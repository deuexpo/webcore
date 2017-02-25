__version__ = '0.1'

import functools
import http.cookies
import traceback

from .request import HTTPRequest
from .response import HTTPError, HTTPResponse
from .route import Route
from .utils import MultiDict

class App:
    def __init__(self):
        self.GET = MultiDict()
        self.POST = MultiDict()
        self.FILES = {}
        self.COOKIES = {}
        self.cookies = http.cookies.SimpleCookie()
        self.plugins = Plugins()
        self.request = HTTPRequest()
        self.routes = []

    def __call__(self, environ, start_response):
        self.GET.clear()
        self.POST.clear()
        self.FILES.clear()
        self.COOKIES.clear()
        self.cookies.clear()
        self.request.bind(environ)
        self.COOKIES.update(self.request.COOKIES)
        self.GET.update(self.request.GET)
        self.POST.update(self.request.POST)
        self.FILES.update(self.request.FILES)
        try:
            try:
                for route in self.routes:
                    if route.match(self.request.path):
                        output = route()
                        if isinstance(output, HTTPResponse):
                            raise output
                        else:
                            raise HTTPResponse(output)
                self.notfound()
            except (HTTPResponse, KeyboardInterrupt, MemoryError, SystemExit):
                raise
            except:
                environ['wsgi.errors'].write(traceback.format_exc())
                raise HTTPError()
        except HTTPResponse as r:
            headers = []
            for k, v in r.headers.items():
                headers.append((k, v))
            if self.cookies:
                for cookie in self.cookies.values():
                    headers.append(('Set-Cookie', cookie.output(header='')))
            start_response(r.status, headers)
            return r.body

    def delcookie(self, key, path='/', domain=None):
        self.setcookie(key, max_age=0, path=path, domain=domain,
                       expires='Thu, 01-Jan-1970 00:00:00 GMT')

    def error(self, text):
        self.cookies.clear()
        raise HTTPError(text)

    def install(self, name, plugin):
        assert not hasattr(self.plugins, name), 'Plugin "{0}" is already installed'.format(name)
        setattr(self.plugins, name, plugin)

    def notfound(self, text='Not Found'):
        self.cookies.clear()
        raise HTTPResponse(text, 404)

    def redirect(self, url, code=302):
        ''' Redirect with one of the following codes:
            301 Moved Permamnetly
            302 Moved Temporaly '''
        code = 301 if int(code)==301 else 302
        raise HTTPResponse(None, code, {'Location': str(url)})

    '''
        def redirect(self, url, code=302):
            if self.request.is_ajax:
                code = 200
                if url[0:7] not in ['http://', 'https:/']:
                    env = self.request.environ
                    url = env['wsgi.url_scheme'] + '://'+env['HTTP_HOST'] + url
                headers = {'Content-Type': 'text/javascript; charset=utf-8'}
                body = 'window.location = "' + url + '";'
            else:
                body = ''
                code = 301 if int(code)==301 else 302
                headers = {'Location': url}
            raise HTTPResponse(body, code, headers)
    '''

    def route(self, path, callback=None):
        for route in self.routes:
            if route.pattern == path:
                raise ValueError('Duplicate route("{}", {})'.format(path, route.callback.__module__))
        def decorator(callback):
            original = callback
            for plugin in self.plugins:
                if hasattr(plugin, 'apply'):
                    callback = plugin.apply(callback)
            route = Route(path, callback)
            self.routes.append(route)
            return original
        return decorator(callback) if callback else decorator

    def run(self, host='localhost', port=8000, app=None):
        import wsgiref.simple_server
        app = app if app else self
        httpd = wsgiref.simple_server.make_server(host, port, app)
        print('Listening on http://{0}:{1}/'.format(host, str(port)))
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
            print('Server stops http://{0}:{1}/'.format(host, str(port)))

    def setcookie(self, key, value='', max_age=None, expires=None, path='/',
                  domain=None, secure=None, httponly=False):
        self.cookies[key] = value
        if max_age is not None:
            self.cookies[key]['max-age'] = max_age
        if expires is not None:
            self.cookies[key]['expires'] = expires
        if path is not None:
            self.cookies[key]['path'] = path
        if domain is not None:
            self.cookies[key]['domain'] = domain
        if secure:
            self.cookies[key]['secure'] = True
        if httponly:
            self.cookies[key]['httponly'] = True

class Plugins:
    def __init__(self):
        super().__setattr__('plugins', [])

    def __delattr__(self, key):
        raise AttributeError('Read-only attribute')

    def __setattr__(self, key, val):
        if hasattr(self, key):
            raise AttributeError('Read-only attribute')
        self.plugins.insert(0, val)
        super().__setattr__(key, val)

    def __iter__(self):
        return iter(self.plugins)
