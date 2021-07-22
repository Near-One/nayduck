import os
import signal
import socket
import subprocess
import psutil
import shutil
import shlex
from pathlib import Path, PurePath
import tempfile
import time
import traceback
import typing
from db_worker import WorkerDB
from multiprocessing import Process
import json
from azure.storage.blob import BlobServiceClient, ContentSettings

import utils


DEFAULT_TIMEOUT = 180
BACKTRACE_PATTERN = 'stack backtrace:'
FAIL_PATTERNS = [BACKTRACE_PATTERN]
INTERESTING_PATTERNS = [BACKTRACE_PATTERN, 'LONG DELAY']
AZURE = os.getenv('AZURE_STORAGE_CONNECTION_STRING')

WORKDIR = Path('/datadrive')

def get_sequential_test_cmd(cwd: Path,
                            test: typing.Sequence[str],
                            build_type: str) -> typing.Sequence[str]:
    try:
        if test[0] in ('pytest', 'mocknet'):
            return ['python', 'tests/' + test[1]] + test[2:]
        if test[0] in ('expensive', 'lib'):
            path = cwd / 'target_expensive' / build_type / 'deps'
            idx = 1 + (test[0] == 'expensive')
            name_prefix = test[idx].replace('-', '_') + '-'
            files = os.listdir(path)
            for filename in files:
                if filename.startswith(name_prefix):
                    return [path / filename, test[idx],
                            '--exact', '--nocapture']
    except Exception:
        print(test)
        raise
    raise ValueError('Invalid test command: ' + ' '.join(test))


def install_new_packages():
    """Makes sure all Python requirements for the pytests are satisfied."""
    requirements = WORKDIR / 'nearcore/pytest/requirements.txt'
    subprocess.check_call(
        ('python', '-m', 'pip', 'install' ,'--user', '-q', '-r', requirements))


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
                            stderr: typing.IO[typing.AnyStr],
                            cwd: Path,
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


def analyse_test_outcome(test: typing.Sequence[str],
                         ret: int,
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
    if ret == 13:
        return 'POSTPONE'

    def get_last_line(rd: typing.BinaryIO) -> str:
        """Returns last non-empty line of a file or empty string if"""
        rd.seek(0)
        last_line = b''
        for line in rd:
            line = line.strip()
            if line:
                last_line = line
        return last_line

    if ret != 0:
        if b'1 passed; 0 failed;' in get_last_line(stdout):
            return 'PASSED'
        return 'FAILED'

    if test[0] == 'expensive' or test[0] == 'lib':
        stderr.seek(0)
        for line in stderr:
            if line.strip().decode('utf-8', 'replace') in FAIL_PATTERNS:
                return 'FAILED'
        if b'0 passed' in get_last_line(stdout):
            return 'IGNORED'

    return 'PASSED'


def execute_test_command(dir_name: Path,
                         test: typing.Sequence[str],
                         build_type: str,
                         cwd: Path,
                         timeout: int) -> str:
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
    cwd = WORKDIR / 'nearcore'
    if test[0] in ('pytest', 'mocknet'):
        cwd = cwd / 'pytest'

    outcome = "FAILED"
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
        print("[%7s] %s" % (outcome, ' '.join(test)))

        if outcome != 'POSTPONE' and test[0] == 'pytest':
            for node_dir in utils.list_test_node_dirs():
                shutil.copytree(node_dir,
                                dir_name / PurePath(node_dir).name)
    except Exception as ee:
        print(ee)
    return outcome


def find_patterns(filename: Path,
                  patterns: typing.Sequence[str]) -> typing.List[str]:
    """Searches for patterns in given file; returns list of found patterns.

    Args:
        filename: Path to the file to read.
        patterns: List of patterns to look for.  Patterns are matched as fixed
            strings (no regex or globing) and must not span multiple lines since
            search is done line-by-line.

    Returns:
        A list of patterns which were found in the file.
    """
    found = [False] * len(patterns)
    count = len(found)
    with open(filename) as rd:
        for line in rd:
            for idx, pattern in enumerate(patterns):
                if not found[idx] and pattern in line:
                    found[idx] = True
                    count -= 1
                    if not count:
                        break
    return [pattern for ok, pattern in zip(found, patterns) if ok]


def save_logs(server, test_id, directory: Path):
    blob_size = 1024
    blob_service_client = BlobServiceClient.from_connection_string(AZURE)
    cnt_settings = ContentSettings(content_type="text/plain")

    files = []
    for entry in os.listdir(directory):
        entry_path = directory / entry
        if entry_path.is_dir():
            filename = entry.split('_')[0]
            for filename, suffix in (
                    ('remote.log', '_remote'),
                    ('companion.log', '_companion'),
                    ('stderr', ''),
            ):
                if (entry_path / filename).exists():
                    files.append((filename + suffix, entry_path / filename))
        elif entry in ('stderr', 'stdout', 'build_err', 'build_out'):
            files.append((entry, directory / entry))

    rainbow_logs = Path.home() / '.rainbow' / 'logs'
    if rainbow_logs.is_dir():
        for folder in os.listdir(rainbow_logs):
            for entry in os.listdir(rainbow_logs / folder):
                for suffix in ('err', 'out'):
                    if suffix in entry:
                        path = rainbow_logs / folder / entry
                        files.append((f'{folder}_{suffix}', path))

    for filename, path in files:
        file_size = path.stat().st_size
        found_patterns = find_patterns(path, INTERESTING_PATTERNS)
        try:
            found_patterns.remove(BACKTRACE_PATTERN)
            stack_trace = True
        except ValueError:
            stack_trace = False
        # REMOVE V2!
        blob_name = str(test_id) + "_v2_" + filename
        s3 = ""
        with open(path, 'rb') as f:
            f.seek(0)
            beginning = f.read(blob_size * 5 * 2).decode()
            if len(beginning) < blob_size * 5 * 2:
                data = beginning
            else:
                data = beginning[0:blob_size * 5]
                data += '\n...\n'
                f.seek(-blob_size * 5, 2)
                data += f.read().decode()
        blob_client = blob_service_client.get_blob_client(container="logs", blob=blob_name)    
        with open(path, 'rb') as f:
            blob_client.upload_blob(f, content_settings=cnt_settings)
            s3 = blob_client.url
        print(s3) 

        server.save_short_logs(test_id, filename, file_size, data, s3, stack_trace, ",".join(found_patterns))
            

def scp_build(build_id, ip, test, build_type="debug"):
    if test[0] == 'mocknet':
        return

    def scp(src: str, dst: str) -> None:
        src = f'azureuser@{ip}:/datadrive/nayduck/workers/{build_id}/{src}'
        dst = WORKDIR / 'nearcore' / dst
        utils.mkdirs(dst)
        cmd = ('scp', '-o', 'StrictHostKeyChecking=no', src, dst)
        subprocess.check_call(cmd)

    scp(f'target/{build_type}/*', f'target/{build_type}')
    scp('near-test-contracts/*', 'runtime/near-test-contracts/res')

    if test[0] in ('expensive', 'lib'):
        idx = 1 + (test[0] == 'expensive') + test[1].startswith('--')
        test_name = test[idx].replace('-', '_')
        scp(f'target_expensive/{build_type}/deps/{test_name}-*',
            f'target_expensive/{build_type}/deps')


def handle_test(server: WorkerDB, test: typing.Dict[str, typing.Any]) -> None:
    print(test)
    if not utils.checkout(test['sha'], cwd=WORKDIR):
        server.update_test_status('CHECKOUT FAILED', test['test_id'])
        return
    outdir = WORKDIR / 'output'
    utils.rmdirs(outdir,
                 Path.home() / '.rainbow',
                 Path.home() / '.rainbow-bridge')
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
        with open('/datadrive/nayduck/.remote', 'w') as f:
            json.dump(config_override, f)

    try:
        scp_build(test['build_id'], test['ip'], tokens,
                  'release' if release else 'debug')
    except (OSError, subprocess.SubprocessError) as ex:
        server.update_test_status('SCP FAILED', test['test_id'])
        raise

    if tokens[0] in ('pytest', 'mocknet'):
        install_new_packages()
    server.test_started(test['test_id'])
    code = run_test(outdir, tokens, remote, 'release' if release else 'debug')
    if code == 'POSTPONE':
        server.remark_test_pending(test['test_id'])
    else:
        server.update_test_status(code, test['test_id'])
        save_logs(server, test['test_id'], outdir)


def main():
    hostname = socket.gethostname()
    print('Starting worker at {}'.format(hostname))
    server = WorkerDB()
    server.handle_restart(hostname)
    while True:
        try:
            test = server.get_pending_test(hostname)
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


if __name__ == "__main__":
    main()
