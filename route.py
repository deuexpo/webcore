import inspect
import re

RE_STATIC = re.compile('^[a-z0-9/_-]+$', re.IGNORECASE | re.ASCII)

class Route:
    def __init__(self, pattern, callback=None):
        self.raw_pattern = pattern
        self.pattern = pattern.lower()
        self.reo = None
        if not RE_STATIC.match(self.pattern):
            if self.pattern[0] != '^':
               self.pattern = '^' + self.pattern
            if self.pattern[-1] != '$':
                self.pattern += '$'
            self.reo = re.compile(self.pattern, re.IGNORECASE | re.ASCII)
        self.callback = callback

    def __call__(self):
        return self.callback(*self.values)

    def match(self, path):
        self.values = []
        if self.reo:
            match = self.reo.match(path)
            if match:
                self.values = match.groups()
                return True
        elif path == self.pattern:
            return True
        return False