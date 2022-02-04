import datetime
import google.cloud.storage
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

WORKDIR = utils.WORKDIR
REPO_URL = utils.REPO_URL
#WORKDIR = pathlib.Path('/tmp')
#REPO_URL = 'https://github.com/Ekleog/nearcore'
def connect_to_gcs() -> google.cloud.storage.Client:
    """Setup the environment to have gsutils work, and return a connection to GCS"""
    subprocess.run(
        ['gcloud', 'auth', 'activate-service-account', '--key-file', GCS_CREDENTIALS_FILE],
        check = True,
    )
    return google.cloud.storage.Client.from_service_account_json(str(GCS_CREDENTIALS_FILE))
    #return google.cloud.storage.Client(project = 'near-nayduck')

NUM_FUZZERS = typing.cast(int, os.cpu_count())
#NUM_FUZZERS = 1

AUTO_REFRESH_INTERVAL_SECS = 24 * 3600
#AUTO_REFRESH_INTERVAL_SECS = 300

CMD_PORT = 7055
METRICS_PORT = 5507

REPO_DIR_PARENT = WORKDIR
REPO_DIR_NAME = 'fuzzed-nearcore'
REPO_DIR = REPO_DIR_PARENT / REPO_DIR_NAME

GCS_CREDENTIALS_FILE = config.CONFIG_DIR / 'credentials.json'
GCS_BUCKET = 'fuzzer'

# pylint: disable=line-too-long
FUZZ_TIME = prometheus_client.Counter('fuzz_seconds', 'Time spent fuzzing', ['branch', 'crate', 'runner', 'flags'])
FUZZ_CRASHES = prometheus_client.Counter('fuzz_crashes', 'Number of times the fuzzer process crashed (not unique crashes)', ['branch', 'crate', 'runner', 'flags'])
FUZZ_ARTIFACTS_FOUND = prometheus_client.Counter('fuzz_artifacts_found', 'Number of artifacts found (should be number of unique crashes)', ['branch', 'crate', 'runner', 'flags'])
FUZZ_CORPUS_UPLOADED = prometheus_client.Counter('fuzz_corpus_uploaded', 'Number of elements uploaded to GCS corpus', ['branch', 'crate', 'runner', 'flags'])
FUZZ_CORPUS_DELETED = prometheus_client.Counter('fuzz_corpus_deleted', 'Number of elements deleted from GCS corpus', ['branch', 'crate', 'runner', 'flags'])
# pylint: enable=line-too-long

class FuzzProcess:
    def __init__(
        self,
        crate: str,
        runner: str,
        proc: subprocess.Popen,
        exit_event: threading.Event,
    ):
        """Create a FuzzProcess object"""
        self.crate = crate
        self.runner = runner
        self.proc = proc
        self.exit_event = exit_event

def update_repo(branch: str) -> None:
    """Update the repository at REPO_DIR to the tip of github's branch `branch`"""
    if not REPO_DIR.exists():
        print(f"Doing initial clone of repository {REPO_DIR}")
        subprocess.check_call(['git', 'clone', REPO_URL, REPO_DIR_NAME], cwd=REPO_DIR_PARENT)

    print(f"Updating to latest commit of branch {branch}")
    subprocess.check_call(['git', 'fetch', REPO_URL, branch], cwd=REPO_DIR)
    subprocess.check_call(['git', 'checkout', 'FETCH_HEAD'], cwd=REPO_DIR)

# TODO: make these types more precise? But then everything comes from toml.load so...
ConfigType = typing.Any
BranchType = typing.Any
TargetType = typing.Any

def parse_config() -> ConfigType:
    """Parse the configuration from the repository at REPO_DIR"""
    # TODO: rather than checking out master before parsing the config, we could use
    # git fetch <repo>; git show FETCH_HEAD:nightly/fuzz.toml to get the file contents
    return toml.load(REPO_DIR / 'nightly' / 'fuzz.toml')

FUZZERS = []

def report_artifact(gcs_path: str, branch: BranchType, t: TargetType) -> None:
    """Callback called when a new artifact is found by a fuzzer"""
    # todo: report on zulip with all the details
    FUZZ_ARTIFACTS_FOUND.labels(branch['name'], t['crate'], t['runner'], t['flags']).inc()

def artifact_deleted(path: str) -> None:
    """Callback called when an artifact is deleted. This would be a programming error."""
    raise RuntimeError(f"Deleted artifact {path}, this is a programming error")

def run_fuzzer(
    branch: BranchType,
    t: TargetType,
    gcs: google.cloud.storage.Client,
    exit_event: threading.Event,
) -> None:
    """
    Run a fuzzer.

    `REPO_DIR` is assumed to already be checked out at `branch`.
    `t` is a target configuration from `fuzz.toml`.
    `gcs` is a handle to a connection to GCS with access to the proper bucket.
    `exit_event` being set will cleanly kill the fuzzer.
    """

    # First, figure out the current corpus version
    bucket = gcs.get_bucket(GCS_BUCKET)
    corpus_vers = bucket.blob('current-corpus').download_as_text().strip()

    date = datetime.datetime.now().strftime('%Y-%m-%d')
    log_path = pathlib.Path(date) / t['crate'] / t['runner'] / str(uuid.uuid4())
    log_filename = WORKDIR / 'fuzz-logs' / log_path
    utils.mkdirs(log_filename.parent)
    with open(log_filename, 'a') as log_file:
        current_commit = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd = REPO_DIR,
            capture_output = True,
            check = True,
        ).stdout
        log_file.write(f"Corpus version: {corpus_vers}\n")
        log_file.write(f"Running on commit {current_commit}\n")
        log_file.flush()

        # Then, make sure the local corpus is the same as the gcs version
        reset_to_gcs(t['crate'] + '/corpus/' + t['runner'], REPO_DIR, corpus_vers, log_file)
        reset_to_gcs(t['crate'] + '/artifacts/' + t['runner'], REPO_DIR, corpus_vers, log_file)

        # Then, make sure we auto-upload any new discovery to gcs
        stop_inotify_event = threading.Event()
        auto_upload_to_gcs(
            exit_event = stop_inotify_event,
            path = t['crate'] + '/corpus/' + t['runner'],
            local = REPO_DIR,
            remote = corpus_vers,
            bucket = bucket,
            log_file = log_file,
            ignore_deletions = False,
            on_uploaded_item = lambda path:
                FUZZ_CORPUS_UPLOADED.labels(branch['name'], t['crate'], t['runner'], t['flags'])
                    .inc(),
            on_deleted_item = lambda path:
                FUZZ_CORPUS_DELETED.labels(branch['name'], t['crate'], t['runner'], t['flags'])
                    .inc(),
        )
        auto_upload_to_gcs(
            exit_event = stop_inotify_event,
            path = t['crate'] + '/artifacts/' + t['runner'],
            local = REPO_DIR,
            remote = corpus_vers,
            bucket = bucket,
            log_file = log_file,
            ignore_deletions = True,
            on_uploaded_item = lambda path: report_artifact(path, branch, t),
            on_deleted_item = artifact_deleted,
        )

        # Prepare the fuzz time metric
        fuzz_time = FUZZ_TIME.labels(branch['name'], t['crate'], t['runner'], t['flags'])
        last_time = time.monotonic()

        # Finally, spin up the fuzzer itself
        proc = subprocess.Popen(
            ['cargo', 'fuzz', 'run', t['runner'], '--'] + t['flags'],
            cwd = REPO_DIR / t['crate'],
            start_new_session = True,
            stdout = log_file,
            stderr = subprocess.STDOUT,
        )
        fuzzer = FuzzProcess(t['crate'], t['runner'], proc, exit_event)
        FUZZERS.append(fuzzer)

        # Wait for the fuzzer to complete (ie. either crash or requested to stop)
        while proc.poll() == None and not exit_event.is_set():
            time.sleep(0.5)
            new_time = time.monotonic()
            fuzz_time.inc(new_time - last_time)
            last_time = new_time
        print(f"Fuzzer running {t} has stopped")

    # Remove this fuzzer from the fuzzer list
    FUZZERS.remove(fuzzer)

    # If a crash was found, report
    if proc.poll() != None:
        FUZZ_CRASHES.labels(branch['name'], t['crate'], t['runner'], t['flags']).inc()

    # Stop the inotify threads and the process, and make sure to wait until they are stopped
    stop_inotify_event.set()
    if proc.poll() == None:
        signal_fuzzer(signal.SIGTERM, proc)
    time.sleep(5)
    if proc.poll() == None:
        signal_fuzzer(signal.SIGKILL, proc)

    # Finally, upload the log files
    bucket.blob(f'logs/{log_path}').upload_from_filename(log_filename)

def start_a_fuzzer(branch: str, cfg: ConfigType, gcs: google.cloud.storage.Client) -> None:
    """Start a fuzzer that will randomly run one of the fuzz targets from `cfg` forever"""
    def run_it(cfg: ConfigType, gcs: google.cloud.storage.Client) -> None:
        exit_event = threading.Event()
        while not exit_event.is_set():
            target = random.choices(cfg['target'], [t['weight'] for t in cfg['target']])[0]
            run_fuzzer(branch, target, gcs, exit_event)
    threading.Thread(daemon = True, target = run_it, args = (cfg, gcs)).start()

def signal_fuzzer(signal: int, proc: subprocess.Popen) -> None:
    """
    Kill fuzzer `proc` (with all its process group as a fuzzer can spawn sub-processes) with
    `signal`
    """

    print(f"Killing fuzzer {proc.pid} with signal {signal}")
    os.killpg(os.getpgid(proc.pid), signal)

def signal_fuzzers(signal: int) -> None:
    """
    Kill all fuzzers (with all their process group as a fuzzer can spawn sub-processes) with
    `signal`
    """

    for f in FUZZERS:
        signal_fuzzer(signal, f.proc)

def stop_fuzzers() -> None:
    """Stop all the fuzzers, cleaning everything up"""
    global FUZZERS
    signal_fuzzers(signal.SIGTERM)
    for f in FUZZERS:
        f.exit_event.set()
    time.sleep(5)
    signal_fuzzers(signal.SIGKILL)
    FUZZERS = []

def listen_for_commands(gcs: google.cloud.storage.Client) -> None:
    """
    Spawn an HTTP server to remote control the fuzzers

    `/pause` and `/resume` respectively sigstop and sigcont the fuzzers
    `/restart` forces a fuzzer restar
    `/exit` stops the whole process immediately (without cleanup)
    """
    class HTTPHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            global FUZZERS
            if self.path == '/pause':
                signal_fuzzers(signal.SIGSTOP)
                self.send_response(200)
            elif self.path == '/resume':
                signal_fuzzers(signal.SIGCONT)
                self.send_response(200)
            elif self.path == '/restart':
                stop_fuzzers()
                start_fuzzing(gcs)
                self.send_response(200)
            elif self.path == '/exit':
                # for development purposes only, production will be using systemctl stop
                signal_fuzzers(signal.SIGKILL)
                sys.exit(0)
            else:
                self.send_response(404)
            self.end_headers()

    with HTTPServer(("127.0.0.1", CMD_PORT), HTTPHandler) as httpd:
        print(f"Serving command server on port {CMD_PORT}")
        httpd.serve_forever()

def start_fuzzing(gcs: google.cloud.storage.Client) -> None:
    """Start the fuzzing, taking the configuration from latest github repo master"""
    update_repo('master')
    cfg = parse_config()
    print(f"Parsed configuration: {cfg}")

    # Checkout random branch
    branch = random.choices(cfg['branch'], [b['weight'] for b in cfg['branch']])[0]
    update_repo(branch['name'])

    # TODO: Minimize the corpus
    # TODO: Rsync the corpus from gcs more frequently, not just once per fuzzer restart
    # TODO: Add corpus size gauge metric
    # TODO: Add coverage metrics (will need to parse logs?)
    # TODO: Add metrics about overhead (time to update corpus, to build fuzzer, etc.)
    # TODO: Have one worktree per branch, this would allow both dependency build caching
    #       after a branch change and to run fuzzers on multiple branches from a single machine
    #       The only drawback would be fuzz corpuses wouldn't be shared across processes on the
    #       same host on different branches, which is probably not too bad

    # Start the fuzzers
    for _ in range(NUM_FUZZERS):
        start_a_fuzzer(branch, cfg, gcs)

def reset_to_gcs(path: str, local: pathlib.Path, remote: str, log_file: typing.IO[str]) -> None:
    """Reset path `local/path` to the contents it has on `remote/path`, logging to `log_file`"""
    print(f"Resetting path {local / path} to GCS {remote}/{path}/")
    log_file.write(f"Resetting path {local / path} to GCS {remote}/{path}/\n")
    log_file.flush()
    #utils.rmdirs(local / path)
    utils.mkdirs(local / path)
    #for blob in bucket.list_blobs(prefix = remote + '/' + path + '/'):
    #    unprefixed_path = blob.name[len(remote) + 1:]
    #    print(f"Downloading blob {blob.name} to {local / unprefixed_path}")
    #    blob.download_to_filename(local / unprefixed_path)
    subprocess.run(
        ['gsutil', '-m', 'rsync', '-d', f"gs://{GCS_BUCKET}/{remote}/{path}/", local / path],
        stdout = log_file,
        stderr = subprocess.STDOUT,
        check = False,
    )
    # TODO: currently two concurrent gsutil can step on each other's feet,
    # it still loads a corpus but it ends up with an error, hence the check=False

def uploader_thread(
    path: str,
    local: pathlib.Path,
    remote: str,
    bucket: google.cloud.storage.Bucket,
    exit_event: threading.Event,
    log_file: typing.IO[str],
) -> None:
    utils.mkdirs(local / path) # Otherwise inotify fails
    i = inotify.adapters.Inotify()
    i.add_watch((local / path).as_posix())
    while True:
        # at most every 5 seconds check for exit_event
        for event in i.event_gen(yield_nones = False, timeout_s = 5):
            (_, event_types, _, filename) = event
            local_filename = local / path / filename
            remote_filename = f'{remote}/{path}/{filename}'
            if 'IN_CLOSE_WRITE' in event_types:
                log_file.write(
                    f"Uploading new corpus item {local_filename} to GCS {remote_filename}\n"
                )
                log_file.flush()
                try:
                    # TODO: batch uploads
                    bucket.blob(remote_filename).upload_from_filename(local_filename)
                    on_uploaded_item(remote_filename)
                except FileNotFoundError:
                    pass # Ignore, as it'd mean the file has been deleted already
            if 'IN_DELETE' in event_types and not ignore_deletions:
                log_file.write(
                    f"Removing now-removed corpus item {local_filename} as GCS {remote_filename}\n"
                )
                log_file.flush()
                try:
                    # TODO: batch
                    bucket.blob(remote_filename).delete()
                    on_deleted_item(remote_filename)
                except google.api_core.exceptions.NotFound:
                    pass # Ignore, as it'd mean the file isn't there already
            if exit_event.is_set():
                return
        if exit_event.is_set():
            return

def auto_upload_to_gcs(
    *,
    exit_event: threading.Event,
    path: pathlib.Path,
    local: pathlib.Path,
    remote: str,
    bucket: str,
    log_file: typing.IO[str],
    ignore_deletions: bool,
    # Without Any here mypy doesn't let us use lambdas. The result is ignored anyway.
    on_uploaded_item: typing.Callable[[str], typing.Any],
    on_deleted_item: typing.Callable[[str], typing.Any],
) -> None:
    """
    Setup an inotify thread that will automatically upload changes to GCS

    `exit_event` will stop the thread when set
    The contents of `local/path` will be propagated to `remote/path` in `bucket`
    Logs will be sent to `log_file`.
    If `ignore_deletions` is set, deletions will not be propagated.
    Upon successful uploading of deletion or an item, resp. `on_uploaded_item` and
    `on_deleted_item` will be called.
    """
    # pylint: disable=line-too-long
    print(f"Setting up inotify watch to auto-upload changes to {local / path} to GCS {remote}/{path}/")
    log_file.write(f"Setting up inotify watch to auto-upload changes to {local / path} to GCS {remote}/{path}/\n")
    log_file.flush()
    # pylint: enable=line-too-long

    threading.Thread(
        daemon = True,
        target = uploader_thread,
        args = (path, local, remote, bucket, exit_event, log_file),
    ).start()

# TODO: replace Any here with something more precise
THREAD_EXCEPTION: typing.Optional[typing.Any] = None
EXCEPTION_HAPPENED_IN_THREAD = threading.Event()

def main() -> None:
    """Main function"""
    # Make sure to cleanup upon ctrl-c or upon any exception in a thread
    def new_excepthook(args: typing.Any) -> None:
        global THREAD_EXCEPTION, EXCEPTION_HAPPENED_IN_THREAD
        print(f"!! Caught exception in thread: {args}")
        THREAD_EXCEPTION = args
        EXCEPTION_HAPPENED_IN_THREAD.set()
    threading.excepthook = new_excepthook

    try:
        # Start the system
        gcs = connect_to_gcs()
        start_fuzzing(gcs)

        # Start the metrics server
        prometheus_client.start_http_server(METRICS_PORT)

        # And listen for the commands that might come up
        threading.Thread(daemon = True, target = listen_for_commands, args = (gcs,)).start()

        # Run until an exception forces us to stop
        print("Startup complete, will run forever now")
        while not EXCEPTION_HAPPENED_IN_THREAD.wait(timeout=AUTO_REFRESH_INTERVAL_SECS):
            # Restart the fuzzers, thus getting latest commit and corpus, at every refresh interval
            stop_fuzzers()
            start_fuzzing(gcs)

        # Finally, proxy the exception so it gets detected and acted upon by a human
        exc_info = typing.cast(typing.Any, THREAD_EXCEPTION) # TODO: remove Any here
        print(f"!! Got exception from thread in main thread {exc_info}")
        sys.excepthook(exc_info.exc_type, exc_info.exc_value, exc_info.exc_traceback)
        raise exc_info.exc_value
    except KeyboardInterrupt:
        print('Got ^C, stopping')
    finally:
        stop_fuzzers()

if __name__ == '__main__':
    utils.setup_environ()
    os.environ['RUSTC_BOOTSTRAP'] = '1' # Nightly is needed by cargo-fuzz
    main()
