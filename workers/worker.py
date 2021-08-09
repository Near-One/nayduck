import json
import os
from pathlib import Path, PurePath
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import traceback
import typing

import psutil

from . import blobs
from . import worker_db
from . import utils

DEFAULT_TIMEOUT = 180
BACKTRACE_PATTERN = 'stack backtrace:'
FAIL_PATTERNS = [BACKTRACE_PATTERN]
INTERESTING_PATTERNS = [BACKTRACE_PATTERN, 'LONG DELAY']


def get_sequential_test_cmd(cwd: Path, test: typing.Sequence[str],
                            build_type: str) -> typing.Sequence[str]:
    if len(test) >= 2 and test[0] in ('pytest', 'mocknet'):
        return ['python', 'tests/' + test[1]] + test[2:]
    if len(test) >= 4 and test[0] == 'expensive':
        path = cwd / 'target_expensive' / build_type / 'deps'
        for filename in os.listdir(path):
            if filename.startswith(test[2] + '-'):
                return (path / filename, test[3], '--exact', '--nocapture')
    raise ValueError('Invalid test command: ' + ' '.join(test))


_LAST_PIP_INSTALL: typing.Optional[str] = None


def install_new_packages(sha: str) -> None:
    """Makes sure all Python requirements for the pytests are satisfied.

    Args:
        sha: Hash of the commit we are on.  This is used to compare to hash the
            last time this function was called.  If they match, the function
            won’t bother calling pip.
    """
    global _LAST_PIP_INSTALL

    if _LAST_PIP_INSTALL != sha:
        subprocess.check_call(
            ('python', '-m', 'pip', 'install', '--user', '-q', '-r',
             utils.REPO_DIR / 'pytest/requirements.txt'))
        _LAST_PIP_INSTALL = sha


def kill_process_tree(pid: int) -> None:
    """Kills a process tree (including grandchildren).

    Sends SIGTERM to the process and all its descendant and waits for them to
    terminate.  If a process doesn't terminate within five seconds, sends
    SIGKILL to remaining stragglers.

    Args:
        pid: Process ID of the parent whose process tree to kill.
    """

    def send_to_all(procs: typing.List[psutil.Process], sig: int) -> None:
        for proc in procs:
            try:
                proc.send_signal(sig)
            except psutil.NoSuchProcess:
                pass

    proc = psutil.Process(pid)
    procs = proc.children(recursive=True) + [proc]
    print('Sending SIGTERM to {} process tree'.format(pid))
    send_to_all(procs, signal.SIGTERM)
    _, procs = psutil.wait_procs(procs, timeout=5)
    if procs:
        print('Sending SIGKILL to {} remaining processes'.format(len(procs)))
        send_to_all(procs, signal.SIGKILL)


def run_command_with_tmpdir(cmd: typing.Sequence[str],
                            stdout: typing.IO[typing.AnyStr],
                            stderr: typing.IO[typing.AnyStr], cwd: Path,
                            timeout: int) -> str:
    """Executes a command and cleans up its temporary files once it’s done.

    Executes a command with TMPDIR, TEMP and TMP environment variables set to
    a temporary directory which is cleared after the command terminates.  This
    should clean up all temporary file that the command might have created.

    Args:
        cmd: The command to execute.
        stdout: File to direct command’s standard output to.
        stderr: File to direct command’s standard error output to.
        cwd: Work directory to run the command in.
        timeout: Time in seconds to allow the test to run.  After that time
            passes, the test process will be killed and function will raise
            subprocess.Timeout exception.
    Raises:
        subprocess.Timeout: if process takes longer that timeout seconds to
        complete.
    """
    with tempfile.TemporaryDirectory() as tmpdir, \
         subprocess.Popen(cmd, stdout=stdout, stderr=stderr, cwd=cwd,
                          env=dict(os.environ,
                                   RUST_BACKTRACE='1',
                                   TMPDIR=tmpdir,
                                   TEMP=tmpdir,
                                   TMP=tmpdir)) as handle:
        try:
            return handle.wait(timeout)
        except subprocess.TimeoutExpired:
            kill_process_tree(handle.pid)
            raise


def analyse_test_outcome(test: typing.Sequence[str], ret: int,
                         stdout: typing.BinaryIO,
                         stderr: typing.BinaryIO) -> str:
    """Returns test's outcome based on exit code and test's output.

    Args:
        test: The test whose result is being analysed.
        ret: Test process exit code.
        stdout: Test's standard output opened as binary file.  The file
            descriptor must be seekable since it will be seeked to the beginning
            of the file if necessary.
        stderr: Test's standard error output opened as binary file.  The file
            descriptor must be seekable since it will be seeked to the beginning
            of the file if necessary.
    Returns:
        Tests outcome as one of: 'PASSED', 'FAILED', 'POSTPONE' or 'IGNORED'.
    """

    def get_last_line(rd: typing.BinaryIO) -> bytes:
        """Returns last non-empty line of a file or empty string."""
        rd.seek(0)
        last_line = b''
        for line in rd:
            line = line.strip()
            if line:
                last_line = line
        return last_line

    def analyze_rust_test():
        """Analyses outcome of an expensive or lib tests."""
        stdout.seek(0)
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
        stderr.seek(0)
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
        return analyze_rust_test()

    return 'PASSED'


def execute_test_command(dir_name: Path, test: typing.Sequence[str],
                         build_type: str, cwd: Path, timeout: int) -> str:
    """Executes a test command and returns test's outcome.

    Args:
        dir_name: Directory where to save 'stdout' and 'stderr' files.
        test: The test to execute.  Test command is constructed based on that
            list by calling get_sequential_test_cmd()
        build_type: A build type ('debug' or 'release') used in some
            circumstances to locate a built test binary inside of the taregt
            directory.
        cwd: Working directory to execute the test in.
        timeout: Time in seconds to allow the test to run.  After that time
            passes, the test process will be killed and function will return
            'TIMEOUT' outcome.
    Returns:
        Tests outcome as one of: 'PASSED', 'FAILED', 'POSTPONE', 'IGNORED' or
        'TIMEOUT'.
    """
    cmd = get_sequential_test_cmd(cwd, test, build_type)
    print('[RUNNING] {}\n+ {}'.format(
        ' '.join(test), ' '.join(shlex.quote(str(arg)) for arg in cmd)))
    with open(dir_name / 'stdout', 'wb+') as stdout, \
         open(dir_name / 'stderr', 'wb+') as stderr:
        try:
            ret = run_command_with_tmpdir(cmd, stdout, stderr, cwd, timeout)
        except subprocess.TimeoutExpired:
            return 'TIMEOUT'
        return analyse_test_outcome(test, ret, stdout, stderr)


def run_test(dir_name: Path, test, remote=False, build_type='debug') -> str:
    cwd = utils.REPO_DIR
    if test[0] in ('pytest', 'mocknet'):
        cwd = cwd / 'pytest'

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

        outcome = execute_test_command(dir_name, test, build_type, cwd, timeout)
        print('[{:<7}] {}'.format(outcome, ' '.join(test)))

        if outcome != 'POSTPONE' and test[0] == 'pytest':
            for node_dir in utils.list_test_node_dirs():
                shutil.copytree(node_dir, dir_name / PurePath(node_dir).name)
    except Exception as ex:
        print(ex)
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
    for line in rd:
        line = line.decode('utf-8', 'replace')
        for idx, pattern in enumerate(patterns):
            if not found[idx] and pattern in line:
                found[idx] = True
                count -= 1
                if not count:
                    break
    return [pattern for ok, pattern in zip(found, patterns) if ok]


class LogFile:

    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        self.path = path
        self.patterns = ''
        self.stack_trace = False
        self.size = path.stat().st_size
        self.data: typing.Optional[bytes] = None
        self.url: typing.Optional[str] = None


def list_logs(directory: Path) -> typing.Sequence[LogFile]:
    """Lists all log files to be saved."""
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
        elif entry in ('stderr', 'stdout', 'build_err', 'build_out'):
            files.append(LogFile(entry, directory / entry))

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


def read_short_log(size: int, rd: typing.BinaryIO) -> typing.Tuple[bytes, bool]:
    """Reads a short log from given file.

    A short log it at most _MAX_SHORT_LOG_SIZE bytes long.  If the file is
    longer than that, the function reads half of the maximum length from the
    beginning and half from the of the file and returns those two fragments
    concatenated with an three dots in between.

    Args:
        size: Actual size of the file.
        rd: The file opened for reading.
    Returns:
        A (short_log, is_full) tuple where first element is the short contents
        of the file and the second is whether the short content is the same is
        actually the full content.
    """
    if size < _MAX_SHORT_LOG_SIZE:
        data = rd.read()
        if len(data) < _MAX_SHORT_LOG_SIZE:  # Sanity check
            return data, True
        rd.seek(0)

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

    return data + b'\n...\n' + ending, False


def save_logs(server: worker_db.WorkerDB, test_id: int,
              directory: Path) -> None:
    logs = list_logs(directory)
    if not logs:
        return

    blob_client = blobs.get_client()

    for log in logs:
        with open(log.path, 'rb') as rd:
            patterns = find_patterns(rd, INTERESTING_PATTERNS)
            try:
                patterns.remove(BACKTRACE_PATTERN)
                log.stack_trace = True
            except ValueError:
                pass
            log.patterns = ','.join(sorted(patterns))

            rd.seek(0)
            log.data, is_full = read_short_log(log.size, rd)
            if is_full:
                log.url = blob_client.get_test_log_href(test_id, log.name)
            else:
                rd.seek(0)
                log.url = blob_client.upload_test_log(test_id, log.name, rd)

    server.save_short_logs(test_id, logs)


_LAST_COPIED_BUILD_ID = None
_COPIED_EXPENSIVE_DEPS = []


def scp_build(build_id, master_ip, test, build_type='debug'):
    global _LAST_COPIED_BUILD_ID, _COPIED_EXPENSIVE_DEPS

    if test[0] == 'mocknet':
        return

    master_auth = 'azureuser@' + utils.int_to_ip(master_ip)

    def scp(src: str, dst: str) -> None:
        src = f'{master_auth}:{utils.BUILDS_DIR}/{build_id}/{src}'
        dst = utils.REPO_DIR / dst
        utils.mkdirs(dst)
        cmd = ('scp', '-o', 'StrictHostKeyChecking=no', src, dst)
        subprocess.check_call(cmd)

    if _LAST_COPIED_BUILD_ID != build_id:
        _LAST_COPIED_BUILD_ID = None
        _COPIED_EXPENSIVE_DEPS = []
        utils.rmdirs(utils.REPO_DIR / 'target',
                     utils.REPO_DIR / 'target_expensive',
                     utils.REPO_DIR / 'runtime/near-test-contracts/res')
        scp('target/*', f'target/{build_type}')
        # For backwards compatibility create alias from near to neard.  We used
        # to build both binaries but they are really the same so instead master
        # no longer builds them and instead we just link the files.
        subprocess.check_call(
            ('ln', '-sf', '--', utils.REPO_DIR / 'target' / build_type / 'near',
             'neard'))
        scp('near-test-contracts/*', 'runtime/near-test-contracts/res')
        _LAST_COPIED_BUILD_ID = build_id

    if test[0] == 'expensive':
        test_name = test[2 + test[1].startswith('--')]
        if test_name not in _COPIED_EXPENSIVE_DEPS:
            scp(f'expensive/{test_name}-*',
                f'target_expensive/{build_type}/deps')
            _COPIED_EXPENSIVE_DEPS.append(test_name)


def handle_test(server: worker_db.WorkerDB,
                test: typing.Dict[str, typing.Any]) -> None:
    print(test)
    if not utils.checkout(test['sha']):
        server.update_test_status('CHECKOUT FAILED', test['test_id'])
        return
    outdir = utils.WORKDIR / 'output'
    utils.rmdirs(outdir, Path.home() / '.rainbow')
    outdir = outdir / str(test['test_id'])
    utils.mkdirs(outdir)

    tokens = test['name'].split()
    if '--features' in tokens:
        del tokens[tokens.index('--features'):]

    config_override = {}
    remote = '--remote' in tokens
    if remote:
        config_override.update(local=False, preexist=True)
        tokens.remove('--remote')
    release = '--release' in tokens
    if release:
        config_override.update(release=True, near_root='../target/release/')
        tokens.remove('--release')
    os.environ.pop('NEAR_PYTEST_CONFIG', None)
    if config_override:
        os.environ['NEAR_PYTEST_CONFIG'] = '/datadrive/nayduck/.remote'
        with open('/datadrive/nayduck/.remote', 'w') as wr:
            json.dump(config_override, wr)

    try:
        scp_build(test['build_id'], test['master_ip'], tokens,
                  'release' if release else 'debug')
    except (OSError, subprocess.SubprocessError):
        server.update_test_status('SCP FAILED', test['test_id'])
        raise

    if tokens[0] in ('pytest', 'mocknet'):
        install_new_packages(test['sha'])
    server.test_started(test['test_id'])
    code = run_test(outdir, tokens, remote, 'release' if release else 'debug')
    if code == 'POSTPONE':
        server.remark_test_pending(test['test_id'])
    else:
        server.update_test_status(code, test['test_id'])
        save_logs(server, test['test_id'], outdir)


def main():
    ipv4 = utils.get_ip()
    hostname = socket.gethostname()
    print('Starting worker at {} ({})'.format(hostname, utils.int_to_ip(ipv4)))

    mocknet = 'mocknet' in hostname
    with worker_db.WorkerDB() as server:
        server.handle_restart(ipv4)
        while True:
            try:
                test = server.get_pending_test(mocknet, ipv4)
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
