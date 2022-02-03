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
import uuid

from lib import config
from workers import utils

WORKDIR = utils.WORKDIR
REPO_URL = utils.REPO_URL
#WORKDIR = pathlib.Path('/tmp')
#REPO_URL = 'https://github.com/Ekleog/nearcore'
def connect_to_gcs():
    subprocess.run(['gcloud', 'auth', 'activate-service-account', '--key-file', GCS_CREDENTIALS_FILE], check=True)
    return google.cloud.storage.Client.from_service_account_json(GCS_CREDENTIALS_FILE)
    #return google.cloud.storage.Client(project = 'near-nayduck')

NUM_FUZZERS = os.cpu_count()
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

FUZZ_TIME = prometheus_client.Counter('fuzz_seconds', 'Time spent fuzzing', ['branch', 'crate', 'runner', 'flags'])
FUZZ_CRASHES = prometheus_client.Counter('fuzz_crashes', 'Number of times the fuzzer process crashed (not unique crashes)', ['branch', 'crate', 'runner', 'flags'])
FUZZ_ARTIFACTS_FOUND = prometheus_client.Counter('fuzz_artifacts_found', 'Number of artifacts found (should be number of unique crashes)', ['branch', 'crate', 'runner', 'flags'])
FUZZ_CORPUS_UPLOADED = prometheus_client.Counter('fuzz_corpus_uploaded', 'Number of elements uploaded to GCS corpus', ['branch', 'crate', 'runner', 'flags'])
FUZZ_CORPUS_DELETED = prometheus_client.Counter('fuzz_corpus_deleted', 'Number of elements deleted from GCS corpus', ['branch', 'crate', 'runner', 'flags'])

def update_repo(branch):
    if not REPO_DIR.exists():
        print(f"Doing initial clone of repository {REPO_DIR}")
        subprocess.check_call(['git', 'clone', REPO_URL, REPO_DIR_NAME], cwd=REPO_DIR_PARENT)

    print(f"Updating to latest commit of branch {branch}")
    subprocess.check_call(['git', 'fetch', REPO_URL, branch], cwd=REPO_DIR)
    subprocess.check_call(['git', 'checkout', 'FETCH_HEAD'], cwd=REPO_DIR)

def parse_config():
    return toml.load(REPO_DIR / 'nightly' / 'fuzz.toml')

FUZZERS = []

def report_artifact(gcs_path, branch, t):
    # todo: report on zulip with all the details
    FUZZ_ARTIFACTS_FOUND.labels(branch['name'], t['crate'], t['runner'], t['flags']).inc()

def artifact_deleted(path):
    raise RuntimeError(f"Deleted artifact {path}, which should have been prevented by ignore_deletions")

def run_fuzzer(branch, t, gcs, exit_event):
    # First, figure out the current corpus version
    bucket = gcs.get_bucket(GCS_BUCKET)
    corpus_vers = bucket.blob('current-corpus').download_as_text().strip()

    date = datetime.datetime.now().strftime('%Y-%m-%d')
    log_path = pathlib.Path(date) / t['crate'] / t['runner'] / str(uuid.uuid4())
    log_filename = WORKDIR / 'fuzz-logs' / log_path
    utils.mkdirs(log_filename.parent)
    with open(log_filename, 'a') as log_file:
        current_commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO_DIR, capture_output=True, check=True).stdout
        log_file.write(f"Corpus version: {corpus_vers}\n")
        log_file.write(f"Running on commit {current_commit}\n")
        log_file.flush()

        # Then, make sure the local corpus is the same as the gcs version
        reset_to_gcs(t['crate'] + '/corpus/' + t['runner'], REPO_DIR, corpus_vers, log_file)
        reset_to_gcs(t['crate'] + '/artifacts/' + t['runner'], REPO_DIR, corpus_vers, log_file)

        # Then, make sure we auto-upload any new discovery to gcs
        stop_inotify_event = threading.Event()
        auto_upload_to_gcs(
            stop_inotify_event,
            t['crate'] + '/corpus/' + t['runner'],
            REPO_DIR,
            corpus_vers,
            bucket,
            log_file,
            False,
            lambda path: FUZZ_CORPUS_UPLOADED.labels(branch['name'], t['crate'], t['runner'], t['flags']).inc(),
            lambda path: FUZZ_CORPUS_DELETED.labels(branch['name'], t['crate'], t['runner'], t['flags']).inc(),
        )
        auto_upload_to_gcs(
            stop_inotify_event,
            t['crate'] + '/artifacts/' + t['runner'],
            REPO_DIR,
            corpus_vers,
            bucket,
            log_file,
            True,
            lambda path: report_artifact(path, branch, t),
            artifact_deleted,
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
        fuzzer = {
            'proc': proc,
            'exit_event': exit_event,
            'crate': t['crate'],
            'runner': t['runner'],
        }
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

def start_a_fuzzer(branch, cfg, gcs):
    def run_it(cfg, gcs):
        exit_event = threading.Event()
        while not exit_event.is_set():
            target = random.choices(cfg['target'], [t['weight'] for t in cfg['target']])[0]
            run_fuzzer(branch, target, gcs, exit_event)
    threading.Thread(daemon = True, target = lambda: run_it(cfg, gcs)).start()

def signal_fuzzer(signal, proc):
    print(f"Killing fuzzer {proc.pid} with signal {signal}")
    os.killpg(os.getpgid(proc.pid), signal)

def signal_fuzzers(signal):
    for f in FUZZERS:
        signal_fuzzer(signal, f['proc'])

def stop_fuzzers():
    global FUZZERS
    signal_fuzzers(signal.SIGTERM)
    for f in FUZZERS:
        f['exit_event'].set()
    time.sleep(5)
    signal_fuzzers(signal.SIGKILL)
    FUZZERS = []

def listen_for_commands(gcs):
    class HTTPHandler(BaseHTTPRequestHandler):
        def do_GET(self):
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
            elif self.path == '/exit': # for development purposes only, production will be using systemctl stop
                signal_fuzzers(signal.SIGKILL)
                sys.exit(0)
            else:
                self.send_response(404)
            self.end_headers()

    with HTTPServer(("127.0.0.1", CMD_PORT), HTTPHandler) as httpd:
        print(f"Serving command server on port {CMD_PORT}")
        httpd.serve_forever()

def start_fuzzing(gcs):
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
    # TODO: Have one worktree per branch, this would allow both dependency build caching after a branch change and to run fuzzers on multiple branches from a single machine
    #       The only drawback would be fuzz corpuses wouldn't be shared across processes on the same host on different branches, which is probably not too bad

    # Start the fuzzers
    for _ in range(NUM_FUZZERS):
        start_a_fuzzer(branch, cfg, gcs)

def reset_to_gcs(path, local, remote, log_file):
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
        check = False, # TODO: currently two concurrent gsutil can step on each other's feet, it still loads a corpus but it ends up with an error
    )

def auto_upload_to_gcs(exit_event, path, local, remote, bucket, log_file, ignore_deletions, on_uploaded_item, on_deleted_item):
    print(f"Setting up inotify watch to auto-upload changes to {local / path} to GCS {remote + '/' + path + '/'}")
    log_file.write(f"Setting up inotify watch to auto-upload changes to {local / path} to GCS {remote + '/' + path + '/'}")
    log_file.flush()

    def uploader_thread(path, local, remote, bucket, exit_event, log_file):
        utils.mkdirs(local / path) # Otherwise inotify fails
        i = inotify.adapters.Inotify()
        i.add_watch((local / path).as_posix())
        while True:
            for event in i.event_gen(yield_nones = False):
                (_, event_types, _, filename) = event
                if 'IN_CLOSE_WRITE' in event_types:
                    log_file.write(f"Uploading new corpus item {local / path / filename} to GCS {remote + '/' + path + '/' + filename}")
                    log_file.flush()
                    try:
                        # TODO: batch uploads
                        bucket.blob(remote + '/' + path + '/' + filename).upload_from_filename(local / path / filename)
                        on_uploaded_item(remote + '/' + path + '/' + filename)
                    except FileNotFoundError:
                        pass # Ignore, as it'd mean the file has been deleted already
                if 'IN_DELETE' in event_types and not ignore_deletions:
                    log_file.write(f"Removing now-removed corpus item {local / path / filename} as GCS {remote + '/' + path + '/' + filename}")
                    log_file.flush()
                    try:
                        # TODO: batch
                        bucket.blob(remote + '/' + path + '/' + filename).delete()
                        on_deleted_item(remote + '/' + path + '/' + filename)
                    except google.api_core.exceptions.NotFound:
                        pass # Ignore, as it'd mean the file isn't there already
                if exit_event.is_set():
                    return
            if exit_event.is_set():
                return

    threading.Thread(daemon = True, target = lambda: uploader_thread(path, local, remote, bucket, exit_event, log_file)).start()

def stop_everything():
    stop_fuzzers()
    sys.exit(0)

def spawn_auto_refresher(gcs):
    while True:
        # Restart the fuzzers, thus getting latest commit and corpus, every 24 hours
        time.sleep(AUTO_REFRESH_INTERVAL_SECS)
        stop_fuzzers()
        start_fuzzing(gcs)

THREAD_EXCEPTION = None
EXCEPTION_HAPPENED_IN_THREAD = threading.Event()

def main():
    # Make sure to cleanup upon ctrl-c or upon any exception in a thread
    def new_excepthook(args):
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
        threading.Thread(daemon = True, target = lambda: listen_for_commands(gcs)).start()

        # Spawn the auto-refresher thread
        threading.Thread(daemon = True, target = lambda: spawn_auto_refresher(gcs)).start()

        # Finally, wait for a thread to get an exception and kill the whole process
        print("Startup complete, will run forever now")
        EXCEPTION_HAPPENED_IN_THREAD.wait()
        print(f"!! Got exception from thread in main thread {THREAD_EXCEPTION}")
        sys.excepthook(THREAD_EXCEPTION.exc_type, THREAD_EXCEPTION.exc_value, THREAD_EXCEPTION.exc_traceback)
        stop_fuzzers()
        raise THREAD_EXCEPTION.exc_value
    except KeyboardInterrupt:
        stop_everything()

if __name__ == '__main__':
    utils.setup_environ()
    os.environ['RUSTC_BOOTSTRAP'] = '1' # Nightly is needed by cargo-fuzz
    main()
