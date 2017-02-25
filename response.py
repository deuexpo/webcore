import http.client

class HTTPResponse(Exception):
    def __init__(self, body=None, code=200, headers=None):
        self.code = int(code)
        self.headers = headers or {}
        self.headers.setdefault('Content-Type', 'text/html; charset=utf-8')
        if body is None:
            self.body = []
        elif isinstance(body, (str, bytes, bytearray)):
            value = body.encode() if isinstance(body, str) else bytes(body)
            self.body = [value]
            self.headers['Content-Length'] = str(len(value))
        else:
            self.body = body

    def __repr__(self):
        if isinstance(self.body, (list, tuple)):
            info = '{} bytes'.format(sum(map(len, self.body)))
        else:
            info = 'streamed'
        return '<{} {} "{}"'.format(self.__class__.__name__, info, self.status)

    @property
    def status(self):
        status = http.client.responses.get(self.code)
        if not status:
            raise AttributeError('Invalid status code "{}"'.format(self.code))
        return '{} {}'.format(self.code, status)

class HTTPError(HTTPResponse):
    def __init__(self, body=None, code=500):
        body = 'Internal Server Error' if body is None else body
        headers = {'Content-Type': 'text/plain; charset=utf-8'}
        super().__init__(body, code, headers)
