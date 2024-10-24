import os
import pathlib
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import typing
import types

import psutil
import requests

REPO_URL = 'https://github.com/nearprotocol/nearcore'
WORKDIR = pathlib.Path('/datadrive')
BUILDS_DIR = WORKDIR / 'builds'
REPO_DIR = WORKDIR / 'nearcore'
FUZZER_CMD_PORT = 7055


def mkdirs(*paths: pathlib.Path) -> None:
    """Creates specified directories and all their parent directories."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def rmdirs(*paths: pathlib.Path) -> None:
    """Recursively removes all given paths."""
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


def format_duration(seconds: float) -> str:
    """Returns duration (given in seconds) in human-readable format."""
    if seconds < 1:
        return f'{int(seconds * 1000)} milliseconds'
    if seconds < 10:
        return f'{seconds:.1f} seconds'
    num = int(seconds)
    if num < 60:
        return f'{int(num)} seconds'
    if num < 3600:
        return f'{num // 60}:{num % 60:02}'
    return f'{num // 3600}:{num // 60 % 60:02}:{num % 60:02}'


def _kill_process_tree(pid: int) -> None:
    """Kills a process tree (including grandchildren).

    Sends SIGTERM to the process and all its descendant and waits for them to
    terminate.  If a process doesn't terminate within five seconds, sends
    SIGKILL to remaining stragglers.

    Args:
        pid: Process ID of the parent whose process tree to kill.
    """

    def send_to_all(procs: list[psutil.Process], sig: int) -> None:
        for proc in procs:
            try:
                proc.send_signal(sig)
            except psutil.NoSuchProcess:
                pass

    proc = psutil.Process(pid)
    procs = proc.children(recursive=True) + [proc]
    print(f'Sending SIGTERM to {pid} process tree', file=sys.stderr)
    send_to_all(procs, signal.SIGTERM)
    _, procs = psutil.wait_procs(procs, timeout=5)
    if procs:
        print(f'Sending SIGKILL to {len(procs)} remaining processes',
              file=sys.stderr)
        send_to_all(procs, signal.SIGKILL)


_Command = typing.Sequence[typing.Union[str, pathlib.Path]]


class Runner:
    """Class for running commands redirecting their output to files."""

    def __init__(self, outdir: typing.Optional[pathlib.Path] = None) -> None:
        """Initialises the object.

        If outdir is given creates "stdout" and "stderr" files in given
        directory and redirects all output from commands to those files.  In
        this case, it’s caller’s responsibility to clean up the files and
        guarantee that "stdout" and "stderr" file names are available and won’t
        conflict with anything.

        Otherwise, creates two temporary files and redirects output there.

        Args:
            outdir: Optionally a directory to create "stdout" and "stderr" files
                in.
        """
        # pylint: disable=consider-using-with
        if outdir:
            self.stdout = typing.cast(typing.BinaryIO,
                                      open(outdir / 'stdout', 'w+b'))
            self.stderr = typing.cast(typing.BinaryIO,
                                      open(outdir / 'stderr', 'w+b'))
        else:
            self.stdout = typing.cast(typing.BinaryIO, tempfile.TemporaryFile())
            self.stderr = typing.cast(typing.BinaryIO, tempfile.TemporaryFile())
        self.__last_cwd: typing.Optional[pathlib.Path] = None

    def __call__(self,
                 cmd: _Command,
                 *,
                 cwd: pathlib.Path,
                 check: bool = False,
                 timeout: int = 3 * 3600,
                 print_cmd: typing.Optional[_Command] = None,
                 **kw: typing.Any) -> int:
        """Calls given command after printing it to standard error.

        If directory the command is run in is different than one previous
        command was run prints a "+ cd <dir>" line to standard error.
        Afterwards, prints "+ <command>" to standard error and executes the
        command.

        Command’s output as well as the aforementioned log messages are
        redirected to separate temporary files.

        Args:
            cmd: Command to execute.
            cwd: Directory to execute the command in.
            check: Whether to raise a subprocess.CalledProcessError exception if
                command fails.  By default, rather than rising the exception,
                False is returned.
            timeout: Time in seconds to allow the command to run.  If the
                command does not finish in allotted time it’s terminated and
                subprocess.TimeoutExpired expcetion is risen.
            print_cmd: If specified, a command to print to standard error
                instead of cmd.
            kw: Keyword arguments passed to subprocess.run() function.
        Returns:
            Command’s exit code.
        Raises:
            subprocess.CalledProcessError: If check argument is True and command
                returned non-zero exit code.
            subprocess.TimeoutExpired: If the command run longer that timeout
                seconds.
        """
        cwd = self.log_command(print_cmd or cmd, cwd)
        with subprocess.Popen(cmd,
                              cwd=cwd,
                              stdin=subprocess.DEVNULL,
                              stdout=self.stdout,
                              stderr=self.stderr,
                              **kw) as proc:
            duration = time.monotonic()
            try:
                ret = proc.wait(timeout)
            except subprocess.TimeoutExpired:
                self.stderr.write(b'# Command timed out\n')
                _kill_process_tree(proc.pid)
                raise
            duration = time.monotonic() - duration

        if ret or duration >= 30:
            dur = format_duration(seconds=duration)
            self.stderr.write((f'# command finished with exit code {ret} '
                               f'after {dur}\n').encode('utf-8'))
        if check and ret:
            raise subprocess.CalledProcessError(ret, cmd)
        return ret

    def log_command(self, cmd: _Command, cwd: pathlib.Path) -> pathlib.Path:
        """Logs information about command about to be executed.

        Args:
            cmd: Command which is going to be executed.
            cwd: Directory in which the command will be executed.
        Returns:
            Resolved cwd (i.e. cwd turned into an absolute path).
        """

        def log(cmd: typing.Iterable[typing.Any]) -> None:
            msg = '+ ' + ' '.join(shlex.quote(str(arg)) for arg in cmd) + '\n'
            sys.stderr.write(msg)
            self.stderr.write(msg.encode('utf-8'))

        cwd = cwd.resolve()
        if self.__last_cwd != cwd:
            self.__last_cwd = cwd
            log(('cd', cwd))
        log(cmd)
        self.stderr.flush()
        return cwd

    def log_traceback(self) -> None:
        """Writes traceback to standard error and command’s standard error."""
        exc = traceback.format_exc()
        sys.stderr.write(exc)
        self.stderr.write(exc.encode('utf-8'))
        self.stderr.flush()

    def __enter__(self) -> 'Runner':
        return self

    def __exit__(self, *_: typing.Any) -> None:
        self.stdout.close()
        self.stderr.close()


def checkout(sha: str, runner: Runner) -> bool:
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
    if REPO_DIR.is_dir():
        result = subprocess.run(
            ('git', 'rev-parse', '--verify', '-q', sha + '^{commit}'),
            stdout=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            check=False,
            cwd=REPO_DIR)
        # yapf: disable
        if ((result.returncode == 0 or
             runner(('git', 'remote', 'update', '-p'), cwd=REPO_DIR) == 0) and
            runner(('git', 'checkout', '-f', sha), cwd=REPO_DIR) == 0):
            return True
        # yapf: enable
        rmdirs(REPO_DIR)

    return (runner(('git', 'clone', REPO_URL), cwd=REPO_DIR.parent) == 0 and
            runner(('git', 'checkout', '-f', sha), cwd=REPO_DIR) == 0)


def get_ip() -> tuple[int, str]:
    """Returns private IPv4 address of the current host as an integer.

    Returns:
        An (ip_int, ip_str) pair where first element is IP as a 32-bit unsigned
        integer and the second is string representation of the IP.
    Raises:
        SystemExit: if no private IP address could be found for the host.
    """
    for iface in psutil.net_if_addrs().values():
        for addr in iface:
            if addr.family != socket.AF_INET:
                continue
            ip_addr = typing.cast(
                int,
                struct.unpack('!I', socket.inet_aton(addr.address))[0])
            # Check if it's a private address.  We don't want to return any kind
            # of public addresses or localhost.
            if ((ip_addr & 0xFF000000) == 0x0A000000 or  # 10.0.0.0/8
                (ip_addr & 0xFFF00000) == 0x0C100000 or  # 172.16.0.0/12
                (ip_addr & 0xFFFF0000) == 0xC0A80000):  # 192.168.0.0/16bbb
                return ip_addr, addr.address
    raise SystemExit('Unable to determine private IP address')


def int_to_ip(addr: int) -> str:
    """Formats IPv4 represented as an integer as a string."""
    return socket.inet_ntoa(struct.pack('!I', addr))


def setup_environ() -> None:
    """Configures environment variables for workers and builders."""
    # Look for Cargo.
    path = WORKDIR / 'home/cargo'
    if (path / 'bin/cargo').is_file():
        os.environb[b'CARGO_HOME'] = os.fsencode(path)
        os.environb[b'RUSTUP_HOME'] = os.fsencode(WORKDIR / 'home/rustup')
        cargo_bin = path / 'bin'
    else:
        cargo_bin = pathlib.Path.home() / '.cargo/bin'

    # Add Cargo to PATH and remove various unnecessary directories
    pathsep = os.fsencode(os.pathsep)
    paths = os.environb.get(b'PATH', os.fsencode(os.defpath)).split(pathsep)
    paths = [
        path for path in paths
        if path.startswith(b'/') and not path.endswith(b'/sbin')
    ]
    if cargo_bin.exists():
        paths.insert(0, os.fsencode(cargo_bin))
    os.environb[b'PATH'] = pathsep.join(paths)

    # TODO: remove once compiler bug is fixed:
    # https://github.com/rust-lang/rust/issues/131564
    os.environb[b'CARGO_INCREMENTAL'] = b'0'

    # Configure Cargo builds to make compilation faster.  We don’t need
    # super-optimised builds thus disabling LTO and using lld.
    os.environb[b'CARGO_PROFILE_RELEASE_LTO'] = b'false'
    os.environb[b'CARGO_PROFILE_DEV_DEBUG'] = b'0'
    os.environb[b'CARGO_PROFILE_TEST_DEBUG'] = b'0'
    if shutil.which('lld'):
        os.environb[b'RUSTFLAGS'] = b'-C link-arg=-fuse-ld=lld'

    # Tell tests this is NayDuck
    os.environb[b'NAYDUCK'] = b'1'
    os.environb[b'NIGHTLY_RUNNER'] = b'1'

    os.environb.pop(b'NEAR_PYTEST_CONFIG', None)


class PausedFuzzers:
    """A context manager which pauses fuzzer running on the host.

    NayDuck workers share their hosts with fuzzers which consume all the CPU
    they can get.  To make performance of tests more consistent we pause the
    fuzzers while worker is running a test and run them only when worker is
    idling (which is most of the time).

    This object is used as a context manager.  On entry the fuzzer is paused; on
    exit it’s resumed.

    If the fuzzer is not detected on the machine, this is a no-op.  Detection of
    running fuzzer is by checking whether nayduck-fuzzer systemd service is
    active.
    """

    SERVICE = 'nayduck-fuzzer.service'

    @classmethod
    def _perform_action(cls, action: str) -> None:
        """Perform an action (pause or resume) without risking an exception."""
        cmd = ('systemctl', 'is-active', '--quiet', cls.SERVICE)
        if subprocess.call(cmd) != 0:
            print(f'{cls.SERVICE} not active, won’t {action} it',
                  file=sys.stderr)
            return

        last_exception = None
        for num in range(3):
            url = f'http://127.0.0.1:{FUZZER_CMD_PORT}/{action}'
            try:
                requests.get(url)
                return
            except requests.exceptions.RequestException as ex:
                last_exception = ex
                time.sleep(1.5**num)
        print(f'Failed to {action} fuzzers: {last_exception}', file=sys.stderr)

    def __enter__(self) -> None:
        self._perform_action('pause')

    def __exit__(self, exc_type: type[BaseException], exc_value: BaseException,
                 exc_tb: types.TracebackType) -> None:
        self._perform_action('resume')
