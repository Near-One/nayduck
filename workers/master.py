import os
from pathlib import Path
import socket
import stat
import time
import traceback
import typing

import psutil

from db_master import MasterDB
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
        return cls(build_id=build_id,
                   build_dir=utils.BUILDS_DIR / str(build_id),
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

    def cp(*, dst: Path, srcs: typing.Sequence[Path], create_dir: bool = False):  # pylint: disable=invalid-name
        if create_dir:
            utils.mkdirs(dst)
        return runner(('cp', '-rl', '--', *srcs, dst))

    utils.rmdirs(spec.build_dir)

    ok = True
    ok = ok and cp(dst=spec.build_dir / 'target',
                   create_dir=True,
                   srcs=[
                       utils.REPO_DIR / 'target' / spec.build_type / exe
                       for exe in ('neard', 'genesis-populate', 'restaked')
                   ])
    ok = ok and cp(
        dst=spec.build_dir / 'near-test-contracts',
        srcs=[utils.REPO_DIR / 'runtime' / 'near-test-contracts' / 'res'])

    if not ok or not spec.is_expensive:
        return ok

    files = {}
    deps_dir = utils.REPO_DIR / 'target_expensive' / spec.build_type / 'deps'
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

    return not files or cp(dst=spec.build_dir / 'expensive',
                           srcs=[path for path, _ in files.values()],
                           create_dir=True)


def build_target(spec: BuildSpec, runner: utils.Runner) -> bool:
    print('Building {}target'.format('expensive ' if spec.is_expensive else ''))

    def cargo(*cmd, add_features=True):
        cmd = ['cargo', *cmd]
        if add_features:
            cmd.extend(spec.features)
        if spec.is_release:
            cmd.append('--release')
        return runner(cmd, cwd=utils.REPO_DIR)

    ok = True
    ok = ok and cargo('build', '-p', 'neard', '--bin', 'neard', '--features',
                      'adversarial')
    ok = ok and cargo('build',
                      '-p',
                      'genesis-populate',
                      '-p',
                      'restaked',
                      '-p',
                      'near-test-contracts',
                      add_features=False)
    if spec.is_expensive:
        # It reads better when the command arguments are aligned so allow long
        # lines.  pylint: disable=line-too-long
        # yapf: disable
        ok = ok and cargo('test', '--no-run', '--target-dir', 'target_expensive', '--workspace',                                                         '--features=expensive_tests')
        ok = ok and cargo('test', '--no-run', '--target-dir', 'target_expensive',                '-p', 'near-client', '-p', 'neard', '-p', 'near-chain', '--features=expensive_tests')
        ok = ok and cargo('test', '--no-run', '--target-dir', 'target_expensive',                '-p', 'near-chunks',                                    '--features=expensive_tests', add_features=False)
        ok = ok and cargo('test', '--no-run', '--target-dir', 'target_expensive', '--workspace', '-p', 'nearcore',                                       '--features=expensive_tests')
        # yapf: enable

    return ok


def build(spec: BuildSpec, runner: utils.Runner) -> bool:
    try:
        return (utils.checkout(spec.sha, runner=runner) and
                build_target(spec, runner=runner) and copy(spec, runner=runner))
    except Exception:
        traceback.print_exc()
        runner.write_err(traceback.format_exc())
        return False


def wait_for_free_space(server: MasterDB, ipv4: str) -> None:
    """Wait until there's at least 20% free space on /datadrive.

    If there's less than 20% of free space on /datadrive file system, delete
    finished builds and wait until enough tests finish that enough free space
    becomes available.

    Args:
        server: Database to query for finished tests.
        ipv4: This builder's IP address (as an integer) used to retrieve list of
            builds we've performed from the database.
    """

    def enough_space() -> bool:
        return psutil.disk_usage(str(utils.WORKDIR)).percent < 80.0

    def clean_finished() -> bool:
        server.with_builds_without_pending_tests(
            ipv4, lambda ids: utils.rmdirs(*[Path(str(bid)) for bid in ids]))
        return enough_space()

    if enough_space() or clean_finished():
        return

    utils.rmdirs(utils.REPO_DIR / 'target', utils.REPO_DIR / 'target_expensive')
    if enough_space():
        return

    print('Not enough free space; '
          'waiting for tests to finish to clean up more builds')
    while True:
        time.sleep(5)
        if clean_finished():
            break
    print('Got enough free space; continuing')


def keep_pulling():
    ipv4 = utils.get_ip()
    print('Starting master at {} ({})'.format(socket.gethostname(),
                                              utils.int_to_ip(ipv4)))

    with MasterDB() as server:
        server.handle_restart(ipv4)

        while True:
            time.sleep(5)
            wait_for_free_space(server, ipv4)
            try:
                new_build = server.get_new_build(ipv4)
                if not new_build:
                    continue

                print(new_build)
                spec = BuildSpec.from_dict(new_build)
                runner = utils.Runner(capture=True)
                success = build(spec, runner)
                print('Build {}; updating database'.format(
                    'succeeded' if success else 'failed'))
                server.update_build_status(spec.build_id,
                                           success,
                                           out=runner.stdout,
                                           err=runner.stderr)
                print('Done; starting another pool iteration')
            except Exception:
                traceback.print_exc()


if __name__ == '__main__':
    utils.setup_environ()
    keep_pulling()
