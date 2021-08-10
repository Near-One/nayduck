import json
import pathlib
import typing

_CFG_DIR = pathlib.Path.home() / '.nayduck'


def get_config(
        name: str) -> typing.Tuple[typing.Dict[str, typing.Any], pathlib.Path]:
    """Returns contents of a JSON configuration file.

    Reads JSON value from a `~/.nayduck/<name>.json` file (where `<name>` is the
    value of the `name` argument).  The value in the file must be a dictionary;
    the function raises an exception if it's not.

    Args:
        name: Base name of the configuration file.
    Returns:
        A (config, config_file) tuple where first element is value read from the
        configuration file and the second is path to that file.
    Raises:
        SystemExit: if file could not be opened, contains malformed JSON or
            contains value which is not a dictionary.
    """
    path = _CFG_DIR / f'{name}.json'
    try:
        with open(path) as rd:
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
    return value, path
