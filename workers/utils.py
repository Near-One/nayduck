import os
import pathlib
import shutil
import subprocess
import typing


REPO_URL = 'https://github.com/nearprotocol/nearcore'


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


class Runner:
    def __init__(self, capture=False):
        self._stdout_data: typing.Sequence[typing.Union[str, bytes]] = []
        self._stderr_data: typing.Sequence[typing.Union[str, bytes]] = []
        if capture:
            self._stdout = self._stderr = subprocess.PIPE
        else:
            self._stdout = self._stderr = None

    def __call__(self, cmd: typing.Sequence[str], **kw: typing.Any) -> bool:
        res = subprocess.run(cmd, **kw, check=False, stdin=subprocess.DEVNULL,
                             stdout=self._stdout, stderr=self._stderr)
        if res.stdout:
            self._stdout_data.append(self.__to_bytes(res.stdout))
        if res.stderr:
            self._stderr_data.append(self.__to_bytes(res.stderr))
        return res.returncode == 0

    def write_err(self, data: typing.Any):
        if data:
            self._stderr_data.append(self.__to_bytes(data))

    stdout = property(lambda self: b''.join(self._stdout_data))
    stderr = property(lambda self: b''.join(self._stderr_data))

    @staticmethod
    def __to_bytes(data: typing.Any) -> bytes:
        if isinstance(data, str):
            return data.encode('utf-8')
        if isinstance(data, bytes):
            return data
        return b''


def checkout(sha: str,
             runner: typing.Optional[Runner]=None,
             cwd: typing.Optional[pathlib.Path]=None) -> bool:
    """Checks out given SHA in the nearcore repository.

    If the repository directory exists updates the origin remote and then checks
    out the SHA.  If that fails, deletes the directory, clones the upstream and
    tries to check out the commit again.

    If the repository directory does not exist, clones the origin and then tries
    to check out the commit.

    The repository directory will be located in (WORKDIR / 'nearcore').

    Args:
        sha: Commit SHA to check out.
    Returns:
        Whether operation succeeded.
    """
    runner = runner or Runner()
    repo_dir = (cwd / 'nearcore') if cwd else pathlib.Path('nearcore')
    if repo_dir.is_dir():
        print('Checkout', sha)
        if (runner(('git', 'remote', 'update', '-p'), cwd=repo_dir) and
            runner(('git', 'checkout', sha), cwd=repo_dir)):
            return True

    print('Clone', sha)
    rmdirs(repo_dir)
    return (runner(('git', 'clone', REPO_URL), cwd=cwd) and
            runner(('git', 'checkout', sha), cwd=repo_dir))
