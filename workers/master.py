import os
from pathlib import Path
import socket
import stat
import time
import traceback
import typing

import psutil

from . import master_db
from . import utils


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


class BuildFailure(RuntimeError):
    pass


def build_target(spec: BuildSpec, runner: utils.Runner) -> None:
    """Builds and copies artefacts to the build output directory.

    Args:
        spec: The build specification as read from the database.  Based on it,
            the function determines which files were built (most notably whether
            expensive targets were compiled) and where they are located
            (e.g. whether they are in debug or release subdirectories).
        runner: A utils.Runner class used to execute `cp` commands.
    Raises:
        BuildFailure: if build fails
    """
    print('Building {}target'.format('expensive ' if spec.is_expensive else ''))

    def cargo(*cmd, add_features=True):
        cmd = ['cargo', *cmd]
        if add_features:
            cmd.extend(spec.features)
        if spec.is_release:
            cmd.append('--release')
        if not runner(cmd, cwd=utils.REPO_DIR):
            raise BuildFailure()

    def copy(src_dir, files: typing.Iterable[str], dst_dir: Path):
        utils.mkdirs(dst_dir)
        for filename in files:
            os.link(src_dir / filename, dst_dir / filename)

    def is_test_executable(path: Path) -> bool:
        if '.' in path.stem:
            return False
        try:
            attrs = path.stat()
        except OSError:
            return False
        return stat.S_ISREG(attrs.st_mode) and attrs.st_mode & 0o100

    utils.rmdirs(spec.build_dir)

    cargo('build', '-pneard', '--bin', 'neard', '--features', 'adversarial')
    cargo('build',
          '-pgenesis-populate',
          '-prestaked',
          '-pnear-test-contracts',
          add_features=False)

    copy(src_dir=utils.REPO_DIR / 'target' / spec.build_type,
         dst_dir=spec.build_dir / 'target',
         files=('neard', 'genesis-populate', 'restaked'))

    src_dir = utils.REPO_DIR / 'runtime' / 'near-test-contracts' / 'res'
    copy(src_dir=src_dir,
         dst_dir=spec.build_dir / 'near-test-contracts',
         files=os.listdir(src_dir))

    if not spec.is_expensive:
        return

    # Make sure there are no left overs from previous builds.  Don't delete
    # the entire directory so we can benefit from incremental building.
    src_dir = utils.REPO_DIR / 'target_expensive' / spec.build_type / 'deps'
    if src_dir.exists():
        for filename in os.listdir(src_dir):
            if '.' not in filename:
                (src_dir / filename).unlink()

    cargo('build', '--tests', '--target-dir', 'target_expensive',
          '--features=expensive_tests')

    copy(src_dir=src_dir,
         dst_dir=spec.build_dir / 'expensive',
         files=[
             name for name in os.listdir(src_dir)
             if is_test_executable(src_dir / name)
         ])


def build(spec: BuildSpec, runner: utils.Runner) -> bool:
    try:
        if not utils.checkout(spec.sha, runner=runner):
            return False
        build_target(spec, runner=runner)
        return True
    except BuildFailure:
        return False
    except Exception:
        traceback.print_exc()
        runner.write_err(traceback.format_exc())
        return False


def wait_for_free_space(server: master_db.MasterDB, ipv4: str) -> None:
    """Wait until there's at least 20% free space on /datadrive.

    If there's less than 50GB of free space on /datadrive file system, delete
    finished builds and wait until enough tests finish that enough free space
    becomes available.  50GB threshold has been chosen to be able to finish any
    build even in the worst circumstances.  Considering that even the largest
    build does not exceed 15GB this should be a safe bet.

    Args:
        server: Database to query for finished tests.
        ipv4: This builder's IP address (as an integer) used to retrieve list of
            builds we've performed from the database.
    """

    def enough_space() -> bool:
        return psutil.disk_usage(str(utils.WORKDIR)).free >= 50_000_000_000

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

    with master_db.MasterDB() as server:
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
