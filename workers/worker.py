import concurrent.futures
import contextlib
import json
import os
import pathlib
import random
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import typing

from lib import testspec
from . import blobs
from . import utils
from . import worker_db

DEFAULT_TIMEOUT = 180

_Cmd = typing.Sequence[typing.Union[str, pathlib.Path]]
_EnvB = typing.MutableMapping[bytes, bytes]


def get_test_command(
        test: testspec.TestSpec) -> typing.Tuple[pathlib.Path, _Cmd]:
    """Returns working directory and command to execute for given test.

    Assumes that the repository from which the test should be run is located in
    utils.REPO_DIR directory.

    Args:
        test: Test to return the command for.
    Returns:
        A (cwd, cmd) tuple where first element is working directory in which to
        execute the command given by the second element.
    """
    if test.category in ('pytest', 'mocknet'):
        cwd = utils.REPO_DIR / 'pytest'
        cmd = [sys.executable, 'tests/' + test.args[0]]
        cmd.extend(test.args[1:])
    elif test.category == 'expensive':
        cwd = utils.REPO_DIR
        prefix = test.args[1] + '-'
        for name in os.listdir(utils.REPO_DIR / 'target/expensive'):
            if name.startswith(prefix):
                name = f'target/expensive/{name}'
                cmd = [name, test.args[2], '--exact', '--nocapture']
    else:
        raise ValueError(f'Invalid test command: {test}')
    return cwd, cmd


_LAST_PIP_REQUIREMENTS: typing.Optional[bytes] = None


def install_new_packages(runner: utils.Runner) -> None:
    """Makes sure all Python requirements for the pytests are satisfied.

    Args:
        runner: Runner whose standard output and error files output of the
            command will be redirected into.
    """
    global _LAST_PIP_REQUIREMENTS

    data = (utils.REPO_DIR / 'pytest' / 'requirements.txt').read_bytes()
    if _LAST_PIP_REQUIREMENTS != data:
        runner((sys.executable, '-m', 'pip', 'install', '--user', '-q',
                '--disable-pip-version-check', '--no-warn-script-location',
                '-r', 'requirements.txt'),
               cwd=utils.REPO_DIR / 'pytest',
               check=True)
        _LAST_PIP_REQUIREMENTS = data


def find_backtrace_line(rd: typing.BinaryIO) -> bool:
    """Returns whether the stream contains a `stack backtrace:` pattern."""
    return any('stack backtrace:' in line.decode('utf-8', 'replace').lower()
               for line in rd)


def analyse_test_outcome(test: testspec.TestSpec, ret: int,
                         stdout: typing.BinaryIO) -> str:
    """Returns test's outcome based on exit code and test's output.

    Args:
        test: The test whose result is being analysed.
        ret: Test process exit code.
        stdout: Test's standard output opened as binary file.
    Returns:
        Tests outcome as one of: 'PASSED', 'FAILED' or 'IGNORED'.
    """
    if ret != 0:
        return 'FAILED'
    if test.category != 'expensive':
        return 'PASSED'

    last_line = b''
    for line in stdout:
        line = line.strip()
        if line.decode('utf-8', 'replace') == 'running 0 tests':
            # If user specified incorrect test name the test executable will
            # run no tests since the filter we provide won't match anything.
            # Report that as a failure rather than ignored test.
            return 'FAILED'
        if line:
            last_line = line
            break

    for line in stdout:
        line = line.strip()
        if line:
            last_line = line

    if b'1 ignored' in last_line:
        return 'IGNORED'
    if b'1 failed' in last_line:
        return 'FAILED'
    return 'PASSED'


def execute_test_command(test: testspec.TestSpec, envb: _EnvB, timeout: int,
                         runner: utils.Runner) -> str:
    """Executes a test command and returns test's outcome.

    Args:
        test: The test to execute.  Test command is constructed based on that
            list by calling get_test_command()
        envb: Environment variables to pass to the process.
        timeout: Time in seconds to allow the test to run.  After that time
            passes, the test process will be killed and function will return
            'TIMEOUT' outcome.
        runner: Runner whose standard output and error files output of the
            command will be redirected into.
    Returns:
        Tests outcome as one of: 'PASSED', 'FAILED', 'IGNORED' or 'TIMEOUT'.
    """
    print(f'[RUNNING] {test}', file=sys.stderr)
    stdout_start = runner.stdout.tell()
    stderr_start = runner.stderr.tell()
    envb[b'RUST_BACKTRACE'] = b'1'
    envb[b'NAYDUCK_TIMEOUT'] = str(timeout).encode('ascii')
    try:
        cwd, cmd = get_test_command(test)
        ret = runner(cmd, cwd=cwd, timeout=timeout, env=envb)
    except subprocess.TimeoutExpired:
        return 'TIMEOUT'
    try:
        runner.stdout.seek(stdout_start)
        runner.stderr.seek(stderr_start)
        return analyse_test_outcome(test, ret, runner.stdout)
    finally:
        runner.stdout.seek(0, 2)
        runner.stderr.seek(0, 2)


def run_test(outdir: pathlib.Path, test: testspec.TestSpec, envb: _EnvB,
             runner: utils.Runner) -> str:
    outcome = 'FAILED'
    try:
        dot_near = pathlib.Path.home() / '.near'
        utils.rmdirs(dot_near)
        utils.mkdirs(dot_near)

        outcome = execute_test_command(test, envb, test.full_timeout, runner)
        print(f'[{outcome:<7}] {test}', file=sys.stderr)

        dirs = [
            name for name in os.listdir(dot_near) if name.startswith('test')
        ]
        if dirs:
            for name in dirs:
                (outdir / name).symlink_to(dot_near / name)
    except Exception:
        runner.log_traceback()
    return outcome


class LogFile:
    name: str
    path: pathlib.Path
    stack_trace: bool = False
    size: int
    data: typing.Optional[bytes] = None
    url: typing.Optional[str] = None
    binary: bool

    def __init__(self,
                 name: str,
                 path: pathlib.Path,
                 *,
                 binary: bool = False) -> None:
        self.name = name
        self.path = path
        self.size = path.stat().st_size
        self.binary = binary


_COMPRESSORS = {'.xz': 'xz -9', '.bz2': 'bzip2 -9', '': 'gzip -9'}


def create_tar_archive(*, outfile: pathlib.Path, entries: typing.Iterable[str],
                       cwd: pathlib.Path) -> bool:
    """Creates a compressed tar archive with given entries.

    Args:
        outfile: File to save the archive to.  The name influences what
            compression method will be used for the archive.  If the name ends
            with ‘.bz2’ the archive will be compressed using ‘bzip2’; if it’s
            ‘.xz’ — ‘xz’; otherwise ‘gzip’ will be used.
        entries: Iterable of entries to include in the archive.  The names are
            relative to `cwd`.  This can be an empty iterable.  If it is, the
            function will do nothing other than return false.
        cwd: Directory where to run tar command.
    Returns:
        Whether the file has been created.
    """
    stdin = b''.join(os.fsencode(entry) + b'\0' for entry in sorted(entries))
    if not stdin:
        return False

    compress = _COMPRESSORS.get(outfile.suffix) or 'gzip -9'
    cmd: typing.Sequence[str] = ('tar', '-cvhI', compress, '--exclude-backups',
                                 '--exclude=stderr', '--null', '-T-')
    with tempfile.NamedTemporaryFile(dir=outfile.parent, delete=False) as tmp:
        try:
            print('+ ' + ' '.join(str(arg) for arg in cmd), file=sys.stderr)
            subprocess.run(cmd, check=True, input=stdin, stdout=tmp, cwd=cwd)
            pathlib.Path(tmp.name).rename(outfile)
            return True
        except (subprocess.CalledProcessError, OSError) as ex:
            print(ex, file=sys.stderr)
            os.unlink(tmp.name)
            return False


def cleanup_fuzz_state(fuzz_spec: testspec.FuzzSpec) -> None:
    """Removes artifacts and corpus directories for given fuzz test."""
    fuzz_dir = utils.REPO_DIR / fuzz_spec.subdir
    for i in ('artifacts', 'corpus'):
        for j in set((fuzz_spec.target.replace('_', '-'), fuzz_spec.target)):
            path = fuzz_dir / i / j
            if path.is_dir():
                utils.rmdirs(path)
            elif path.exists():
                path.unlink()


def generate_fuzz_state(outfile: pathlib.Path,
                        fuzz_spec: typing.Optional[testspec.FuzzSpec]) -> bool:
    """Generates a tar archive with fuzz crash artefacts if any are availabe."""
    if not fuzz_spec:
        return False

    fuzz_dir = utils.REPO_DIR / fuzz_spec.subdir
    target_dirs = sorted(
        set((fuzz_spec.target.replace('_', '-'), fuzz_spec.target)))
    entries = (f'{i}/{j}' for i in ('artifacts', 'corpus') for j in target_dirs
               if (fuzz_dir / i / j).is_dir())
    return create_tar_archive(outfile=outfile, entries=entries, cwd=fuzz_dir)


def generate_nodes_state(outfile: pathlib.Path) -> bool:
    """Generates a tar archive with test node’s home directories."""
    directory = outfile.parent
    entries = (name for name in os.listdir(directory)
               if (name.startswith('test') and name.endswith('_finished') and
                   (directory / name).is_dir()))
    return create_tar_archive(outfile=outfile, entries=entries, cwd=directory)


def list_logs(
    directory: pathlib.Path,
    *,
    save_state: bool = False,
    fuzz_spec: typing.Optional[testspec.FuzzSpec] = None
) -> typing.Iterable[LogFile]:
    """Yields all log files to be saved."""
    if save_state:
        outfile = directory / 'fuzz-state.tar.xz'
        if generate_fuzz_state(outfile, fuzz_spec):
            yield LogFile(outfile.name, outfile, binary=True)

        outfile = directory / 'nodes-state.tar.xz'
        if generate_nodes_state(outfile):
            yield LogFile(outfile.name, outfile, binary=True)

    for entry in os.listdir(directory):
        entry_path = directory / entry
        if entry_path.is_dir():
            path = entry_path / 'stderr'
            if path.exists():
                yield LogFile(entry.split('_')[0], path)
        elif entry in ('stderr', 'stdout'):
            yield LogFile(entry, entry_path)


_MAX_SHORT_LOG_SIZE = 10 * 1024


def read_short_log(  # pylint: disable=too-many-branches
        size: int, rd: typing.BinaryIO,
        is_binary: bool) -> typing.Tuple[bytes, bool]:
    """Reads a short log from given file.

    A short log it at most _MAX_SHORT_LOG_SIZE bytes long.  If the file is
    longer than that, the function reads half of the maximum length from the
    beginning and half from the of the file and returns those two fragments
    concatenated with an three dots in between.

    Args:
        size: Actual size of the file.
        rd: The file opened for reading.
        is_binary: Whether the file is a binary file.  If true, the function
            won’t try to do a partial read and use slightly lower limit for the
            maximum short log length.
    Returns:
        A (short_log, is_full) tuple where first element is the short contents
        of the file and the second is whether the short content is the same is
        actually the full content.
    """
    limit = _MAX_SHORT_LOG_SIZE
    if is_binary:
        # Binary files don’t compress as well as text log files so use lower
        # limit for the size we’re willing to store in the database.
        limit //= 2
    if size <= limit:
        data = rd.read(limit + 1)
        if len(data) <= limit:  # Sanity check
            return data, True
        rd.seek(0)

    if is_binary:
        return b'', False

    data = rd.read(_MAX_SHORT_LOG_SIZE // 2 - 3)
    if data:
        pos = len(data)
        limit = max(pos - 6, 1)
        while pos > limit and (data[pos - 1] & 0xC0) == 0x80:
            pos -= 1
        # If we can't find a start byte near the end than it's probably not
        # UTF-8 at all.
        if ((data[pos - 1] & 0xC0) == 0xC0 and
                data[pos - 1:].decode('utf-8', 'ignore') == ''):
            data = data[:pos - 1]

    rd.seek(-_MAX_SHORT_LOG_SIZE // 2 + 2, 2)
    ending = rd.read()
    if ending:
        limit = min(len(ending), 8)
        pos = 0
        while pos < limit and (ending[pos] & 0xC0) == 0x80:
            pos += 1
        if pos < limit:  # If we went too far it doesn't look like UTF-8.
            ending = ending[pos:]

    # Don’t split in the middle of a line unless we’d need to discard too much
    # data to split cleanly.
    pos = data.rfind(b'\n')
    if -1 < pos and len(data) - pos < 500:
        data = data[:pos]
    pos = ending.find(b'\n')
    if -1 < pos < 500:
        ending = ending[pos + 1:]

    # If there are escape codes, make sure the state is reset.
    parts = [data]
    pos = data.rfind(b'\x1b[')
    if (pos > 0 and data[pos:pos + 3] != b'\x1b[m' and
            data[pos:pos + 4] != b'\x1b[0m'):
        parts.append(b'\x1b[m')
    pos = data.rfind(b'\x1b(')
    if pos > 0 and data[pos:pos + 3] != b'\x1b(B':
        parts.append(b'\x1b(B')

    parts.append(b'\n...\n')
    parts.append(ending)
    return b''.join(parts), False


def save_logs(server: worker_db.WorkerDB, test_id: int, directory: pathlib.Path,
              *, save_state: bool,
              fuzz_spec: typing.Optional[testspec.FuzzSpec]) -> None:
    logs = list(list_logs(directory, save_state=save_state,
                          fuzz_spec=fuzz_spec))
    if not logs:
        return

    blob_client = blobs.get_client()

    def process_log(log: LogFile) -> LogFile:
        with open(log.path, 'rb') as rd:
            if not log.binary:
                log.stack_trace = find_backtrace_line(rd)
                rd.seek(0)
            log.data, is_full = read_short_log(log.size, rd, log.binary)
            if not is_full:
                rd.seek(0)
                log.url = blob_client.upload_test_log(test_id, log.name, rd)
            elif log.size:
                log.url = blob_client.get_test_log_href(test_id, log.name)

        return log

    max_workers = len(os.sched_getaffinity(0))
    with concurrent.futures.ThreadPoolExecutor(max_workers) as executor:
        executor.map(process_log, logs)

    server.save_short_logs(test_id, logs)


_LAST_COPIED_BUILD_ID: typing.Optional[int] = None
_COPIED_EXPENSIVE_DEPS: typing.List[str] = []


def scp_build(build_id: int, builder_ip: int, test: testspec.TestSpec,
              runner: utils.Runner) -> None:
    if test.skip_build:
        return

    builder_addr = utils.int_to_ip(builder_ip)

    def scp(src: str, dst: str) -> None:
        src = f'{builder_addr}:{utils.BUILDS_DIR}/{build_id}/{src}'
        path = utils.REPO_DIR / dst
        if not path.is_dir():
            runner.log_command(('mkdir', '-p', '--', dst), cwd=utils.REPO_DIR)
            utils.mkdirs(path)
        delay = 1 + random.random()
        for retry in range(3):
            if runner(('scp', '-oStrictHostKeyChecking=no',
                       '-oControlMaster=auto', '-oControlPath=/dev/shm/.ssh.%C',
                       '-oControlPersist=2', '-oBatchMode=yes', src, dst),
                      print_cmd=('scp', src, dst),
                      cwd=utils.REPO_DIR,
                      check=retry == 2) == 0:
                break
            time.sleep(delay)
            delay *= 2

    global _LAST_COPIED_BUILD_ID
    if _LAST_COPIED_BUILD_ID != build_id:
        _LAST_COPIED_BUILD_ID = None
        _COPIED_EXPENSIVE_DEPS[:] = ()
        repo_dir = utils.REPO_DIR
        utils.rmdirs(repo_dir / 'target')
        for path in (repo_dir / 'runtime/near-test-contracts/res').iterdir():
            if path.suffix == '.wasm':
                path.unlink()
        scp('target/*', f'target/{test.build_dir}')
        scp('near-test-contracts/*.wasm', 'runtime/near-test-contracts/res')
        _LAST_COPIED_BUILD_ID = build_id

    if test.category == 'expensive':
        test_name = test.args[1]
        if test_name not in _COPIED_EXPENSIVE_DEPS:
            scp(f'expensive/{test_name}-*', 'target/expensive')
            _COPIED_EXPENSIVE_DEPS.append(test_name)


@contextlib.contextmanager
def temp_dir() -> typing.Generator[pathlib.Path, None, None]:
    """A context manager setting a new temporary directory.

    Create a new temporary directory and sets it as tempfile.tempdir as well as
    TMPDIR, TEMP and TMP environment directories.  Once the context manager
    exits, values of all those variables are restored and the temporary
    directory deleted.
    """
    old_tempdir = tempfile.tempdir
    old_env = {
        var: os.environb.get(var) for var in (b'TMPDIR', b'TEMP', b'TMP')
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        tempfile.tempdir = tmpdir
        for var in old_env:
            os.environb[var] = os.fsencode(tmpdir)
        try:
            yield pathlib.Path(tmpdir)
        finally:
            tempfile.tempdir = old_tempdir
            for var, old_value in old_env.items():
                if old_value is None:
                    os.environb.pop(var, None)
                else:
                    os.environb[var] = old_value


def handle_test(server: worker_db.WorkerDB, test: worker_db.Test) -> None:
    print(test, file=sys.stderr)
    with temp_dir() as tmpdir:
        outdir = tmpdir / 'output'
        utils.mkdirs(outdir)
        with utils.Runner(outdir) as runner:
            __handle_test(server, outdir, runner, test)


def __handle_test(server: worker_db.WorkerDB, outdir: pathlib.Path,
                  runner: utils.Runner, test_row: worker_db.Test) -> None:
    if not utils.checkout(test_row.sha, runner):
        server.update_test_status('CHECKOUT FAILED', test_row.test_id)
        return

    utils.rmdirs(pathlib.Path.home() / '.rainbow',
                 utils.REPO_DIR / 'test-utils/runtime-tester/fuzz/artifacts')

    config_override: typing.Dict[str, typing.Any] = {}
    envb: _EnvB = typing.cast(_EnvB, os.environb)

    test = testspec.TestSpec.from_row(typing.cast(testspec.TestDBRow, test_row))

    if test.is_remote:
        config_override.update(local=False, preexist=True)
    if test.is_release:
        config_override.update(release=True, near_root='../target/release/')

    if config_override:
        fd, path = tempfile.mkstemp(prefix=b'config-', suffix=b'.json')
        with os.fdopen(fd, 'w') as wr:
            json.dump(config_override, wr)
        envb = dict(envb)
        envb[b'NEAR_PYTEST_CONFIG'] = path

    status = None
    try:
        scp_build(test_row.build_id, test_row.builder_ip, test, runner)
    except (OSError, subprocess.SubprocessError):
        runner.log_traceback()
        status = 'SCP FAILED'

    fuzz_spec = None
    if status is None:
        fuzz_spec = test.get_fuzz_spec()
        if fuzz_spec:
            cleanup_fuzz_state(fuzz_spec)

        if test.category in ('pytest', 'mocknet'):
            install_new_packages(runner)
        server.test_started(test_row.test_id)
        status = run_test(outdir, test, envb, runner)

    server.update_test_status(status, test_row.test_id)
    save_logs(server,
              test_row.test_id,
              outdir,
              save_state=status not in ('SCP FAILED', 'PASSED', 'IGNORED'),
              fuzz_spec=fuzz_spec)


def main() -> None:
    ipv4, ip_str = utils.get_ip()
    print(f'Starting worker @ {socket.gethostname()} ({ip_str} / {ipv4})',
          file=sys.stderr)

    with worker_db.WorkerDB(ipv4) as server:
        server.handle_restart()
        while True:
            try:
                test_row = server.get_pending_test()
                if test_row:
                    handle_test(server, test_row)
                else:
                    time.sleep(10)
            except KeyboardInterrupt:
                print('Got SIGINT; terminating', file=sys.stderr)
                break
            except Exception:
                traceback.print_exc()
                time.sleep(10)


if __name__ == '__main__':
    utils.setup_environ()
    main()
