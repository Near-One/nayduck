import concurrent.futures
import contextlib
import json
import os
from pathlib import Path, PurePath
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import typing

from . import blobs
from . import worker_db
from . import utils

DEFAULT_TIMEOUT = 180
BACKTRACE_PATTERN = 'stack backtrace:'
FAIL_PATTERNS = [BACKTRACE_PATTERN]
INTERESTING_PATTERNS = [BACKTRACE_PATTERN, 'LONG DELAY']

_Test = typing.List[str]
_Cmd = typing.Sequence[typing.Union[str, Path]]
_EnvB = typing.MutableMapping[bytes, bytes]


def get_test_command(test: _Test) -> typing.Tuple[Path, _Cmd]:
    """Returns working directory and command to execute for given test.

    Assumes that the repository from which the test should be run is located in
    utils.REPO_DIR directory.

    Args:
        test: Test to return the command for.
    Returns:
        A (cwd, cmd) tuple where first element is working directory in which to
        execute the command given by the second element.
    Raises:
        ValueError: If test specification is malformed.
    """
    if len(test) >= 2 and test[0] in ('pytest', 'mocknet'):
        cmd = [sys.executable, 'tests/' + test[1]] + test[2:]
        return utils.REPO_DIR / 'pytest', cmd
    if len(test) >= 4 and test[0] == 'expensive':
        for name in os.listdir(utils.REPO_DIR / 'target/expensive'):
            if name.startswith(test[2] + '-'):
                name = f'target/expensive/{name}'
                return utils.REPO_DIR, (name, test[3], '--exact', '--nocapture')
    raise ValueError('Invalid test command: ' + ' '.join(test))


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


def analyse_test_outcome(test: _Test, ret: int, stdout: typing.BinaryIO,
                         stderr: typing.BinaryIO) -> str:
    """Returns test's outcome based on exit code and test's output.

    Args:
        test: The test whose result is being analysed.
        ret: Test process exit code.
        stdout: Test's standard output opened as binary file.
        stderr: Test's standard error output opened as binary file.
    Returns:
        Tests outcome as one of: 'PASSED', 'FAILED', 'POSTPONE' or 'IGNORED'.
    """

    def get_last_line(rd: typing.BinaryIO) -> bytes:
        """Returns last non-empty line of a file or empty string."""
        last_line = b''
        for line in rd:
            line = line.strip()
            if line:
                last_line = line
        return last_line

    def analyse_rust_test() -> str:
        """Analyses outcome of an expensive or lib tests."""
        for line in stdout:
            line = line.strip()
            if not line:
                continue
            if line.decode('utf-8', 'replace') == 'running 0 tests':
                # If user specified incorrect test name the test executable will
                # run no tests since the filter we provide won't match anything.
                # Report that as a failure rather than ignored test.
                return 'FAILED'
            break
        for line in stderr:
            if line.strip().decode('utf-8', 'replace') in FAIL_PATTERNS:
                return 'FAILED'
        if b'0 passed' in get_last_line(stdout):
            return 'IGNORED'
        return 'PASSED'

    if ret == 13:
        return 'POSTPONE'

    if ret != 0:
        if b'1 passed; 0 failed;' in get_last_line(stdout):
            return 'PASSED'
        return 'FAILED'

    if test[0] == 'expensive':
        return analyse_rust_test()

    return 'PASSED'


def execute_test_command(test: _Test, envb: _EnvB, timeout: int,
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
        Tests outcome as one of: 'PASSED', 'FAILED', 'POSTPONE', 'IGNORED' or
        'TIMEOUT'.
    """
    print('[RUNNING] ' + ' '.join(test), file=sys.stderr)
    stdout_start = runner.stdout.tell()
    stderr_start = runner.stderr.tell()
    envb[b'RUST_BACKTRACE'] = b'1'
    try:
        cwd, cmd = get_test_command(test)
        ret = runner(cmd, cwd=cwd, timeout=timeout, env=envb)
    except subprocess.TimeoutExpired:
        return 'TIMEOUT'
    try:
        runner.stdout.seek(stdout_start)
        runner.stderr.seek(stderr_start)
        return analyse_test_outcome(test, ret, runner.stdout, runner.stderr)
    finally:
        runner.stdout.seek(0, 2)
        runner.stderr.seek(0, 2)


def run_test(outdir: Path, test: _Test, remote: bool, envb: _EnvB,
             runner: utils.Runner) -> str:
    outcome = 'FAILED'
    try:
        timeout = DEFAULT_TIMEOUT
        if len(test) > 1 and test[1].startswith('--timeout='):
            timeout = int(test[1][10:])
            test = [test[0]] + test[2:]
        if remote:
            timeout += 60 * 15

        if test[0] == 'pytest':
            utils.rmdirs(*utils.list_test_node_dirs())
            utils.mkdirs(Path.home() / '.near')

        outcome = execute_test_command(test, envb, timeout, runner)
        print('[{:<7}] {}'.format(outcome, ' '.join(test)))

        if outcome != 'POSTPONE' and test[0] == 'pytest':
            for node_dir in utils.list_test_node_dirs():
                shutil.copytree(node_dir, outdir / PurePath(node_dir).name)
    except Exception:
        runner.log_traceback()
    return outcome


def find_patterns(rd: typing.BinaryIO,
                  patterns: typing.Collection[str]) -> typing.List[str]:
    """Searches for patterns in given file; returns list of found patterns.

    Args:
        rd: The file opened for reading.
        patterns: List of patterns to look for.  Patterns are matched as fixed
            strings (no regex or globing) and must not span multiple lines since
            search is done line-by-line.

    Returns:
        A list of patterns which were found in the file.
    """
    found = [False] * len(patterns)
    count = len(found)
    for raw_line in rd:
        line = raw_line.decode('utf-8', 'replace')
        for idx, pattern in enumerate(patterns):
            if not found[idx] and pattern in line:
                found[idx] = True
                count -= 1
                if not count:
                    break
    return [pattern for ok, pattern in zip(found, patterns) if ok]


class LogFile:  # pylint: disable=too-many-instance-attributes

    def __init__(self, name: str, path: Path, binary: bool = False) -> None:
        self.name = name
        self.path = path
        self.patterns = ''
        self.stack_trace = False
        self.size = path.stat().st_size
        self.data: typing.Optional[bytes] = None
        self.url: typing.Optional[str] = None
        self.binary = binary


def generate_artifacts_file(directory: Path, name: str) -> None:
    """Generates a tar archive with fuzz crash artefacts if any are availabe."""
    artdir = utils.REPO_DIR / 'test-utils/runtime-tester/fuzz/artifacts'
    subdir = 'runtime-fuzzer'
    if not (artdir / subdir).is_dir():
        return

    files = sorted(f'{subdir}/{entry}' for entry in os.listdir(artdir / subdir)
                   if entry.startswith('crash-'))
    if not files:
        return

    outfile = directory / name
    cmd: typing.Sequence[typing.Union[str, Path]] = ('tar', 'cf', outfile, '-I',
                                                     'gzip -9', '--', *files)
    print('+ ' + ' '.join(str(arg) for arg in cmd), file=sys.stderr)
    returncode = subprocess.run(cmd, check=False, cwd=artdir).returncode
    if returncode != 0 and outfile.exists():
        outfile.unlink()


def list_logs(directory: Path) -> typing.Sequence[LogFile]:
    """Lists all log files to be saved."""
    crashes_file_name = 'crashes.tar.gz'
    generate_artifacts_file(directory, crashes_file_name)

    files = []
    for entry in os.listdir(directory):
        entry_path = directory / entry
        if entry_path.is_dir():
            base = entry.split('_')[0]
            for filename, suffix in (
                ('remote.log', '_remote'),
                ('companion.log', '_companion'),
                ('stderr', ''),
            ):
                if (entry_path / filename).exists():
                    files.append(LogFile(base + suffix, entry_path / filename))
        elif entry in ('stderr', 'stdout', crashes_file_name):
            files.append(
                LogFile(entry,
                        directory / entry,
                        binary=entry == 'crashes.tar.gz'))

    rainbow_logs = Path.home() / '.rainbow' / 'logs'
    if rainbow_logs.is_dir():
        for folder in os.listdir(rainbow_logs):
            for entry in os.listdir(rainbow_logs / folder):
                for suffix in ('err', 'out'):
                    if suffix in entry:
                        path = rainbow_logs / folder / entry
                        files.append(LogFile(f'{folder}_{suffix}', path))

    return files


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


def save_logs(server: worker_db.WorkerDB, test_id: int,
              directory: Path) -> None:
    logs = list_logs(directory)
    if not logs:
        return

    blob_client = blobs.get_client()

    def process_log(log: LogFile) -> LogFile:
        with open(log.path, 'rb') as rd:
            if not log.binary:
                patterns = find_patterns(rd, INTERESTING_PATTERNS)
                try:
                    patterns.remove(BACKTRACE_PATTERN)
                    log.stack_trace = True
                except ValueError:
                    pass
                log.patterns = ','.join(sorted(patterns))
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


def scp_build(build_id: int, master_ip: int, test: _Test, build_type: str,
              runner: utils.Runner) -> None:
    global _LAST_COPIED_BUILD_ID

    if test[0] == 'mocknet':
        return

    master_auth = utils.int_to_ip(master_ip)

    def scp(src: str, dst: str) -> None:
        src = f'{master_auth}:{utils.BUILDS_DIR}/{build_id}/{src}'
        path = utils.REPO_DIR / dst
        if not path.is_dir():
            runner.log_command(('mkdir', '-p', '--', dst), cwd=utils.REPO_DIR)
            utils.mkdirs(path)
        runner(('scp', src, dst), cwd=utils.REPO_DIR, check=True)

    if _LAST_COPIED_BUILD_ID != build_id:
        _LAST_COPIED_BUILD_ID = None
        _COPIED_EXPENSIVE_DEPS[:] = ()
        repo_dir = utils.REPO_DIR
        utils.rmdirs(repo_dir / 'target')
        for path in (repo_dir / 'runtime/near-test-contracts/res').iterdir():
            if path.suffix == '.wasm':
                path.unlink()
        scp('target/*', f'target/{build_type}')
        scp('near-test-contracts/*.wasm', 'runtime/near-test-contracts/res')
        _LAST_COPIED_BUILD_ID = build_id

    if test[0] == 'expensive':
        test_name = test[2 + test[1].startswith('--')]
        if test_name not in _COPIED_EXPENSIVE_DEPS:
            scp(f'expensive/{test_name}-*', 'target/expensive')
            _COPIED_EXPENSIVE_DEPS.append(test_name)


@contextlib.contextmanager
def temp_dir() -> typing.Generator[Path, None, None]:
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
            yield Path(tmpdir)
        finally:
            tempfile.tempdir = old_tempdir
            for var, old_value in old_env.items():
                if old_value is None:
                    os.environb.pop(var, None)
                else:
                    os.environb[var] = old_value


def handle_test(server: worker_db.WorkerDB, test: worker_db.Test) -> None:
    print(test)
    with temp_dir() as tmpdir:
        outdir = tmpdir / 'output'
        utils.mkdirs(outdir)
        with utils.Runner(outdir) as runner:
            __handle_test(server, outdir, runner, test)


def __handle_test(server: worker_db.WorkerDB, outdir: Path,
                  runner: utils.Runner, test: worker_db.Test) -> None:
    if not utils.checkout(test.sha, runner):
        server.update_test_status('CHECKOUT FAILED', test.test_id)
        return

    utils.rmdirs(Path.home() / '.rainbow',
                 utils.REPO_DIR / 'test-utils/runtime-tester/fuzz/artifacts')

    config_override: typing.Dict[str, typing.Any] = {}
    envb: _EnvB = typing.cast(_EnvB, os.environb)

    tokens = test.name.split()
    if '--features' in tokens:
        del tokens[tokens.index('--features'):]

    remote = '--remote' in tokens
    if remote:
        config_override.update(local=False, preexist=True)
        tokens.remove('--remote')
    release = '--release' in tokens
    if release:
        config_override.update(release=True, near_root='../target/release/')
        tokens.remove('--release')

    if config_override:
        fd, path = tempfile.mkstemp(prefix=b'config-', suffix=b'.json')
        with os.fdopen(fd, 'w') as wr:
            json.dump(config_override, wr)
        envb = dict(envb)
        envb[b'NEAR_PYTEST_CONFIG'] = path

    status = None
    try:
        scp_build(test.build_id, test.master_ip, tokens,
                  'release' if release else 'debug', runner)
    except (OSError, subprocess.SubprocessError):
        runner.log_traceback()
        status = 'SCP FAILED'

    if status is None:
        if tokens[0] in ('pytest', 'mocknet'):
            install_new_packages(runner)
        server.test_started(test.test_id)
        status = run_test(outdir, tokens, remote, envb, runner)

    if status == 'POSTPONE':
        server.remark_test_pending(test.test_id)
    else:
        server.update_test_status(status, test.test_id)
        save_logs(server, test.test_id, outdir)


def main() -> None:
    ipv4 = utils.get_ip()
    hostname = socket.gethostname()
    print('Starting worker at {} ({})'.format(hostname, utils.int_to_ip(ipv4)))

    mocknet = 'mocknet' in hostname
    with worker_db.WorkerDB(ipv4) as server:
        server.handle_restart()
        while True:
            try:
                test = server.get_pending_test(mocknet)
                if test:
                    handle_test(server, test)
                else:
                    time.sleep(10)
            except KeyboardInterrupt:
                print('Got SIGINT; terminating')
                break
            except Exception:
                traceback.print_exc()
                time.sleep(10)


if __name__ == '__main__':
    utils.setup_environ()
    main()
