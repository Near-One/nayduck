import atexit
from collections import defaultdict
import datetime
import google
import google.cloud.storage as gcs
from http.server import BaseHTTPRequestHandler, HTTPServer
import inotify.adapters
import os
import pathlib
import prometheus_client
import random
import signal
import subprocess
import sys
import threading
import time
import toml
import typing
import uuid

from lib import config
from workers import utils

#WORKDIR = utils.WORKDIR
#REPO_URL = utils.REPO_URL
WORKDIR = pathlib.Path('/tmp')
REPO_URL = 'https://github.com/Ekleog/nearcore'
def connect_to_gcs() -> gcs.Client:
    """Setup the environment to have gsutils work, and return a connection to GCS"""
    #subprocess.run(
    #    ['gcloud', 'auth', 'activate-service-account', '--key-file', GCS_CREDENTIALS_FILE],
    #    check = True,
    #)
    #return gcs.Client.from_service_account_json(str(GCS_CREDENTIALS_FILE))
    return gcs.Client(project = 'near-nayduck')

NUM_FUZZERS = typing.cast(int, os.cpu_count())
#NUM_FUZZERS = 1

#AUTO_REFRESH_INTERVAL_SECS = 24 * 3600
#SYNC_LOG_UPLOAD_INTERVAL_SECS = 3600
AUTO_REFRESH_INTERVAL_SECS = 300
SYNC_LOG_UPLOAD_INTERVAL_SECS = 30

CMD_PORT = 7055
METRICS_PORT = 5507

REPO_DIR = WORKDIR / 'fuzzed-nearcore'
LOGS_DIR = WORKDIR / 'fuzz-logs'
CORPUS_DIR = WORKDIR / 'fuzz-corpus'

GCS_CREDENTIALS_FILE = config.CONFIG_DIR / 'credentials.json'
GCS_BUCKET = 'fuzzer'

# pylint: disable=line-too-long
FUZZ_BUILD_TIME = prometheus_client.Counter('fuzz_build_seconds', 'Time spent building fuzzers', ['branch', 'crate', 'runner'])
FUZZ_TIME = prometheus_client.Counter('fuzz_seconds', 'Time spent fuzzing', ['branch', 'crate', 'runner', 'flags'])
FUZZ_CRASHES = prometheus_client.Counter('fuzz_crashes', 'Number of times the fuzzer process crashed (not unique crashes)', ['branch', 'crate', 'runner', 'flags'])
FUZZ_ARTIFACTS_FOUND = prometheus_client.Counter('fuzz_artifacts_found', 'Number of artifacts found (should be number of unique crashes)', ['crate', 'runner'])
FUZZ_CORPUS_UPLOADED = prometheus_client.Counter('fuzz_corpus_uploaded', 'Number of elements uploaded to GCS corpus', ['crate', 'runner'])
FUZZ_CORPUS_DELETED = prometheus_client.Counter('fuzz_corpus_deleted', 'Number of elements deleted from GCS corpus', ['crate', 'runner'])
# pylint: enable=line-too-long

# TODO: make these types more precise? But then everything comes from toml.load so...
ConfigType = typing.Any
BranchType = typing.Any
TargetType = typing.Any

REPORTED_ARTIFACTS = defaultdict(list)

class Repository:
    def __init__(self, repo_dir: pathlib.Path, url: str):
        """Create a Repository object"""

        self.repo_dir = repo_dir
        self.url = url
    
    def clone_if_need_be(self):
        """Clone the repository from `self.url` if it is not present yet"""

        if not self.repo_dir.exists():
            print(f"Doing initial clone of repository {self.repo_dir}")
            utils.mkdirs(self.repo_dir)
            subprocess.check_call(['git', 'clone', self.url, '.git-clone'], cwd=self.repo_dir)

    def worktree(self, branch: str) -> pathlib.Path:
        """
        Checks out a worktree on the tip of `branch` in repo at `self.url`, and return the path to
        the worktree.
        """

        print(f"Updating to latest commit of branch {branch}")
        worktree_path = self.repo_dir / branch
        if worktree_path.exists():
            subprocess.check_call(['git', 'fetch', self.url, f'refs/heads/{branch}'], cwd=worktree_path)
            subprocess.check_call(['git', 'checkout', 'FETCH_HEAD'], cwd=worktree_path)
        else:
            print(f"Doing initial checkout of branch {branch}")
            subprocess.check_call(['git', 'fetch', self.url, f'refs/heads/{branch}'], cwd=self.repo_dir / '.git-clone')
            subprocess.check_call(
                ['git', 'worktree', 'add', worktree_path, 'FETCH_HEAD'],
                cwd = self.repo_dir / '.git-clone',
            )

        return worktree_path

    def latest_config(self, branch) -> ConfigType:
        """Parses the configuration from the tip of `branch` of repo self.url"""

        # TODO: rather than checking out master before parsing the config, we could use
        # git fetch <repo>; git show FETCH_HEAD:nightly/fuzz.toml to get the file contents
        return toml.load(self.worktree(branch) / 'nightly' / 'fuzz.toml')

class Corpus:
    def __init__(self, dir: pathlib.Path, bucket: gcs.Bucket):
        """Create a corpus object that'll be using directory `dir`"""
        self.dir = dir
        self.bucket = bucket
        self.inotify_threads = []

    def update(self):
        """Figure out the latest version of the corpus on GCS and download it"""
        if len(self.inotify_threads) != 0:
            raise RuntimeError("Attempted updating a corpus that has alive notifiers")
        self.version = self.bucket.blob('current-corpus').download_as_text().strip()

    def synchronize(self, crate: str, runner: str, log_file: typing.IO[str]):
        """Download the corpus for `crate/runner` from GCS, then upload there any local changes"""
        if self._sync_running_for(crate, runner):
            raise RuntimeError(f"Attempted to synchronize {crate}/{runner} that's already being synchronized")
        base = pathlib.Path(crate) / runner
        self._reset_to_gcs(base / 'corpus', log_file)
        self._reset_to_gcs(base / 'artifacts', log_file)
        self._auto_upload(base / 'corpus', crate, runner, log_file, False)
        self._auto_upload(base / 'artifacts', crate, runner, log_file, True)

    def stop_synchronizing(self) -> None:
        for t in self.inotify_threads:
            t.exit_event.set()
        for t in self.inotify_threads:
            t.join()
        self.inotify_threads = []

    def corpus_for(self, target: TargetType) -> pathlib.Path:
        """Return the path to the corpus for target `target`"""
        dir = self.dir / target['crate'] / target['runner'] / 'corpus'
        utils.mkdirs(dir)
        return dir

    def artifacts_for(self, target: TargetType) -> pathlib.Path:
        """Return the path to the artifacts for target `target`"""
        dir = self.dir / target['crate'] / target['runner'] / 'artifacts'
        utils.mkdirs(dir)
        return dir

    def _reset_to_gcs(self, path: pathlib.Path, log_file: typing.IO[str]) -> None:
        """Reset `path` to its GCS contents, logging to `log_file`"""
        print(f"Resetting path {self.dir}/{path} to GCS {self.version}/{path}/")
        log_file.write(f"Resetting path {self.dir}/{path} to GCS {self.version}/{path}/\n")
        log_file.flush()
        utils.mkdirs(self.dir / path)
        subprocess.check_call(
            ['gsutil', '-m', 'rsync', '-d', f"gs://{self.bucket.name}/{self.version}/{path}/", self.dir / path],
            stdout = log_file,
            stderr = subprocess.STDOUT,
        )

    def _auto_upload(self, path: pathlib.Path, crate: str, runner: str, log_file: typing.IO[str], is_artifacts: bool) -> None:
        # pylint: disable=line-too-long
        print(f"Setting up inotify watch to auto-upload changes to {self.dir / path} to GCS {self.bucket.name}/{path}/")
        log_file.write(f"Setting up inotify watch to auto-upload changes to {self.dir / path} to GCS {self.bucket.name}/{path}/\n")
        log_file.flush()
        # pylint: enable=line-too-long
        thread = InotifyThread(crate, runner, self.dir, self.bucket, self.version, path, log_file, is_artifacts)
        thread.start()
        self.inotify_threads.append(thread)

    def _sync_running_for(self, crate: str, runner: str) -> bool:
        for t in self.inotify_threads:
            if t.crate == crate and t.runner == runner:
                return True
        return False

class InotifyThread(threading.Thread):
    def __init__(
        self,
        crate: str,
        runner: str,
        dir: pathlib.Path,
        bucket: gcs.Bucket,
        version: str,
        path: pathlib.Path,
        log_file: typing.IO[str],
        is_artifacts: bool,
    ) -> None:
        threading.Thread.__init__(self, daemon=True)
        self.crate = crate
        self.runner = runner
        self.dir = dir
        self.bucket = bucket
        self.version = version
        self.path = path
        self.log_file = log_file
        self.is_artifacts = is_artifacts

        self.exit_event = threading.Event()
        self.corpus_uploaded_metric = FUZZ_CORPUS_UPLOADED.labels(crate, runner)
        self.corpus_deleted_metric = FUZZ_CORPUS_DELETED.labels(crate, runner)
        self.artifacts_found_metric = FUZZ_ARTIFACTS_FOUND.labels(crate, runner)

    def run(self):
        utils.mkdirs(self.dir / self.path)
        i = inotify.adapters.Inotify()
        i.add_watch((self.dir / self.path).as_posix())
        while not self.exit_event.is_set():
            # check for exit_event at most every second
            for event in i.event_gen(yield_nones = False, timeout_s = 1):
                if self.exit_event.is_set():
                    break
                (_, event_types, _, filename) = event
                local_filename = self.dir / self.path / filename
                remote_filename = f'{self.version}/{self.path}/{filename}'

                if 'IN_CLOSE_WRITE' in event_types:
                    self.log_file.write(
                        f"Uploading new corpus item {local_filename} to GCS {remote_filename}\n"
                    )
                    self.log_file.flush()
                    try:
                        # TODO: batch uploads
                        self.bucket.blob(remote_filename).upload_from_filename(local_filename)
                        if self.is_artifacts:
                            self._report_artifact(remote_filename, self.crate, self.runner)
                        else:
                            self.corpus_uploaded_metric.inc()
                    except FileNotFoundError:
                        pass # Ignore, as it'd mean the file has been deleted already

                if 'IN_DELETE' in event_types and not self.is_artifacts:
                    self.log_file.write(
                        f"Removing now-removed corpus item {local_filename} as GCS {remote_filename}\n"
                    )
                    self.log_file.flush()
                    try:
                        # TODO: batch
                        self.bucket.blob(remote_filename).delete()
                        self.corpus_deleted_metric.inc()
                    except google.api_core.exceptions.NotFound:
                        pass # Ignore, as it'd mean the file isn't there already

    def _report_artifact(self, gcs_path: str, crate: str, runner: str) -> None:
        self.artifacts_found_metric.inc()

class FuzzProcess:
    def __init__(
        self,
        corpus_vers: str,
        branch: BranchType,
        target: TargetType,
        repo_dir: pathlib.Path,
        log_path: pathlib.Path,
        log_filepath: pathlib.Path,
    ):
        """Create a FuzzProcess object"""

        self.corpus_vers = corpus_vers
        self.branch = branch
        self.target = target
        self.repo_dir = repo_dir
        self.log_path = log_path
        self.log_filepath = log_filepath
        self.log_file = open(log_filepath, 'a')

        self.fuzz_build_time_metric = FUZZ_BUILD_TIME.labels(branch['name'], target['crate'], target['runner'])
        self.fuzz_time_metric = FUZZ_TIME.labels(branch['name'], target['crate'], target['runner'], target['flags'])
        self.fuzz_crashes_metric = FUZZ_TIME.labels(branch['name'], target['crate'], target['runner'], target['flags'])

    def build(self):
        """
        Build the fuzzer runner.
        
        This is a synchronous operation for convenience reasons, as cargo itself uses all the
        available cores most of the time it shouldn't be a big deal. The only drawback is that
        requests to pause/exit the fuzzer would block until the current build is completed.
        """
        print(f'Building fuzzer for branch {self.branch} and target {self.target}, log is at {self.log_path}')

        # Log metadata information
        current_commit = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd = self.repo_dir,
            capture_output = True,
            check = True,
        ).stdout
        self.log_file.write(f"Corpus version: {self.corpus_vers}\n")
        self.log_file.write(f"On commit {current_commit} (tip of branch {self.branch['name']})\n")
        self.log_file.write(f"Target is {self.target}")
        self.log_file.flush()

        # Build the fuzzer runner
        build_start = time.monotonic()
        subprocess.check_call(
            ['cargo', 'fuzz', 'build', self.target['runner']],
            cwd = self.repo_dir / self.target['crate'],
            stdout = self.log_file,
            stderr = subprocess.STDOUT,
        )
        self.fuzz_build_time_metric.inc(time.monotonic() - build_start)

    def start(self, corpus: Corpus):
        """Start the fuzzer runner on corpus `Corpus`"""
        print(f'Starting fuzzer for branch {self.branch} and target {self.target}, log is at {self.log_path}')

        # Prepare the fuzz time metric
        self.last_time = time.monotonic()

        # Spin up the fuzzer process itself
        self.proc = subprocess.Popen(
            [
                'cargo',
                'fuzz',
                'run',
                self.target['runner'],
                '--',
                corpus.corpus_for(self.target),
                corpus.artifacts_for(self.target),
                f"-artifact_prefix={corpus.artifacts_for(self.target)}/",
            ] + self.target['flags'],
            cwd = self.repo_dir / self.target['crate'],
            start_new_session = True,
            stdout = self.log_file,
            stderr = subprocess.STDOUT,
        )

    def poll(self):
        """Checks if the current process is still running. Returns True if it stopped"""
        if self.proc.poll() == None:
            new_time = time.monotonic()
            self.fuzz_time_metric.inc(new_time - self.last_time)
            self.last_time = new_time
            return False
        else: # Fuzz crash found
            print(f"Fuzzer running {self.target} has stopped")
            self.fuzz_crashes_metric.inc()
            return True

    def report_crash(self, corpus: Corpus, bucket: gcs.Bucket):
        with open(self.log_filepath, 'r') as log_file_r:
            log_lines = log_file_r.readlines()

        artifact_pattern = f'Test unit written to {corpus.artifacts_for(self.target)}/'
        artifact = "<failed detecting relevant artifact in log file>"
        for l in log_lines[::-1]:
            if artifact_pattern in l:
                artifact = l.split(artifact_pattern)[1][:-1] # Second part of the line except the \n
                break

        branch = self.branch['name']
        logs_url = f"https://storage.cloud.google.com/fuzzer/logs/{self.log_path}"
        downloader = f"gsutil cp gs://{bucket.name}/{self.corpus_vers}/{self.target['crate']}/{self.target['runner']}/artifacts/{artifact} {self.target['crate']}/artifacts/{self.target['runner']}/{artifact}"
        reproducer = f"cd {self.target['crate']}\nRUSTC_BOOTSTRAP=1 cargo fuzz run {self.target['runner']} artifacts/{self.target['runner']}/{artifact}"
        minimizer = f"cd {self.target['crate']}\nRUSTC_BOOTSTRAP=1 cargo fuzz tmin {self.target['runner']} artifacts/{self.target['runner']}/{artifact}"

        # Check the artifact was not reported yet for this branch
        global REPORTED_ARTIFACTS
        if artifact in REPORTED_ARTIFACTS[branch]:
            return
        already_reported_for = []
        for other_branch in REPORTED_ARTIFACTS.keys():
            if artifact in REPORTED_ARTIFACTS[other_branch]:
                already_reported_for.append(other_branch)
        REPORTED_ARTIFACTS[branch].append(artifact)

        if len(already_reported_for) == 0:
            already_reported_msg = ""
        else:
            already_reported_msg = f"(already reported for branches {already_reported_for})"

        # Send the information in two mesages, a short one guaranteed to succeed, then a long one
        # with the log lines that could go over the message size limit
        import textwrap
        import zulip
        client = zulip.Client(config_file="~/.fuzzer-zuliprc")
        client.send_message({
            "type": "stream",
            "to": "nearinc/fuzzer/private",
            "topic": f"{branch}: artifact {artifact}",
            "content": (
                f"# Fuzzer found new crash for branch *{branch}* {already_reported_msg}\n"
                f"Full logs are available at {logs_url}.\n"
                f"\n"
                f"You can download the artifact by using the following command (all commands are to be run from the root of `nearcore`):\n"
                f"```\n"
                f"{downloader}\n"
                f"```\n"
                f"\n"
                f"Then, you can reproduce by running the following command:\n"
                f"```\n"
                f"{reproducer}\n"
                f"```\n"
                f"\n"
                f"Or minimize by running the following command:\n"
                f"```\n"
                f"{minimizer}\n"
                f"```\n"
                f"\n"
                f"Please edit the topic name to add more meaningful information once investigated. Keeping the artifact hash in it can help if the same artifact gets detected as crashing another branch.\n"
            ),
        })
        last_log_lines = ""
        for l in log_lines[::-1]:
            if l.startswith("```"):
                # Censor the end of a spoiler block, not great but this is for human consumption
                # anyway
                l = " " + l
            if len(last_log_lines) + len(l) > 9000:
                # Zulip limit is 10k, let's keep some safety buffer here
                break
            last_log_lines = l + last_log_lines
        client.send_message({
            "type": "stream",
            "to": "nearinc/fuzzer/private",
            "topic": f"{branch}: artifact {artifact}",
            "content": f"```spoiler Last few log lines\n{last_log_lines}\n```",
        })

    def signal(self, signal: int) -> None:
        """
        Signal the fuzzer process (with all its process group as a fuzzer can spawn sub-fuzzers)
        """

        print(f"Sending signal {signal} to fuzzer {self.proc.pid}")
        os.killpg(os.getpgid(self.proc.pid), signal)

def random_weighted(array, num: int):
    return random.choices(array, [x['weight'] for x in array], k = num)

def pause_exit_spot(pause_evt: threading.Event, resume_evt: threading.Event, exit_evt: threading.Event) -> None:
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

def kill_fuzzers(bucket: gcs.Bucket, fuzzers: typing.Iterable[FuzzProcess]):
    for f in fuzzers:
        try:
            f.signal(signal.SIGTERM)
        except ProcessLookupError:
            print(f"Failed looking up process {f.proc.pid}")
    time.sleep(5)
    for f in fuzzers:
        try:
            f.signal(signal.SIGKILL)
        except ProcessLookupError:
            print(f"Failed looking up process {f.proc.pid}")
    for f in fuzzers:
        bucket.blob(f"logs/{f.log_path}").upload_from_filename(LOGS_DIR / f.log_path)

def run_fuzzers(gcs_client: gcs.Client, pause_evt: threading.Event, resume_evt: threading.Event, exit_evt: threading.Event):
    """
    Run all the fuzzers until `exit_evt` gets triggered, pausing and resuming
    them based on `pause_evt` and `resume_evt`.
    """

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
        cfg_for = {b['name']: repo.latest_config(b['name']) for b in cfg['branch']}

        # Figure out which targets we want to run
        branches = random_weighted(cfg['branch'], NUM_FUZZERS)
        targets = [random_weighted(cfg_for[b['name']]['target'], 1)[0] for b in branches]

        # Synchronize the relevant corpuses
        corpus.stop_synchronizing()
        corpus.update()
        for t in set((t['crate'], t['runner']) for t in targets):
            log_path = pathlib.Path('sync') / date / t[0] / t[1] / str(uuid.uuid4())
            utils.mkdirs((LOGS_DIR / log_path).parent)
            corpus.synchronize(t[0], t[1], open(LOGS_DIR / log_path, 'a'))
            sync_log_files.append(log_path)
            if pause_exit_spot(pause_evt, resume_evt, exit_evt):
                return

        # Initialize the fuzzers
        fuzzers = []
        for (b, t) in zip(branches, targets):
            worktree = repo.worktree(b['name'])
            log_path = pathlib.Path('fuzz') / date / t['crate'] / t['runner'] / str(uuid.uuid4())
            utils.mkdirs((LOGS_DIR / log_path).parent)
            log_file = LOGS_DIR / log_path
            fuzzers.append(FuzzProcess(corpus.version, b, t, worktree, log_path, log_file))

        # Build the fuzzers
        for f in fuzzers:
            f.build()
            if pause_exit_spot(pause_evt, resume_evt, exit_evt):
                return

        # Start the fuzzers
        atexit.register(kill_fuzzers, bucket, fuzzers)
        for f in fuzzers:
            f.start(corpus)

        # Wait until something happens
        started = time.monotonic()
        last_sync_file_upload = started
        while time.monotonic() < started + AUTO_REFRESH_INTERVAL_SECS:
            # Exit event happened?
            if exit_evt.is_set():
                kill_fuzzers(bucket, fuzzers)
                atexit.unregister(kill_fuzzers)
                return

            # Pause event happened?
            resume_evt.clear()
            if pause_evt.is_set():
                for f in fuzzers:
                    f.signal(signal.SIGSTOP)
                while not resume_evt.wait(timeout=1):
                    if exit_evt.is_set():
                        kill_fuzzers(bucket, fuzzers)
                        atexit.unregister(kill_fuzzers)
                        return
                pause_evt.clear()
                for f in fuzzers:
                    f.signal(signal.SIGCONT)

            # Fuzz crash found?
            for f in fuzzers:
                if f.poll():
                    bucket.blob(f"logs/{f.log_path}").upload_from_filename(LOGS_DIR / f.log_path)
                    f.report_crash(corpus, bucket)
                    fuzzers.remove(f)

                    # Start a new fuzzer
                    b = random_weighted(branches, 1)[0]
                    t = random_weighted(targets, 1)[0]
                    worktree = repo.worktree(b['name'])
                    log_path = pathlib.Path('fuzz') / date / t['crate'] / t['runner'] / str(uuid.uuid4())
                    utils.mkdirs((LOGS_DIR / log_path).parent)
                    log_file = LOGS_DIR / log_path
                    new_fuzzer = FuzzProcess(corpus.version, b, t, worktree, log_path, log_file)
                    new_fuzzer.build() # TODO: building the fuzzer should not block receiving the pause/resume messages
                    new_fuzzer.start(corpus)
                    fuzzers.append(new_fuzzer)

            # Regularly upload the sync log files
            if time.monotonic() > last_sync_file_upload + SYNC_LOG_UPLOAD_INTERVAL_SECS:
                last_sync_file_upload = time.monotonic()
                for l in sync_log_files:
                    bucket.blob(f"logs/{l}").upload_from_filename(LOGS_DIR / l)

    # TODO: Minimize the corpus
    # TODO: Rsync the corpus from gcs more frequently, not just once per fuzzer restart
    # TODO: Add corpus size gauge metric
    # TODO: Add coverage metrics (will need to parse logs?)
    # TODO: Add metrics about overhead (time to update corpus, to build fuzzer, etc.)

def listen_for_commands(pause_event: threading.Event, resume_event: threading.Event) -> None:
    """
    Spawn an HTTP server to remote control the fuzzers

    `/pause` and `/resume` respectively sigstop and sigcont the fuzzers
    """
    class HTTPHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
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

    with HTTPServer(("127.0.0.1", CMD_PORT), HTTPHandler) as httpd:
        print(f"Serving command server on port {CMD_PORT}")
        httpd.serve_forever()

# TODO: replace Any here with something more precise
THREAD_EXCEPTION: typing.Optional[typing.Any] = None
EXCEPTION_HAPPENED_IN_THREAD = threading.Event()

def main() -> None:
    """Main function"""
    # Make sure to cleanup upon ctrl-c or upon any exception in a thread
    def new_excepthook(args: typing.Any) -> None:
        global THREAD_EXCEPTION, EXCEPTION_HAPPENED_IN_THREAD
        THREAD_EXCEPTION = args
        EXCEPTION_HAPPENED_IN_THREAD.set()
    threading.excepthook = new_excepthook

    try:
        gcs = connect_to_gcs()

        # Start the metrics server
        prometheus_client.start_http_server(METRICS_PORT)

        # And listen for the commands that might come up
        pause_event = threading.Event()
        resume_event = threading.Event()
        threading.Thread(daemon = True, target = listen_for_commands, args = (pause_event, resume_event)).start()

        # Run until an exception forces us to stop
        print("Startup complete, will start running forever now")
        run_fuzzers(gcs, pause_event, resume_event, EXCEPTION_HAPPENED_IN_THREAD)

        # Finally, proxy the exception so it gets detected and acted upon by a human
        exc_info = THREAD_EXCEPTION
        if exc_info != None:
            raise exc_info.exc_value
    except KeyboardInterrupt:
        print('Got ^C, stopping')

if __name__ == '__main__':
    utils.setup_environ()
    os.environ['RUSTC_BOOTSTRAP'] = '1' # Nightly is needed by cargo-fuzz
    main()
