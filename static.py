import mimetypes
import os.path
import time
from . import HTTPError, HTTPResponse, notfound, request

def sendfile(filepath, block_size=8192, download=False):
    ''' Static file sender, use it only for development (not for production).
        :filepath: Full path of the file to be send.
        :block_size: File is sent by blocks with this size.
        :download: If True, ask the browser to open a "Save as..." dialog
            instead of opening the file with the associated program. You can
            specify a custom filename as a string. If not specified, the
            original filename is used (default: False).
    '''
    filepath = os.path.abspath(filepath)
    filename = os.path.basename(filepath)
    if not os.path.isfile(filepath):
        notfound()
    if not os.access(filepath, os.R_OK):
        raise HTTPError('Access Denied', 403)
    headers = {}
    mimetype = mimetypes.guess_type(filename)[0]
    if not mimetype:
        mimetype = 'application/octet-stream'
    headers['Content-Type'] = mimetype
    headers['Content-Length'] = str(os.path.getsize(filepath))
    mtime = os.path.getmtime(filepath)
    mtime = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(mtime))
    headers['Last-Modified'] = mtime
    if download:
        download = filename if download==True else download
        headers['Content-Disposition'] = 'attachment; filename="{0}"'.format(download)

    if 'wsgi.file_wrapper' in request.environ:
        fp = open(filepath, 'rb')
        file_iterator = request.environ['wsgi.file_wrapper'](fp, block_size)
    else:
        file_iterator = stream(filepath, block_size)
    raise HTTPResponse(file_iterator, headers=headers)

def stream(filepath, block_size):
    with open(filepath, 'rb') as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            yield block