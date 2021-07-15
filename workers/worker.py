import os
import socket
import sys
import subprocess
import psutil
import shutil
from pathlib import Path, PurePath
import time
import typing
from db_worker import WorkerDB
from multiprocessing import Process
import json
from azure.storage.blob import BlobServiceClient, ContentSettings
from os.path import expanduser

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
        if test[0] == 'pytest' or test[0] == 'mocknet':
            return ["python", "tests/" + test[1]] + test[2:]
        deps_path = cwd / 'target_expensive' / build_type / 'deps'
        if test[0] == 'expensive':
            fls = os.listdir(deps_path)
            print(fls)
            for f in fls:
                if test[2].replace('-', '_') + '-' in f:
                    return [deps_path / f, test[3], '--exact', '--nocapture']
        elif test[0] == 'lib':
            fls = os.listdir(deps_path)
            print(fls)
            for f in fls:
                if test[1].replace('-', '_')  + '-' in f:
                    return [deps_path / f, test[2], '--exact', '--nocapture']
        assert False, test
    except:
        print(test)
        raise


def install_new_packages():
    """Makes sure all Python requirements for the pytests are satisfied."""
    requirements = WORKDIR / 'nearcore/pytest/requirements.txt'
    subprocess.check_call(
        ('python', '-m', 'pip', 'install' ,'--user', '-q', '-r', requirements))


def run_test(dir_name: Path, test, remote=False, build_type="debug"):
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

        
        cmd = get_sequential_test_cmd(cwd, test, build_type)
        print(cmd)

        if test[0] == 'pytest':
            utils.rmdirs(*utils.list_test_node_dirs())
            utils.mkdirs(Path.home() / '.near')

        print("[RUNNING] %s %s" % (' '.join(test), ' '.join(cmd)))

        stdout = open(os.path.join(dir_name, 'stdout'), 'w')
        stderr = open(os.path.join(dir_name, 'stderr'), 'w')

        env = os.environ.copy()
        env["RUST_BACKTRACE"] = "1"

        handle = subprocess.Popen(cmd, stdout=stdout, stderr=stderr,
                                  env=env, cwd=cwd)
        try:
            ret = handle.wait(timeout)
            if ret == 0:
                ignored = False
                if test[0] == 'expensive' or test[0] == 'lib':
                    with open(os.path.join(dir_name, 'stdout')) as f:
                        lines = f.readlines()
                        while len(lines) and lines[-1].strip() == '':
                            lines.pop()
                        if len(lines) == 0:
                            ignored = True
                        else:
                            if '0 passed' in lines[-1]:
                                ignored = True
                outcome = 'PASSED' if not ignored else 'IGNORED'
                if test[0] == 'expensive' or test[0] == 'lib':
                    with open(os.path.join(dir_name, 'stderr')) as f:
                        lines = f.readlines()
                        for line in lines:
                            if line.strip() in FAIL_PATTERNS:
                                outcome = 'FAILED'
                                break
            elif ret == 13:
                return 'POSTPONE'
            else:
                outcome = 'FAILED'
                with open(os.path.join(dir_name, 'stdout')) as f:
                    lines = f.readlines()
                    while len(lines) and lines[-1].strip() == '':
                        lines.pop()
                    if len(lines) == 0:
                        outcome = 'FAILED'
                    else:
                        if '1 passed; 0 failed;' in lines[-1]:
                            outcome = 'PASSED'
        except subprocess.TimeoutExpired as e:
            stdout.flush()
            stderr.flush()
            sys.stdout.flush()
            sys.stderr.flush()
            outcome = 'TIMEOUT'
            print("Sending SIGINT to %s" % handle.pid)
            for child in psutil.Process(handle.pid).children(recursive=True):
                child.terminate()
            handle.terminate()
            handle.communicate()

        if test[0] == 'pytest':
            for node_dir in utils.list_test_node_dirs():
                shutil.copytree(node_dir, os.path.join(dir_name, os.path.basename(node_dir)))

        print("[%7s] %s" % (outcome, ' '.join(test)))
        sys.stdout.flush()
    except Exception as ee:
        print(ee)
    return outcome


def find_patterns(filename: str,
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


def save_logs(server, test_id, dir_name):
    blob_size = 1024
    blob_service_client = BlobServiceClient.from_connection_string(AZURE)
    cnt_settings = ContentSettings(content_type="text/plain")
    files = []
    for filename in os.listdir(dir_name):
        if os.path.isdir(os.path.join(dir_name, filename)):
            fl_name = filename.split('_')[0]
            if os.path.exists(os.path.join(dir_name, filename, "remote.log")):
                files.append((fl_name + "_remote", os.path.join(dir_name, filename, "remote.log")))
            if os.path.exists(os.path.join(dir_name, filename, "companion.log")):
                files.append((fl_name + "_companion", os.path.join(dir_name, filename, "companion.log")))
            if os.path.exists(os.path.join(dir_name, filename, "stderr")):
                files.append((fl_name, os.path.join(dir_name, filename, "stderr")))
        elif filename in ["stderr", "stdout", "build_err", "build_out"]:
            files.append((filename, os.path.join(dir_name, filename)))
    home = expanduser("~")
    if os.path.isdir(os.path.join(home, ".rainbow", "logs")):
        for folder in os.listdir(os.path.join(home, ".rainbow", "logs")):
            for filename in os.listdir(os.path.join(home, ".rainbow", "logs", folder)):
                if "err" in filename:
                    files.append((f"{folder}_err", os.path.join(home, ".rainbow", "logs", folder, filename)))
                if "out" in filename:
                    files.append((f"{folder}_out", os.path.join(home, ".rainbow", "logs", folder, filename)))

    for fl_name, fl in files:
        file_size = os.path.getsize(fl)
        found_patterns = find_patterns(fl, INTERESTING_PATTERNS)
        try:
            found_patterns.remove(BACKTRACE_PATTERN)
            stack_trace = True
        except ValueError:
            stack_trace = False
        # REMOVE V2!
        blob_name = str(test_id) + "_v2_" + fl_name
        s3 = ""
        with open(fl, 'rb') as f:
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
        with open(fl, 'rb') as f:
            blob_client.upload_blob(f, content_settings=cnt_settings)
            s3 = blob_client.url
        print(s3) 

        server.save_short_logs(test_id, fl_name, file_size, data, s3, stack_trace, ",".join(found_patterns))
            

def scp_build(build_id, ip, test, build_type="debug"):
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


def checkout(sha: str) -> bool:
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
    repo_dir = (WORKDIR / 'nearcore')
    if repo_dir.is_dir():
        print('Checkout', sha)
        for directory in ('target', 'target_expensive', 'normal_target'):
            utils.rmdirs(repo_dir / directory)
        try:
            subprocess.check_call(('git', 'remote', 'update', '--prune'),
                                  cwd=repo_dir)
            subprocess.check_call(('git', 'checkout', sha), cwd=repo_dir)
            return True
        except subprocess.CalledProcessError:
            pass

    print('Clone', sha)
    utils.rmdirs(repo_dir)
    try:
        subprocess.check_call(
            ('git', 'clone', 'https://github.com/nearprotocol/nearcore'),
            cwd=WORKDIR)
        subprocess.check_call(('git', 'checkout', sha), cwd=repo_dir)
        return True
    except subprocess.CalledProcessError:
        return False


def keep_pulling():
    hostname = socket.gethostname()
    server = WorkerDB()
    server.handle_restart(hostname)
    home = expanduser("~")
    while True:
        time.sleep(5)
        try:
            server = WorkerDB()
            test = server.get_pending_test(hostname)
            if not test:
                continue
            
            test_name = test['name']
            print(test)
            if not checkout(test['sha']):
                server.update_test_status("CHECKOUT FAILED", test['test_id'])
                continue
            outdir = WORKDIR / 'output'
            shutil.rmtree(outdir, ignore_errors=True)
            shutil.rmtree(os.path.join(home, ".rainbow"), ignore_errors=True)
            shutil.rmtree(os.path.join(home, ".rainbow-bridge"), ignore_errors=True)
            outdir = outdir / str(test['test_id'])
            outdir.mkdir(parents=True, exist_ok=True)
            
            remote = False
            config_override = {}
            if "NEAR_PYTEST_CONFIG" in os.environ:
                 del os.environ["NEAR_PYTEST_CONFIG"]
            if '--remote' in test_name: 
                remote = True
                config_override['local'] = False
                config_override['preexist'] = True
                os.environ["NEAR_PYTEST_CONFIG"] = "/datadrive/nayduck/.remote"
                test_name = test_name.replace(' --remote', '')
            release = False
            if '--release' in test_name:
                release = True
                config_override['release'] = True
                config_override['near_root'] = '../target/release/'
                os.environ["NEAR_PYTEST_CONFIG"] = "/datadrive/nayduck/.remote"
                test_name = test_name.replace(' --release', '')
            if "NEAR_PYTEST_CONFIG" in os.environ:
                with open("/datadrive/nayduck/.remote", "w") as f:
                    json.dump(config_override, f)
            
            if '--features' in test_name:
                test_name = test_name[:test_name.find('--features')]

            if not ('mocknet' in test_name):
                try:
                    scp_build(test['build_id'], test['ip'], test_name.strip().split(' '), "release" if release else "debug")
                except (OSError, subprocess.SubprocessError) as ex:
                    print(ex)
                    server.update_test_status("SCP FAILED", test['test_id'])
                    continue
            
            tokens = test_name.split()
            if tokens and tokens[0] in ('pytest', 'mocknet'):
                install_new_packages()
            server.test_started(test['test_id'])
            code = run_test(outdir, tokens, remote, "release" if release else "debug")
            server = WorkerDB()
            if code == 'POSTPONE':
                server.remark_test_pending(test['test_id'])
                continue
            server.update_test_status(code, test['test_id'])
            save_logs(server, test['test_id'], outdir)
        except Exception as e:
            print(e)

if __name__ == "__main__":
    keep_pulling()        
