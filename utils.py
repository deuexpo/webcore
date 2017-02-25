import copy
import functools

class cached_cls_attr:
    ''' A property that caches itself to the class object. '''
    def __init__(self, fget):
        functools.update_wrapper(self, fget, updated=[])
        self.fget = fget

    def __get__(self, obj, cls):
        val = self.fget(cls)
        setattr(cls, self.__name__, val)
        return val

class cached_property:
    ''' A property that is only computed once per instance and then replaces
    itself with an ordinary attribute. Deleting the attribute resets the
    property. '''
    def __init__(self, fget):
        self.__doc__ = getattr(fget, '__doc__')
        self.fget = fget

    def __get__(self, obj, cls):
        if obj is None:
            return self
        val = obj.__dict__[self.fget.__name__] = self.fget(obj)
        return val

class MultiDict(dict):
    ''' This dict stores list of values per key, and behaves exactly like a
    normal dict in that it returns only the last value for any given key.
    There are special methods available to access the full list of values. '''
    def __init__(self, *a, **ka):
        data = {}
        for d in a:
            data.update(d)
        data.update(ka)
        for key, val in data.items():
            self.setlist(key, val)

    def __init__(self, data=None):
        data = data or {}
        for key, val in data.items():
            self.setlist(key, val)

    def __copy__(self):
        result = self.__class__('')
        for key, val in self.lists():
            result.setlist(key, val)
        return result

    def __deepcopy__(self, memo):
        result = self.__class__()
        memo[id(self)] = result
        for key, val in self.lists():
            result.setlist(key, copy.deepcopy(val, memo))
        return result

    def __getitem__(self, key):
        return self.getlist(key)[-1]

    def __repr__(self):
        return '<{}: {}>'.format(self.__class__.__name__, super().__repr__())

    def __setitem__(self, key, value):
        self.setlist(key, [value])

    def _assert_not_empty_list(self, value):
        assert (value and type(value) == list), 'Value must be not empty list'

    def append(self, key, value):
        self.setdefault(key, []).append(value)

    def copy(self):
        return self.__deepcopy__({})

    def dict(self):
        ''' Returns current object as a dict with singular values. '''
        return dict((key, self[key]) for key in self)

    def get(self, key, default=None):
        return self[key] if key in self else default     

    def getlist(self, key):
        return super().__getitem__(key)

    def items(self):
        for key in self:
            yield key, self[key]

    def lists(self):
        return super().items()

    def setdefault(self, key, default=None):
        return super().setdefault(key, [default])

    def setlist(self, key, value):
        self._assert_not_empty_list(value)
        super().__setitem__(key, value)

    def setlistdefault(self, key, default):
        self._assert_not_empty_list(default)
        if key not in self:
            self.setlist(key, default)
        return self.getlist(key)

    def update(self, *a, **ka):
        ''' Replaces existing key lists. '''
        if len(a) > 1:
            raise TypeError('Expected at most 1 arguments, got {}'.format(len(a)))
        if a:
            if isinstance(a[0], self.__class__):
                for key, val in a[0].lists():
                    self.setlist(key, val)
            else:
                try:
                    for key, val in a[0].items():
                        self[key] = val
                except TypeError:
                    raise ValueError('update() takes only dictionary')
        for key, val in ka.items():
            self[key] = val

    def values(self):
        ''' Yield the last value on every key list. '''
        for key in self:
            yield self[key]