import os
import pathlib
import shutil
import socket
import struct
import subprocess
import typing

import psutil

REPO_URL = 'https://github.com/nearprotocol/nearcore'
WORKDIR = pathlib.Path('/datadrive')
BUILDS_DIR = WORKDIR / 'builds'
REPO_DIR = WORKDIR / 'nearcore'


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
    return [
        directory / entry
        for entry in os.listdir(directory)
        if entry.startswith('test')
    ]


class Runner:

    def __init__(self, capture=False):
        self._stdout_data: typing.Sequence[typing.Union[str, bytes]] = []
        self._stderr_data: typing.Sequence[typing.Union[str, bytes]] = []
        if capture:
            self._stdout = self._stderr = subprocess.PIPE
        else:
            self._stdout = self._stderr = None

    def __call__(self, cmd: typing.Sequence[str], **kw: typing.Any) -> bool:
        res = subprocess.run(cmd,
                             **kw,
                             check=False,
                             stdin=subprocess.DEVNULL,
                             stdout=self._stdout,
                             stderr=self._stderr)
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


def checkout(sha: str, runner: typing.Optional[Runner] = None) -> bool:
    """Checks out given SHA in the nearcore repository.

    If the repository directory exists updates the origin remote and then checks
    out the SHA.  If that fails, deletes the directory, clones the upstream and
    tries to check out the commit again.

    If the repository directory does not exist, clones the origin and then tries
    to check out the commit.

    The repository directory will be located in REPO_DIR.

    Args:
        sha: Commit SHA to check out.
    Returns:
        Whether operation succeeded.
    """
    runner = runner or Runner()
    if REPO_DIR.is_dir():
        print('Checkout', sha)
        result = subprocess.run(
            ('git', 'rev-parse', '--verify', '-q', sha + '^{commit}'),
            stdout=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            check=False,
            cwd=REPO_DIR)
        if ((result.returncode or runner(
            ('git', 'remote', 'update', '-p'), cwd=REPO_DIR)) and runner(
                ('git', 'checkout', sha), cwd=REPO_DIR)):
            return True

    print('Clone', sha)
    rmdirs(REPO_DIR)
    return (runner(('git', 'clone', REPO_URL), cwd=WORKDIR) and runner(
        ('git', 'checkout', sha), cwd=REPO_DIR))


def get_ip() -> int:
    """Returns private IPv4 address of the current host as an integer.

    Returns:
        A string with the hosts private IP address.
    Raises:
        SystemExit: if no private IP address could be found for the host.
    """
    for iface in psutil.net_if_addrs().values():
        for addr in iface:
            if addr.family != socket.AF_INET:
                continue
            ip_addr = struct.unpack('!I', socket.inet_aton(addr.address))[0]
            # Check if it's a private address.  We don't want to return any kind
            # of public addresses or localhost.
            if ((ip_addr & 0xFF000000) == 0x0A000000 or  # 10.0.0.0/8
                (ip_addr & 0xFFF00000) == 0x0C100000 or  # 172.16.0.0/12
                (ip_addr & 0xFFFF0000) == 0xC0A80000):  # 192.168.0.0/16bbb
                return ip_addr
    raise SystemExit('Unable to determine private IP address')


def int_to_ip(addr: int) -> str:
    """Formats IPv4 represented as an integer as a string."""
    return socket.inet_ntoa(struct.pack('!I', addr))


def setup_environ() -> None:
    """Configures environment variables for workers and masters."""
    os.environ.update(CARGO_PROFILE_RELEASE_LTO='false',
                      CARGO_PROFILE_DEV_DEBUG='0',
                      CARGO_PROFILE_TEST_DEBUG='0')
    if shutil.which('lld'):
        os.environ['RUSTFLAGS'] = '-C link-arg=-fuse-ld=lld'
