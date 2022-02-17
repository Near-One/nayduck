import atexit
from collections import defaultdict
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import pathlib
import random
import shlex
import signal
import subprocess
import sys
import threading
import time
import typing
import uuid

import google.api_core.exceptions
import google.cloud.storage as gcs
import inotify.adapters
import prometheus_client
import toml
from typing_extensions import TypedDict
import zulip

from lib import config
from workers import utils

WORKDIR = utils.WORKDIR
REPO_URL = utils.REPO_URL
#WORKDIR = pathlib.Path('/tmp')
#REPO_URL = 'https://github.com/Ekleog/nearcore'

AUTO_REFRESH_INTERVAL = datetime.timedelta(24 * 3600)
SYNC_LOG_UPLOAD_INTERVAL = datetime.timedelta(3600)
#AUTO_REFRESH_INTERVAL = datetime.timedelta(seconds=300)
#SYNC_LOG_UPLOAD_INTERVAL = datetime.timedelta(seconds=30)


def connect_to_gcs() -> gcs.Client:
    """Setup the environment to have gsutils work, and return a connection to GCS"""
    subprocess.run(
        [
            'gcloud', 'auth', 'activate-service-account', '--key-file',
            GCS_CREDENTIALS_FILE
        ],
        check=True,
    )
    return gcs.Client.from_service_account_json(str(GCS_CREDENTIALS_FILE))
    #return gcs.Client(project = 'near-nayduck')


NUM_FUZZERS = typing.cast(int, os.cpu_count())
#NUM_FUZZERS = 1

CMD_PORT = 7055
METRICS_PORT = 5507

REPO_DIR = WORKDIR / 'fuzzed-nearcore'
LOGS_DIR = WORKDIR / 'fuzz-logs'
CORPUS_DIR = WORKDIR / 'fuzz-corpus'

ZULIPRC = config.CONFIG_DIR / 'zuliprc'
GCS_CREDENTIALS_FILE = config.CONFIG_DIR / 'credentials.json'
GCS_BUCKET = 'fuzzer'

FUZZ_BUILD_TIME = prometheus_client.Counter('fuzz_build_seconds',
                                            'Time spent building fuzzers',
                                            ['branch', 'crate', 'runner'])
FUZZ_TIME = prometheus_client.Counter('fuzz_seconds', 'Time spent fuzzing',
                                      ['branch', 'crate', 'runner', 'flags'])
FUZZ_CRASHES = prometheus_client.Counter(
    'fuzz_crashes',
    'Number of times the fuzzer process crashed (not unique crashes)',
    ['branch', 'crate', 'runner', 'flags'])
FUZZ_ARTIFACTS_FOUND = prometheus_client.Counter(
    'fuzz_artifacts_found',
    'Number of artifacts found (should be number of unique crashes)',
    ['crate', 'runner'])
FUZZ_CORPUS_UPLOADED = prometheus_client.Counter(
    'fuzz_corpus_uploaded', 'Number of elements uploaded to GCS corpus',
    ['crate', 'runner'])
FUZZ_CORPUS_DELETED = prometheus_client.Counter(
    'fuzz_corpus_deleted', 'Number of elements deleted from GCS corpus',
    ['crate', 'runner'])

BranchType = TypedDict('BranchType', {'name': str, 'weight': int})
TargetType = TypedDict('TargetType', {
    'crate': str,
    'runner': str,
    'weight': int,
    'flags': typing.List[str]
})
ConfigType = TypedDict('ConfigType', {
    'branch': typing.List[BranchType],
    'target': typing.List[TargetType]
})

# Branch name -> list of reported artifacts
REPORTED_ARTIFACTS: typing.DefaultDict[str,
                                       typing.List[str]] = defaultdict(list)


class Repository:

    def __init__(self, repo_dir: pathlib.Path, url: str):
        """Create a Repository object"""

        self.repo_dir = repo_dir
        self.url = url

    def clone_if_need_be(self) -> None:
        """Clone the repository from `self.url` if it is not present yet"""

        if not self.repo_dir.exists() or not (self.repo_dir /
                                              '.git-clone').exists():
            print(f'Doing initial clone of repository {self.repo_dir}',
                    file=sys.stderr)
            utils.mkdirs(self.repo_dir)
            subprocess.check_call(['git', 'clone', self.url, '.git-clone'],
                                  cwd=self.repo_dir)

    def worktree(self, branch: str) -> pathlib.Path:
        """
        Checks out a worktree on the tip of `branch` in repo at `self.url`, and return the path to
        the worktree.
        """

        print(f'Updating to latest commit of branch {branch}', file=sys.stderr)
        worktree_path = self.repo_dir / branch
        if worktree_path.exists():
            subprocess.check_call(
                ['git', 'fetch', self.url, f'refs/heads/{branch}'],
                cwd=worktree_path)
            subprocess.check_call(['git', 'checkout', 'FETCH_HEAD'],
                                  cwd=worktree_path)
        else:
            print(f'Doing initial checkout of branch {branch}', file=sys.stderr)
            subprocess.check_call(
                ['git', 'fetch', self.url, f'refs/heads/{branch}'],
                cwd=self.repo_dir / '.git-clone')
            subprocess.check_call(
                ['git', 'worktree', 'add', worktree_path, 'FETCH_HEAD'],
                cwd=self.repo_dir / '.git-clone',
            )

        return worktree_path

    def latest_config(self, branch: str) -> ConfigType:
        """Parses the configuration from the tip of `branch` of repo self.url"""

        # TODO: rather than checking out master before parsing the config, we could use
        # git fetch <repo>; git show FETCH_HEAD:nightly/fuzz.toml to get the file contents
        return typing.cast(
            ConfigType,
            toml.load(self.worktree(branch) / 'nightly' / 'fuzz.toml'))


class Corpus:

    def __init__(self, directory: pathlib.Path, bucket: gcs.Bucket):
        """Create a corpus object that'll be using directory `directory`"""
        self.dir = directory
        self.bucket = bucket
        self.inotify_threads: typing.List[InotifyThread] = []
        self.version = '<unknown>'

    def update(self) -> None:
        """Figure out the latest version of the corpus on GCS and download it"""
        if self.inotify_threads:
            raise RuntimeError(
                'Attempted updating a corpus that has live notifiers')
        self.version = self.bucket.blob(
            'current-corpus').download_as_text().strip()

    def synchronize(self, crate: str, runner: str,
                    log_file: typing.IO[str]) -> None:
        """Download the corpus for `crate/runner` from GCS, then upload there any local changes"""
        if self._sync_running_for(crate, runner):
            raise RuntimeError(
                f'Attempted to synchronize {crate}/{runner} that\'s already being synchronized'
            )
        base = pathlib.Path(crate) / runner
        self._reset_to_gcs(base / 'corpus', log_file)
        self._reset_to_gcs(base / 'artifacts', log_file)
        self._auto_upload(base / 'corpus', crate, runner, log_file, False)
        self._auto_upload(base / 'artifacts', crate, runner, log_file, True)

    def stop_synchronizing(self) -> None:
        for thread in self.inotify_threads:
            thread.exit_event.set()
        for thread in self.inotify_threads:
            thread.join()
        self.inotify_threads = []

    def corpus_for(self, target: TargetType) -> pathlib.Path:
        """Return the path to the corpus for target `target`"""
        directory = self.dir / target['crate'] / target['runner'] / 'corpus'
        utils.mkdirs(directory)
        return directory

    def artifacts_for(self, target: TargetType) -> pathlib.Path:
        """Return the path to the artifacts for target `target`"""
        directory = self.dir / target['crate'] / target['runner'] / 'artifacts'
        utils.mkdirs(directory)
        return directory

    def _reset_to_gcs(self, path: pathlib.Path,
                      log_file: typing.IO[str]) -> None:
        """Reset `path` to its GCS contents, logging to `log_file`"""
        print(f'Resetting path {self.dir}/{path} to GCS {self.version}/{path}/',
                file=sys.stderr)
        log_file.write(
            f'Resetting path {self.dir}/{path} to GCS {self.version}/{path}/\n')
        log_file.flush()
        utils.mkdirs(self.dir / path)
        subprocess.check_call(
            [
                'gsutil', '-m', 'rsync', '-d',
                f'gs://{self.bucket.name}/{self.version}/{path}/',
                self.dir / path
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    def _auto_upload(self, path: pathlib.Path, crate: str, runner: str,
                     log_file: typing.IO[str], is_artifacts: bool) -> None:
        print(f'Setting up inotify watch to auto-upload changes to '
              f'{self.dir / path} to GCS {self.bucket.name}/{path}/',
              file=sys.stderr)
        log_file.write(f'Setting up inotify watch to auto-upload changes to '
                       f'{self.dir / path} to GCS {self.bucket.name}/{path}/\n')
        log_file.flush()
        thread = InotifyThread(crate=crate,
                               runner=runner,
                               directory=self.dir,
                               bucket=self.bucket,
                               version=self.version,
                               path=path,
                               log_file=log_file,
                               is_artifacts=is_artifacts)
        thread.start()
        self.inotify_threads.append(thread)

    def _sync_running_for(self, crate: str, runner: str) -> bool:
        return any(t.crate == crate and t.runner == runner
                   for t in self.inotify_threads)


class InotifyThread(threading.Thread):
    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        *,
        crate: str,
        runner: str,
        directory: pathlib.Path,
        bucket: gcs.Bucket,
        version: str,
        path: pathlib.Path,
        log_file: typing.IO[str],
        is_artifacts: bool,
    ) -> None:
        """
        Prepare an inotify thread for running. The thread can be called with `.run()`.

        `crate` and `runner` are resp. the crate path from repository root and the runner name.
        `directory` is the root of the corpus directory in use.
        `bucket` is the GCS bucket to which to upload/delete the new items.
        `version` is the corpus version in the GCS bucket (first path item, used to handle corpus
        minimization).
        `path` is the path to watch, starting from the corpus root.
        `log_file` is an open log file to which to write the syncing operations performed.
        `is_artifacts` is `True` iff the folder to watch is an artifacts (as opposed to corpus)
        folder. It will not bump the same metrics and will disable the remote deletion logic.
        """

        super().__init__(daemon=True)
        self.crate = crate
        self.runner = runner
        self.dir = directory
        self.bucket = bucket
        self.version = version
        self.path = path
        self.log_file = log_file
        self.is_artifacts = is_artifacts

        self.exit_event = threading.Event()
        self.corpus_uploaded_metric = FUZZ_CORPUS_UPLOADED.labels(crate, runner)
        self.corpus_deleted_metric = FUZZ_CORPUS_DELETED.labels(crate, runner)
        self.artifacts_found_metric = FUZZ_ARTIFACTS_FOUND.labels(crate, runner)

    def run(self) -> None:
        utils.mkdirs(self.dir / self.path)
        i = inotify.adapters.Inotify()
        i.add_watch((self.dir / self.path).as_posix())
        while not self.exit_event.is_set():
            # check for exit_event at most every second
            for event in i.event_gen(yield_nones=False, timeout_s=1):
                if self.exit_event.is_set():
                    break
                (_, event_types, _, filename) = event
                local_filename = self.dir / self.path / filename
                remote_filename = f'{self.version}/{self.path}/{filename}'

                if 'IN_CLOSE_WRITE' in event_types:
                    self.log_file.write(
                        f'Uploading new corpus item {local_filename} to GCS {remote_filename}\n'
                    )
                    self.log_file.flush()
                    try:
                        # TODO: batch uploads
                        self.bucket.blob(remote_filename).upload_from_filename(
                            local_filename)
                        if self.is_artifacts:
                            self.artifacts_found_metric.inc()
                        else:
                            self.corpus_uploaded_metric.inc()
                    except FileNotFoundError:
                        pass  # Ignore, as it'd mean the file has been deleted already

                if 'IN_DELETE' in event_types and not self.is_artifacts:
                    self.log_file.write(
                        f'Removing now-removed corpus item {local_filename} '
                        f'as GCS {remote_filename}\n')
                    self.log_file.flush()
                    try:
                        # TODO: batch
                        self.bucket.blob(remote_filename).delete()
                        self.corpus_deleted_metric.inc()
                    except google.api_core.exceptions.NotFound:
                        pass  # Ignore, as it'd mean the file isn't there already


class FuzzProcess:
    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        *,
        corpus_vers: str,
        branch: BranchType,
        target: TargetType,
        repo_dir: pathlib.Path,
        log_relpath: pathlib.Path,
        log_fullpath: pathlib.Path,
    ):
        """
        Create a FuzzProcess object. It can be built with `.build()` and then started with
        `.start()`.

        `corpus_vers` is the version of the corpus (first path item), used only for logging.
        `branch` and `target` are the configuration parameters to run this process with.
        `repo_dir` is the path to the nearcore checkout root.
        `log_relpath` is the relative path from the log folder to the log file.
        `log_fullpath` is the absolute path to the log file.s
        """

        self.corpus_vers = corpus_vers
        self.branch = branch
        self.target = target
        self.repo_dir = repo_dir
        self.log_relpath = log_relpath
        self.log_fullpath = log_fullpath
        self.log_file = open(log_fullpath, 'a', encoding='utf-8')  # pylint: disable=consider-using-with

        self.last_time = 0.
        self.proc: typing.Any = None  # There's some weirdness around brackets and Popen

        self.fuzz_build_time_metric = FUZZ_BUILD_TIME.labels(
            branch['name'], target['crate'], target['runner'])
        self.fuzz_time_metric = FUZZ_TIME.labels(branch['name'],
                                                 target['crate'],
                                                 target['runner'],
                                                 target['flags'])
        self.fuzz_crashes_metric = FUZZ_TIME.labels(branch['name'],
                                                    target['crate'],
                                                    target['runner'],
                                                    target['flags'])

    def build(self) -> None:
        """
        Build the fuzzer runner.

        This is a synchronous operation for convenience reasons, as cargo itself uses all the
        available cores most of the time it shouldn't be a big deal. The only drawback is that
        requests to pause/exit the fuzzer would block until the current build is completed.
        """
        print(f'Building fuzzer for branch {self.branch} and target '
              f'{self.target}, log is at {self.log_relpath}', file=sys.stderr)

        # Log metadata information
        current_commit = str(
            subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=self.repo_dir,
                capture_output=True,
                check=True,
            ).stdout)
        self.log_file.write(f'Corpus version: {self.corpus_vers}\n')
        self.log_file.write(
            f'On commit {current_commit} (tip of branch {self.branch["name"]})\n'
        )
        self.log_file.write(f'Target is {self.target}')
        self.log_file.flush()

        # Build the fuzzer runner
        # TODO: actually build and have build time metrics for the fuzzer runner, but this must not
        # block the pause/resume behavior
        #build_start = time.monotonic()
        #subprocess.check_call(
        #    ['cargo', 'fuzz', 'build', self.target['runner']],
        #    cwd=self.repo_dir / self.target['crate'],
        #    stdout=self.log_file,
        #    stderr=subprocess.STDOUT,
        #)
        #self.fuzz_build_time_metric.inc(time.monotonic() - build_start)

    def start(self, corpus: Corpus) -> None:
        """Start the fuzzer runner on corpus `Corpus`"""
        print(f'Starting fuzzer for branch {self.branch} and '
              f'target {self.target}, log is at {self.log_relpath}',
              file=sys.stderr)

        # Prepare the fuzz time metric
        self.last_time = time.monotonic()

        # Spin up the fuzzer process itself
        self.proc = subprocess.Popen(  # pylint: disable=consider-using-with
            [
                'cargo',
                'fuzz',
                'run',
                self.target['runner'],
                '--',
                str(corpus.corpus_for(self.target)),
                str(corpus.artifacts_for(self.target)),
                f'-artifact_prefix={corpus.artifacts_for(self.target)}/',
            ] + self.target['flags'],
            cwd=self.repo_dir / self.target['crate'],
            start_new_session=True,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
        )

    def poll(self) -> bool:
        """Checks if the current process is still running. Returns True if it stopped"""
        if self.proc.poll() is None:
            new_time = time.monotonic()
            self.fuzz_time_metric.inc(new_time - self.last_time)
            self.last_time = new_time
            return False
        # else: Fuzz crash found
        print(f'Fuzzer running {self.target} has stopped', file=sys.stderr)
        self.fuzz_crashes_metric.inc()
        return True

    def report_crash(self, corpus: Corpus, bucket: gcs.Bucket) -> None:
        # pylint: disable=too-many-locals

        with open(self.log_fullpath, 'r', encoding='utf-8') as log_file_r:
            log_lines = log_file_r.readlines()

        artifact_pattern = f'Test unit written to {corpus.artifacts_for(self.target)}/'
        artifact = '<failed detecting relevant artifact in log file>'
        for line in log_lines[::-1]:
            if artifact_pattern in line:
                artifact = line.split(artifact_pattern)[1].strip()
                break

        branch = self.branch['name']
        logs_url = f'https://storage.cloud.google.com/fuzzer/logs/{self.log_relpath}'

        # Check the artifact was not reported yet for this branch
        if artifact in REPORTED_ARTIFACTS[branch]:
            return
        already_reported_for = [
            other_branch for (other_branch,
                              reported_artifacts) in REPORTED_ARTIFACTS.items()
            if artifact in reported_artifacts
        ]
        REPORTED_ARTIFACTS[branch].append(artifact)

        if already_reported_for:
            already_reported_msg = f'(already reported for branches {already_reported_for})'
        else:
            already_reported_msg = ''

        # Send the information in two mesages, a short one guaranteed to succeed, then a long one
        # with the log lines that could go over the message size limit
        client = zulip.Client(config_file=ZULIPRC)
        gcs_artifact = shlex.quote(
            f'gs://{bucket.name}/{self.corpus_vers}/{self.target["crate"]}/'
            f'{self.target["runner"]}/artifacts/{artifact}')
        artifact_dest = shlex.quote(
            f'{self.target["crate"]}/artifacts/{self.target["runner"]}/{artifact}'
        )
        quoted_crate = shlex.quote(self.target['crate'])
        quoted_runner = shlex.quote(self.target['runner'])
        quoted_artifact = shlex.quote(
            f'artifacts/{self.target["runner"]}/{artifact}')
        client.send_message({
            'type':
                'stream',
            'to':
                'nearinc/fuzzer/private',
            'topic':
                f'{branch}: artifact {artifact}',
            'content':
                f'''\
# Fuzzer found new crash for branch *{branch}* {already_reported_msg}

Full logs are available at {logs_url}.

You can download the artifact by using the following command (all commands \
are to be run from the root of `nearcore`):
```
gsutil cp {gcs_artifact} {artifact_dest}
```

Then, you can reproduce by running the following command:
```
cd {quoted_crate}
RUSTC_BOOTSTRAP=1 cargo fuzz run {quoted_runner} {quoted_artifact}
```

Or minimize by running the following command:
```
cd {quoted_crate}
RUSTC_BOOTSTRAP=1 cargo fuzz tmin {quoted_runner} {quoted_artifact}
```

Please edit the topic name to add more meaningful information once investigated. \
Keeping the artifact hash in it can help if the same artifact gets detected as \
crashing another branch.
'''
        })
        last_log_lines = ''
        for line in log_lines[::-1]:
            if line.startswith('```'):
                # Censor the end of a spoiler block, not great but this is for human consumption
                # anyway
                line = ' ' + line
            if len(last_log_lines) + len(line) > 9000:
                # Zulip limit is 10k, let's keep some safety buffer here
                break
            last_log_lines = line + last_log_lines
        client.send_message({
            'type': 'stream',
            'to': 'nearinc/fuzzer/private',
            'topic': f'{branch}: artifact {artifact}',
            'content': f'```spoiler Last few log lines\n{last_log_lines}\n```',
        })

    def signal(self, sig: int) -> None:
        """
        Signal the fuzzer process (with all its process group as a fuzzer can spawn sub-fuzzers)
        """

        print(f'Sending signal {sig} to fuzzer {self.proc.pid}', file=sys.stderr)
        os.killpg(os.getpgid(self.proc.pid), sig)


# Actually this should also require a ['weight']: int bound but it seems like a mess to encode
T = typing.TypeVar('T')  # pylint: disable=invalid-name


def random_weighted(array: typing.List[T], num: int) -> typing.List[T]:
    untyped_array = typing.cast(typing.Any, array)
    return random.choices(array, [x['weight'] for x in untyped_array], k=num)


def pause_exit_spot(pause_evt: threading.Event, resume_evt: threading.Event,
                    exit_evt: threading.Event) -> bool:
    """
    Poll the events, returning True if `exit_evt` was set and pausing as requested by `pause_evt`
    and `resume_evt`
    """

    resume_evt.clear()
    if pause_evt.is_set():
        while not resume_evt.wait(timeout=1):
            if exit_evt.is_set():
                return True
        pause_evt.clear()
    return exit_evt.is_set()


def kill_fuzzers(bucket: gcs.Bucket,
                 fuzzers: typing.Iterable[FuzzProcess]) -> None:
    for fuzzer in fuzzers:
        try:
            fuzzer.signal(signal.SIGTERM)
        except ProcessLookupError:
            print(f'Failed looking up process {fuzzer.proc.pid}',
                    file=sys.stderr)
    time.sleep(5)
    for fuzzer in fuzzers:
        try:
            fuzzer.signal(signal.SIGKILL)
        except ProcessLookupError:
            print(f'Failed looking up process {fuzzer.proc.pid}',
                    file=sys.stderr)
    for fuzzer in fuzzers:
        bucket.blob(f'logs/{fuzzer.log_relpath}').upload_from_filename(
            str(LOGS_DIR / fuzzer.log_relpath))


def run_fuzzers(gcs_client: gcs.Client, pause_evt: threading.Event,
                resume_evt: threading.Event, exit_evt: threading.Event) -> None:
    """
    Run all the fuzzers until `exit_evt` gets triggered, pausing and resuming
    them based on `pause_evt` and `resume_evt`.
    """
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements

    bucket = gcs_client.bucket(GCS_BUCKET)

    repo = Repository(REPO_DIR, REPO_URL)
    repo.clone_if_need_be()

    corpus = Corpus(CORPUS_DIR, bucket)

    while True:
        if pause_exit_spot(pause_evt, resume_evt, exit_evt):
            return

        sync_log_files = []
        date = datetime.datetime.now().strftime('%Y-%m-%d')

        # Read the configuration from the repository
        cfg = repo.latest_config('master')
        cfg_for = {
            b['name']: repo.latest_config(b['name']) for b in cfg['branch']
        }

        # Figure out which targets we want to run
        branches = random_weighted(cfg['branch'], NUM_FUZZERS)
        targets = [
            random_weighted(cfg_for[b['name']]['target'], 1)[0]
            for b in branches
        ]

        # Synchronize the relevant corpuses
        corpus.stop_synchronizing()
        corpus.update()
        for targ in set((t['crate'], t['runner']) for t in targets):
            log_path = pathlib.Path('sync') / date / targ[0] / targ[1] / str(
                uuid.uuid4())
            utils.mkdirs((LOGS_DIR / log_path).parent)
            # pylint: disable=consider-using-with
            corpus.synchronize(targ[0], targ[1],
                               open(LOGS_DIR / log_path, 'a', encoding='utf-8'))
            # pylint: enable=consider-using-with
            sync_log_files.append(log_path)
            if pause_exit_spot(pause_evt, resume_evt, exit_evt):
                return

        # Initialize the fuzzers
        fuzzers = []
        for (branch, target) in zip(branches, targets):
            worktree = repo.worktree(branch['name'])
            log_path = pathlib.Path(
                'fuzz') / date / target['crate'] / target['runner'] / str(
                    uuid.uuid4())
            log_file = LOGS_DIR / log_path
            utils.mkdirs(log_file.parent)
            fuzzers.append(
                FuzzProcess(corpus_vers=corpus.version,
                            branch=branch,
                            target=target,
                            repo_dir=worktree,
                            log_relpath=log_path,
                            log_fullpath=log_file))

        # Build the fuzzers
        for fuzzer in fuzzers:
            fuzzer.build()
            if pause_exit_spot(pause_evt, resume_evt, exit_evt):
                return

        # Start the fuzzers
        atexit.register(kill_fuzzers, bucket, fuzzers)
        for fuzzer in fuzzers:
            fuzzer.start(corpus)

        # Wait until something happens
        started = time.monotonic()
        last_sync_file_upload = started
        next_restart = started + AUTO_REFRESH_INTERVAL.total_seconds()
        while time.monotonic() < next_restart:
            # Exit event happened?
            if exit_evt.is_set():
                kill_fuzzers(bucket, fuzzers)
                atexit.unregister(kill_fuzzers)
                return

            # Pause event happened?
            resume_evt.clear()
            if pause_evt.is_set():
                for fuzzer in fuzzers:
                    fuzzer.signal(signal.SIGSTOP)
                while not resume_evt.wait(timeout=1):
                    if exit_evt.is_set():
                        kill_fuzzers(bucket, fuzzers)
                        atexit.unregister(kill_fuzzers)
                        return
                pause_evt.clear()
                for fuzzer in fuzzers:
                    fuzzer.signal(signal.SIGCONT)

            # Fuzz crash found?
            for fuzzer in fuzzers:
                if fuzzer.poll():
                    bucket.blob(
                        f'logs/{fuzzer.log_relpath}').upload_from_filename(
                            str(fuzzer.log_fullpath))
                    fuzzer.report_crash(corpus, bucket)
                    fuzzers.remove(fuzzer)

                    # Start a new fuzzer
                    branch = random_weighted(branches, 1)[0]
                    target = random_weighted(targets, 1)[0]
                    worktree = repo.worktree(branch['name'])
                    log_path = pathlib.Path('fuzz') / date / target[
                        'crate'] / target['runner'] / str(uuid.uuid4())
                    utils.mkdirs((LOGS_DIR / log_path).parent)
                    log_file = LOGS_DIR / log_path
                    new_fuzzer = FuzzProcess(corpus_vers=corpus.version,
                                             branch=branch,
                                             target=target,
                                             repo_dir=worktree,
                                             log_relpath=log_path,
                                             log_fullpath=log_file)
                    # TODO: building the fuzzer should not block receiving the pause/resume messages
                    new_fuzzer.build()
                    new_fuzzer.start(corpus)
                    fuzzers.append(new_fuzzer)

            # Regularly upload the sync log files
            upload_interval_secs = SYNC_LOG_UPLOAD_INTERVAL.total_seconds()
            next_sync = last_sync_file_upload + upload_interval_secs
            if time.monotonic() > next_sync:
                last_sync_file_upload = time.monotonic()
                for line in sync_log_files:
                    bucket.blob(f'logs/{line}').upload_from_filename(
                        str(LOGS_DIR / line))

    # TODO: Minimize the corpus
    # TODO: Rsync the corpus from gcs more frequently, not just once per fuzzer restart
    # TODO: Add corpus size gauge metric
    # TODO: Add coverage metrics (will need to parse logs?)
    # TODO: Add metrics about overhead (time to update corpus, to build fuzzer, etc.)


def listen_for_commands(pause_event: threading.Event,
                        resume_event: threading.Event) -> None:
    """
    Spawn an HTTP server to remote control the fuzzers

    `/pause` and `/resume` respectively sigstop and sigcont the fuzzers
    """

    class HTTPHandler(BaseHTTPRequestHandler):

        def do_GET(self) -> None:  # pylint: disable=invalid-name
            if self.path == '/pause':
                resume_event.clear()
                pause_event.set()
                self.send_response(200)
            elif self.path == '/resume':
                pause_event.clear()
                resume_event.set()
                self.send_response(200)
            else:
                self.send_response(404)
            self.end_headers()

    with HTTPServer(('127.0.0.1', CMD_PORT), HTTPHandler) as httpd:
        print(f'Serving command server on port {CMD_PORT}', file=sys.stderr)
        httpd.serve_forever()


# TODO: replace Any here with something more precise
THREAD_EXCEPTION: typing.Optional[typing.Any] = None
EXCEPTION_HAPPENED_IN_THREAD = threading.Event()


def main() -> None:
    """Main function"""

    # Make sure to cleanup upon ctrl-c or upon any exception in a thread
    def new_excepthook(args: typing.Any) -> None:
        global THREAD_EXCEPTION
        THREAD_EXCEPTION = args
        EXCEPTION_HAPPENED_IN_THREAD.set()

    threading.excepthook = new_excepthook

    try:
        gcs_client = connect_to_gcs()

        # Start the metrics server
        prometheus_client.start_http_server(METRICS_PORT)

        # And listen for the commands that might come up
        pause_event = threading.Event()
        resume_event = threading.Event()
        threading.Thread(daemon=True,
                         target=listen_for_commands,
                         args=(pause_event, resume_event)).start()

        # Run until an exception forces us to stop
        print('Startup complete, will start running forever now',
                file=sys.stderr)
        run_fuzzers(gcs_client, pause_event, resume_event,
                    EXCEPTION_HAPPENED_IN_THREAD)

        # Finally, proxy the exception so it gets detected and acted upon by a human
        exc_info = THREAD_EXCEPTION
        if exc_info is not None:
            raise exc_info.exc_value
    except KeyboardInterrupt:
        print('Got ^C, stopping', file=sys.stderr)


if __name__ == '__main__':
    utils.setup_environ()
    os.environ['RUSTC_BOOTSTRAP'] = '1'  # Nightly is needed by cargo-fuzz
    main()
