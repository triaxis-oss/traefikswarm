# import all commands here

import importlib

__all__ = [
    'config',
    'forwarder',
    'expose',
    'unexpose',
    'service',
]

commands = [importlib.import_module(f'.{cmd}', __name__) for cmd in __all__]
vars().update({cmd.__name__:cmd for cmd in commands})
