import http.client

class HTTPResponse(Exception):
    def __init__(self, code=None, headers=None, body=''):
        ''' Format the body to list of bytes, thus, providing execution of
        templates and exceptions inside scripts. '''
        self.code = int(code) or 200
        self.body = []
        if type(body) is bytes:
            self.body.append(body)
        elif isinstance(body, list):
            for i, s in enumerate(body):
                if type(s) is not bytes:
                    s = str(s).encode()
                self.body.append(s)
        elif body is not None:
            self.body.append(str(body).encode())
        self.headers = headers or {}
        if not self.headers.get('Content-Type'):
            self.headers['Content-Type'] = 'text/html; charset=utf-8'
        self.headers['Content-Length'] = str(sum([len(s) for s in self.body]))

    def __repr__(self):
        output = [self.status]
        output.extend([k+': '+v for k, v in self.headers.items()])
        output.append('')
        if self.charset.lower() == 'utf-8':
            body = ''.join([s.decode() for s in self.body])
        else:
            body = ''.join([str(s) for s in self.body])
        output.append(body)
        return '\n'.join(output)

    __str__ = __repr__

    @property
    def charset(self):
        parts = self.headers['Content-Type'].split()
        if len(parts) == 2:
            parts = parts[1].split('=')
            if parts[0] == 'charset' and len(parts) == 2:
                return parts[1]
        return ''
    
    @property
    def status(self):
        status = http.client.responses.get(self.code)
        if not status:
            raise AttributeError('Incorrect response code: ' + str(self.code))
        return str(self.code) + ' ' + status

class HTTPError(HTTPResponse):
    def __init__(self, code=500, body=None):
        body = body or 'Internal Server Error'
        headers = {'Content-Type': 'text/plain; charset=utf-8'}
        super().__init__(code, headers, body)
