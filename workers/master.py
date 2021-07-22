import os
import socket
import sys
import subprocess
import psutil
import shutil
from pathlib import Path
import stat
import time
import traceback
import typing
from db_master import MasterDB
from azure.storage.blob import BlobServiceClient, ContentSettings

import utils


class BuildSpec(typing.NamedTuple):
    """Build specification as read from the database."""
    build_id: int
    build_dir: Path
    sha: str
    features: typing.Sequence[str]
    is_release: bool
    is_expensive: bool

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> 'BuildSpec':
        build_id = int(data['build_id'])
        return cls(
            build_id=build_id,
            build_dir=Path(str(build_id)),
            sha=str(data['sha']),
            features=tuple(str(data['features']).strip().split()),
            is_release=bool(data['is_release']),
            is_expensive=bool(data['expensive']))

    @property
    def build_type(self) -> str:
        return ('debug', 'release')[self.is_release]


def copy(spec: BuildSpec, runner: utils.Runner) -> bool:
    """Copies artefacts to the build output directory.

    Args:
        spec: The build specification as read from the database.  Based on it,
            the function determines which files were built (most notably whether
            expensive targets were compiled) and where they are located
            (e.g. whether they are in debug or release subdirectories).
        runner: A utils.Runner class used to execute `cp` commands.
    Returns:
        Whether copying of all files have succeeded.
    """
    print('Copying data')

    utils.rmdirs(spec.build_dir)

    def cp(*, dst: Path, srcs: typing.Sequence[Path], create_dir: bool=False):
        if create_dir:
            utils.mkdirs(dst)
        return runner(('cp', '-rl', '--', *srcs, dst))

    ok = True
    ok = ok and cp(dst=spec.build_dir / 'target' / spec.build_type,
                   srcs=[Path('nearcore') / 'target' / spec.build_type / exe
                         for exe in ('neard', 'near', 'genesis-populate',
                                     'restaked')],
                   create_dir=True)
    ok = ok and cp(dst=spec.build_dir / 'near-test-contracts',
                   srcs=[Path('nearcore') / 'runtime' / 'near-test-contracts' /
                         'res'])

    if not ok or not spec.is_expensive:
        return ok

    files = {}
    deps_dir = Path('nearcore/target_expensive') / spec.build_type / 'deps'
    for filename in os.listdir(deps_dir):
        if '.' in filename:
            continue
        path = deps_dir / filename
        try:
            attrs = path.stat()
        except OSError:
            continue
        if not stat.S_ISREG(attrs.st_mode) or attrs.st_mode & 0o100 == 0:
            continue
        ctime = attrs.st_ctime
        test_name = filename.split('-')[0]
        (prev_path, prev_ctime) = files.setdefault(test_name, (path, ctime))
        if prev_path != path and prev_ctime < ctime:
            files[test_name] = (path, ctime)

    return not files or cp(
        dst=spec.build_dir / 'target_expensive' / spec.build_type / 'deps',
        srcs=[path for path, _ in files.values()], create_dir=True)


def build_target(spec: BuildSpec, runner: utils.Runner) -> bool:
    print('Building {}target'.format('expensive ' if spec.is_expensive else ''))

    def cargo(*cmd, add_features=True):
        cmd = ['cargo', *cmd]
        if add_features:
            cmd.extend(spec.features)
        if spec.is_release:
            cmd.append('--release')
        return runner(cmd, cwd=Path('nearcore'))

    ok = True
    ok = ok and cargo('build', '-p', 'neard', '--features', 'adversarial')
    ok = ok and cargo('build', '-p', 'genesis-populate', '-p', 'restaked',
                      '-p', 'near-test-contracts', add_features=False)
    if spec.is_expensive:
        # It reads better when the command arguments are aligned so allow long
        # lines.  pylint: disable=line-too-long
        ok = ok and cargo('test', '--no-run', '--target-dir', 'target_expensive', '--workspace',                                                         '--features=expensive_tests')
        ok = ok and cargo('test', '--no-run', '--target-dir', 'target_expensive',                '-p', 'near-client', '-p', 'neard', '-p', 'near-chain', '--features=expensive_tests')
        ok = ok and cargo('test', '--no-run', '--target-dir', 'target_expensive',                '-p', 'near-chunks',                                    '--features=expensive_tests', add_features=False)
        ok = ok and cargo('test', '--no-run', '--target-dir', 'target_expensive', '--workspace', '-p', 'nearcore',                                       '--features=expensive_tests')

    return ok


def build(spec: BuildSpec, runner: utils.Runner) -> bool:
    try:
        return (utils.checkout(spec.sha, runner=runner) and
                build_target(spec, runner=runner) and
                copy(spec, runner=runner))
    except Exception:
        traceback.print_exc()
        runner.write_err(traceback.format_exc())
        return False


def wait_for_free_space(server: MasterDB, ip_address: str) -> None:
    """Wait until there's at least 20% free space on /datadrive.

    If there's less than 20% of free space on /datadrive file system, delete
    finished builds and wait until enough tests finish that enough free space
    becomes available.

    Args:
        server: Database to query for finished tests.
        ip_address: This builder's IP address used to retrieve list of builds
            we've performed from the database.
    """
    def enough_space() -> bool:
        return psutil.disk_usage('/datadrive').percent < 80.0

    def clean_finished() -> bool:
        server.with_builds_without_pending_tests(
            ip_address, lambda ids: utils.rmdirs(
                *[Path(str(bid)) for bid in ids]))
        return enough_space()

    if enough_space() or clean_finished():
        return

    utils.rmdirs(Path('nearcore/target'), Path('nearcore/target_expensive'))
    if enough_space():
        return

    print('Not enough free space; '
          'waiting for tests to finish to clean up more builds')
    while True:
        time.sleep(5)
        if clean_finished():
            break
    print('Got enough free space; continuing')


def get_ip() -> str:
    """Returns private IPv4 address of the current host.

    Returns:
        A string with the hosts private IP address.
    Raises:
        SystemExit: if no private IP address could be found for the host.
    """
    for iface in psutil.net_if_addrs().values():
        for addr in iface:
            if addr.family != socket.AF_INET:
                continue
            ip_addr = addr.address
            octets = [int(octet) for octet in ip_addr.split('.')]
            if len(octets) != 4:  # Sanity check
                continue
            # Check if it's a private address.  We don't want to return any kind
            # of public addresses or localhost.
            if (octets[0] == 10 or
                (octets[0] == 172 and 16 <= octets[1] <= 31) or
                (octets[0] == 192 and octets[1] == 168)):
                return ip_addr
    sys.exit('Unable to determine private IP address')


def keep_pulling():
    ip_address = get_ip()
    print('Starting master at {}'.format(ip_address))

    server = MasterDB()
    server.handle_restart(ip_address)
  
    while True:
        time.sleep(5)
        wait_for_free_space(server, ip_address)
        try:
            new_build = server.get_new_build(ip_address)
            if not new_build:
                continue

            print(new_build)
            spec = BuildSpec.from_dict(new_build)
            runner = utils.Runner(capture=True)
            success = build(spec, runner)
            print('Build {}; updating database'.format(
                'succeeded' if success else 'failed'))
            server.update_build_status(spec.build_id, success,
                                       out=runner.stdout, err=runner.stderr)
            print('Done; starting another pool iteration')
        except Exception as e:
            print(e)

if __name__ == "__main__":
    keep_pulling()
        
