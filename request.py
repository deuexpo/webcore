import cgi
import collections
import functools
import os
import re
import unicodedata
import urllib.parse

from http.cookies import SimpleCookie
from io import BytesIO
from tempfile import TemporaryFile

from .response import HTTPError
from .utils import cached_property, MultiDict

class CachedToEnviron:
    def __init__(self, fget):
        functools.update_wrapper(self, fget, updated=[])
        self.fget = fget
        self.key = 'request.' + fget.__name__

    def __get__(self, obj, cls):
        if obj is None:
            return self
        if self.key not in obj.environ:
            obj.environ[self.key] = self.fget(obj)
        return obj.environ[self.key]

    def __set__(self, obj, value):
        raise AttributeError('Read-only attribute')

    def __delete__(self, obj):
        raise AttributeError('Read-only attribute')

class FileUpload:
    def __init__(self, file, filename, headers=None):
        # An open file(-like) object (BytesIO buffer or temporary file)
        self.file = file
        # Raw filename as sent by the client
        self.raw_filename = filename
        self.headers = {}
        if headers:
            for key, val in headers.items():
                key = key.title().replace('_','-')
                self.headers[key] = val

    def _copy_file(self, fp, chunk_size=2**16):
        offset = self.file.tell()
        while True:
            buffer = self.file.read(chunk_size)
            if not buffer:
                break
            fp.write(buffer)
        self.file.seek(offset)

    @cached_property
    def filename(self):
        ''' Name of the file on the client file system, but normalized to
        ensure file system compatibility (lowercase, no whitespace, no path
        separators, no unsafe characters, ASCII only). An empty filename
        will return ''. '''
        fname = self.raw_filename
        if isinstance(fname, str):
            fname = unicodedata.normalize('NFKD', fname)
            fname = fname.encode('ascii', 'ignore')
        fname = fname.decode('ascii', 'ignore')
        fname = os.path.basename(fname.replace('\\', os.path.sep))
        fname = re.sub(r'[^a-zA-Z0-9-_.\s]', '', fname).strip().lower()
        fname = re.sub(r'[-\s]+', '-', fname.strip())
        while fname.startswith(('.', '-')) or fname.endswith('.'):
            fname.strip('.').lstrip('-')
        return fname or ''

    def save(self, filepath, overwrite=False, chunk_len=2**16):
        ''' Save file to a disk or copy its content to an open file(-like)
        object. Existing files are not overwritten by default (IOError).
            "filepath": File path or file(-like) object. If the directory
                        doesn`t exist, it will be created recursively.
            "overwrite": If True, replace existing files. (default: False)
            "chunk_len": Bytes to read at a time. (default: 64kb)
        '''
        if isinstance(filepath, str): # Except file-likes here
            dirname = os.path.dirname(filepath)
            if not os.path.isdir(dirname):
                os.makedirs(dirname)
            if not overwrite and os.path.exists(filepath):
                raise IOError('File exists.')
            with open(filepath, 'wb') as fp:
                self._copy_file(fp, chunk_len)
        else:
            self._copy_file(filepath, chunk_len)

    @cached_property
    def size(self):
        self.file.seek(0, 2)
        size = self.file.tell()
        self.file.seek(0)
        return size

class HTTPRequest:
    __slots__ = ('environ')

    # Maximum size of memory buffer for reading request body in bytes.
    MEMFILE_MAX = 102400

    def __init__(self, environ=None):
        self.environ = environ or {}

    def __delitem__(self, key):
        raise KeyError('The request dictionary is read-only.')

    def __getitem__(self, key):
        return self.environ[key]

    def __iter__(self):
        return iter(self.environ)

    def __len__(self):
        return len(self.environ)

    def __setitem__(self, key, value):
        raise KeyError('The request dictionary is read-only.')

    def __repr__(self):
        return '<%s: %s %s>' % (self.__class__.__name__, self.method, self.url)

    def __getattr__(self, name):
        """ Search in self.environ for additional user defined attributes. """
        try:
            var = self.environ['bottle.request.ext.%s' % name]
            return var.__get__(self) if hasattr(var, '__get__') else var
        except KeyError:
            raise AttributeError('Attribute %r not defined.' % name)

    def __repr__(self):
        methods = [v for v in dir(self) if not v.startswith('_')]
        for name in methods: getattr(self, name)
        env = [
            k+': '+str(v) for k, v in self.environ.items()
            if k.startswith('request.')
        ]
        return str('\n'.join(sorted(env)))

    @CachedToEnviron
    def _body(self):
        iter_body = self._iter_chunked if self.is_chunked else self._iter_body
        read_func = self.environ['wsgi.input'].read
        body, body_size, is_temp_file = BytesIO(), 0, False
        for part in iter_body(read_func, self.MEMFILE_MAX):
            body.write(part)
            body_size += len(part)
            if not is_temp_file and body_size > self.MEMFILE_MAX:
                body, mem = TemporaryFile(mode='w+b'), body
                body.write(mem.getvalue())
                is_temp_file = True
                del mem
        self.environ['wsgi.input'] = body
        body.seek(0)
        return body

    def _iter_body(self, read, bufsize):
        conlen = self.content_length
        while conlen:
            part = read(min(conlen, bufsize))
            if not part:
                break
            yield part
            conlen -= len(part)

    def _iter_chunked(self, read, bufsize):
        err = HTTPError('Error while parsing chunked body.', 400)
        rn, sem = '\r\n'.encode(), ';'.encode()
        while True:
            header = read(2)
            while header[-2:] != rn:
                c = read(1)
                header += c
                if not c:
                    raise err
                if len(header) > bufsize:
                    raise err
            size, sep, extensions = header.partition(sem)
            try:
                chunk_len = int(size.decode().strip(), 16)
            except ValueError:
                raise err
            if chunk_len == 0:
                break
            buffer = b''
            while chunk_len > 0:
                if not buffer:
                    buffer = read(min(chunk_len, bufsize))
                part, buffer = buffer[:chunk_len], buffer[chunk_len:]
                if not part:
                    raise err
                yield part
                chunk_len -= len(part)
            if read(2) != rn:
                raise err

    @CachedToEnviron
    def _post(self):
        ''' Form values parsed from a POST request body. The result is
        returned as a dict. All keys are strings, all values are lists of
        strings or FileUpload objects. '''
        if self.content_type.startswith('multipart/'):
            post = {}
            env = {'QUERY_STRING': ''} # Empty query insure only POST data
            for key in ('REQUEST_METHOD', 'CONTENT_TYPE', 'CONTENT_LENGTH'):
                if key in self.environ:
                    env[key] = self.environ[key]
            data = cgi.FieldStorage(fp=self._body, environ=env, keep_blank_values=True)
            self.environ['cgi.FieldStorage'] = data  # http://bugs.python.org/issue18394
            data = data.list or []
            for item in data:
                if item.filename:
                    post[item.name] = FileUpload(item.file, item.filename, item.headers)
                else:
                    if item.name in post:
                        post[item.name].append(item.value)
                    else:
                        post[item.name] = [item.value]
            return post
        else:
            # If not "multipart" we default to "application/x-www-form-urlencoded"
            conlen = self.content_length
            if conlen > self.MEMFILE_MAX:
                raise HTTPError('Request too large', 413)
            body = self._body.read(conlen).decode()
            return urllib.parse.parse_qs(body, keep_blank_values=True)

    @CachedToEnviron
    def COOKIES(self):
        cookies = SimpleCookie(self.environ.get('HTTP_COOKIE', '')).values()
        return {c.key: c.value for c in cookies}

    @CachedToEnviron
    def FILES(self):
        ''' File uploads are stored here. The result is returned as a dict.
        All keys are strings, all values are FileUpload objects. '''
        files = {}
        for key, val in self._post.items():
            if isinstance(val, FileUpload):
                files[key] = val
        return files

    @CachedToEnviron
    def GET(self):
        query = self.environ.get('QUERY_STRING', '')
        data = urllib.parse.parse_qs(query, keep_blank_values=True)
        return MultiDict(data)

    @CachedToEnviron
    def POST(self):
        ''' Form values parsed from a POST request body. The result is
        returned as a dict. All keys are strings, all values are lists of
        strings. File uploads are stored separately in self.FILES. '''
        post = {}
        for key, val in self._post.items():
            if not isinstance(val, FileUpload):
                post[key] = val
        return MultiDict(post)

    bind = __init__

    @CachedToEnviron
    def content_length(self):
        ''' The request body length as an integer. The client is responsible to
        set this header. Otherwise, self._body will be empty and 0 is returned. '''
        return int(self.environ.get('CONTENT_LENGTH') or 0)

    @CachedToEnviron
    def content_type(self):
        ''' The Content-Type header as a lowercase-string (default: empty). '''
        return self.environ.get('CONTENT_TYPE', '').lower()

    def get(self, value, default=None):
        return self.environ.get(value, default)

    @CachedToEnviron
    def is_ajax(self):
        ''' True if the request was triggered by a XMLHTTPRequest. This only
        works with JavaScript libraries that support the "X-Requested-With"
        header (most of the popular libraries do). '''
        requested_with = self.environ.get('HTTP_X_REQUESTED_WITH', '')
        return requested_with.lower() == 'xmlhttprequest'

    @CachedToEnviron
    def is_chunked(self):
        ''' True if HTTP header contains "Transfer-Encoding: chunked" '''
        return 'chunked' in self.environ.get('HTTP_TRANSFER_ENCODING', '').lower()

    def keys(self):
        return self.environ.keys()

    @CachedToEnviron
    def method(self):
        ''' "REQUEST_METHOD" as an uppercase string. '''
        return self.environ.get('REQUEST_METHOD', 'GET').upper()

    @CachedToEnviron
    def query(self):
        return self.environ.get('QUERY_STRING')
    
    @CachedToEnviron
    def path(self):
        ''' "PATH_INFO" lowercased with exactly one prefixed slash (to fix broken clients). '''
        return '/' + self.environ.get('PATH_INFO', '').lstrip('/').lower()

    @CachedToEnviron
    def remote_addr(self):
        ''' The client IP as a string (can be forged by malicious clients). '''
        route = self.remote_route
        return route[0] if route else None

    @CachedToEnviron
    def remote_route(self):
        ''' A list of all IPs that were involved in this request, starting with
        the client IP and followed by zero or more proxies. This does only work
        if all proxies support the "X-Forwarded-For" header. This information
        can be forged by malicious clients. '''
        proxy = self.environ.get('HTTP_X_FORWARDED_FOR')
        if proxy:
            return [ip.strip() for ip in proxy.split(',')]
        remote = self.environ.get('REMOTE_ADDR')
        return [remote] if remote else []

    @CachedToEnviron
    def url(self):
        ''' The relative URL. '''
        url = self.path
        if self.query:
            url += '?' + self.query
        return url

    @CachedToEnviron
    def urlfull(self):
        ''' The full request URL including hostname and scheme. If your app
        lives behind a reverse proxy or load balancer and you get confusing
        results, make sure that the "X-Forwarded-Host" header is set
        correctly. '''
        return self.urlparts.geturl()

    @CachedToEnviron
    def urlparts(self):
        ''' The self.url string as an urllib.parse.SplitResult tuple.
        The tuple contains (scheme, host, path, query_string and fragment),
        but the fragment is always empty because it is not visible to the
        server. '''
        env = self.environ
        http = env.get('HTTP_X_FORWARDED_PROTO') or env.get('wsgi.url_scheme', 'http')
        host = env.get('HTTP_X_FORWARDED_HOST') or env.get('HTTP_HOST')
        if not host:
            host = env.get('SERVER_NAME', '127.0.0.1')
            port = env.get('SERVER_PORT')
            if port and port != ('80' if http=='http' else '443'):
                host += ':' + port
        http = http.lower()
        host = host.lower()
        return urllib.parse.SplitResult(http, host, self.path, self.query, '')
