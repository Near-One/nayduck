import os
from pathlib import Path
import socket
import stat
import time
import traceback
import sys
import typing

import psutil

from . import builder_db
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
    def from_row(cls, data: builder_db.Build) -> 'BuildSpec':
        build_id = int(data.build_id)
        return cls(build_id=build_id,
                   build_dir=utils.BUILDS_DIR / str(build_id),
                   sha=str(data.sha),
                   features=tuple(data.features.split()),
                   is_release=bool(data.is_release),
                   is_expensive=bool(data.expensive))

    @property
    def build_type(self) -> str:
        return ('debug', 'release')[self.is_release]

    def __str__(self) -> str:
        ret = f'Build #{self.build_id}: sha={self.sha}'
        if self.is_release:
            ret += ' --relaese'
        if self.features:
            ret += ' ' + ' '.join(self.features)
        if self.is_expensive:
            ret += ' (inc. expensive)'
        return ret


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
    print('Building {}target'.format('expensive ' if spec.is_expensive else ''),
          file=sys.stderr)

    def cargo(*args: typing.Union[str, Path],
              add_features: bool = True) -> None:
        cmd = ['cargo', *args]
        if add_features:
            cmd.extend(spec.features)
        if spec.is_release:
            cmd.append('--release')
        if runner(cmd, cwd=utils.REPO_DIR) != 0:
            raise BuildFailure()

    def copy(src_dir: Path, files: typing.Iterable[str], dst_dir: Path) -> None:
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
        return bool(stat.S_ISREG(attrs.st_mode) and attrs.st_mode & 0o100)

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
         files=[name for name in os.listdir(src_dir) if name.endswith('.wasm')])

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


def wait_for_free_space(server: builder_db.BuilderDB) -> None:
    """Wait until there's at least 20% free space on /datadrive.

    If there's less than 50GB of free space on /datadrive file system, delete
    finished builds and wait until enough tests finish that enough free space
    becomes available.  50GB threshold has been chosen to be able to finish any
    build even in the worst circumstances.  Considering that even the largest
    build does not exceed 15GB this should be a safe bet.

    Args:
        server: Database to query for finished tests.
    """

    def enough_space() -> bool:
        return psutil.disk_usage(str(utils.WORKDIR)).free >= 50_000_000_000

    def clean_finished() -> bool:
        bids = server.builds_without_pending_tests()
        if bids:
            utils.rmdirs(*[utils.BUILDS_DIR / str(bid) for bid in bids])
            server.unassign_builds(bids)
        return enough_space()

    if enough_space() or clean_finished():
        return

    utils.rmdirs(utils.REPO_DIR / 'target', utils.REPO_DIR / 'target_expensive')
    if enough_space():
        return

    print(
        'Not enough free space; '
        'waiting for tests to finish to clean up more builds',
        file=sys.stderr)
    while True:
        time.sleep(5)
        if clean_finished():
            break
    print('Got enough free space; continuing', file=sys.stderr)


def handle_build(server: builder_db.BuilderDB, spec: BuildSpec) -> None:
    """Handles a single build request."""
    print(spec, file=sys.stderr)
    with utils.Runner() as runner:
        success = False
        try:
            if utils.checkout(spec.sha, runner=runner):
                build_target(spec, runner=runner)
                success = True
        except BuildFailure:
            pass
        except Exception:
            runner.log_traceback()

        print('Build #{} {}'.format(spec.build_id,
                                    'succeeded' if success else 'failed'),
              file=sys.stderr)
        runner.stdout.seek(0)
        stdout = runner.stdout.read()
        runner.stderr.seek(0)
        stderr = runner.stderr.read()
    server.update_build_status(spec.build_id, success, out=stdout, err=stderr)


def keep_pulling() -> None:
    ipv4 = utils.get_ip()
    print('Starting builder at {} ({})'.format(socket.gethostname(),
                                               utils.int_to_ip(ipv4)),
          file=sys.stderr)

    with builder_db.BuilderDB(ipv4) as server:
        server.handle_restart()
        while True:
            wait_for_free_space(server)
            try:
                new_build = server.get_new_build()
                if new_build:
                    handle_build(server, BuildSpec.from_row(new_build))
                    continue
            except Exception:
                traceback.print_exc()
                server.handle_restart()
            time.sleep(10)


if __name__ == '__main__':
    utils.setup_environ()
    keep_pulling()
