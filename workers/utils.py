import os
import pathlib
import shutil
import subprocess
import typing


def mkdirs(*paths: pathlib.Path) -> None:
    """Creates specified directories and all their parent directories."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def rmdirs(*paths: pathlib.Path) -> None:
    """Recursively removes all given paths."""
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


def list_test_node_dirs() -> typing.List[pathlib.Path]:
    """Returns a list of paths matching ~/.near/test* glob."""
    directory = pathlib.Path.home() / '.near'
    if not directory.is_dir():
        return []
    return [directory / entry
            for entry in os.listdir(directory)
            if entry.startswith('test')]
