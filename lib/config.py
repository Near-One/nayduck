import json
import pathlib
import typing

_SENTINEL = object()
_T = typing.TypeVar('_T')

CONFIG_DIR = pathlib.Path.home() / '.nayduck'


def _identity(obj: _T) -> _T:
    """Returns its argument."""
    return obj


class Config(dict[str, typing.Any]):
    """A wrapper for configuration read from a file.

    The object provides req and take methods which behave like __getitem__ and
    pop respectively except that they throw SystemExit if the key is missing or
    holds a None or '' value.

    Attributes:
        path: Path to the file the configuration was loaded from.
    """

    def __init__(self, data: dict[str, typing.Any], path: pathlib.Path) -> None:
        super().__init__(data)
        self.path = path

    def req(self,
            key: str,
            conv: typing.Callable[[typing.Any], _T] = _identity) -> _T:
        """Returns value associated with given key.

        Args:
            key: Key to look for the value under.
            conv: Function to convert the read value into value to return.
        Raises:
            SystemExit: if key is missing, is empty (i.e. None or empty string)
                or conv function raises an exception.
        """
        return self._return(key, conv, self.get(key, None))

    def take(self,
             key: str,
             conv: typing.Callable[[typing.Any], _T] = _identity) -> _T:
        """Removes given key from the mapping and returns its old value.

        Args:
            key: Key to look for the value under.
            conv: Function to convert the read value into value to return.
        Raises:
            SystemExit: if key is missing, is empty (i.e. None or empty string)
                or conv function raises an exception.
        """
        return self._return(key, conv, self.pop(key, None))

    def _return(self, key: str, conv: typing.Callable[[typing.Any], _T],
                value: typing.Any) -> _T:
        """Returns converted value; raises SystemExit if it's malformed."""
        if value is None or value == '':
            raise SystemExit(f'{self.path}: missing or empty "{key}" value')
        try:
            return conv(value)
        except Exception as ex:
            raise SystemExit(f'{self.path}: malformed {key}: {ex}') from ex


def load(name: str) -> Config:
    """Loads JSON configuration from given file.

    Reads JSON value from a `~/.nayduck/<name>.json` file (where `<name>` is the
    value of the `name` argument).  The value in the file must be a dictionary;
    the function raises an exception if it's not.

    Args:
        name: Base name of the configuration file.
    Returns:
        A Config object holding the configuration as well as path to the file.
    Raises:
        SystemExit: if file could not be opened, contains malformed JSON or
            contains value which is not a dictionary.
    """
    path = CONFIG_DIR / name / f'{name}.json'
    try:
        with open(path, encoding='utf-8') as rd:
            value = json.load(rd)
    except OSError as ex:
        raise SystemExit(f'{path}: {ex.strerror}') from ex
    except json.JSONDecodeError as ex:
        raise SystemExit(
            f'{path}:{ex.lineno}:{ex.colno}: malformed JSON: {ex.msg}') from ex
    except Exception as ex:
        raise SystemExit(f'{path}: {ex}') from ex
    if not isinstance(value, dict):
        raise SystemExit(f'{path}: value is not a dictionary')
    return Config(typing.cast(dict[str, typing.Any], value), path)
