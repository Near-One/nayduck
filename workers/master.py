import os
import socket
import sys
import subprocess
import psutil
import shutil
from pathlib import Path, PurePath
import time
from db_master import DB
from rc import bash, run
from multiprocessing import Process
from azure.storage.blob import BlobServiceClient, ContentSettings


def enough_space(filename="/datadrive"):
    try:
        df = subprocess.Popen(["df", filename], stdout=subprocess.PIPE, universal_newlines=True)
        output = df.communicate()[0]
        pr = output.split()[11]
        n_pr = int(str(pr)[:-1])
        if n_pr >= 80:
            return False
        return True
    except:
        return False

def build(sha, run_id, run_type, outdir, remote, release):
    with open(str(outdir) + '/build_out', 'w') as fl_o:
        with open(str(outdir) + '/build_err', 'w') as fl_e:
            kwargs = {"stdout": fl_o, "stderr": fl_e}
            print("Checkout")
            bld = bash(f'''
                cd nearcore
                git checkout {sha}
            ''' , **kwargs, login=True)
            print(bld)
            if bld.returncode != 0:
                print("Clone")
                bld = bash(f'''
                    rm -rf nearcore
                    git clone https://github.com/nearprotocol/nearcore 
                    cd nearcore
                    git checkout {sha}
                ''' , **kwargs, login=True)
                print(bld)
                if bld.returncode != 0:
                    return bld
            if 'mocknet' in run_type:
                return bld
            if remote:
                print("Build for remote.")
                bld = bash(f'''
                    cd nearcore
                    cargo build -j2 -p neard --features adversarial
                ''' , **kwargs, login=True)
                return bld
            print("Build")
            bld = bash(f'''
                cd nearcore
                cargo build -j2 -p neard --features adversarial {release}
                cargo build -j2 -p genesis-populate {release}
                cargo build -j2 -p restaked {release}
            ''' , **kwargs, login=True)
            print(bld)
            if bld.returncode != 0:
                bash(f'''rm -rf nearcore''')
                return bld
            bld = run(f'''cd nearcore && cargo test -j2 --workspace --no-run --all-features --target-dir target_expensive''', **kwargs)
            if bld.returncode != 0:
                bash(f'''rm -rf nearcore''')
                return bld
            bld = run(f'''cd nearcore && cargo build -j2 -p neard --target-dir normal_target''', **kwargs)
            if bld.returncode != 0:
                bash(f'''rm -rf nearcore''')
                return bld
            bld = bash(f'''cp -r nearcore {run_id}''')
            return bld

def cleanup_finished_runs(runs):
    for run in runs:
        bash(f'''
            rm -rf {run}
        ''')

def keep_pulling():
    hostname = socket.gethostname()
    ip_address = socket.gethostbyname(hostname)
    while True:
        try:
            server = DB()
            finished_runs = server.get_all_finished_runs(ip_address)
            cleanup_finished_runs(finished_runs)
            if not enough_space():
                print("Not enough space. Waiting for clean up.")
            time.sleep(5)
            run = server.get_new_run(ip_address)
            print(run)
            if not run:
                continue
            shutil.rmtree(os.path.abspath('output/'), ignore_errors=True)
            outdir = os.path.abspath('output/')
            Path(outdir).mkdir(parents=True, exist_ok=True)
            code = build(run['sha'], run['id'], run['type'], outdir, remote, release)
            server = DB()
            if code.returncode == 0:
                server.update_run_status('BUILD DONE', run['id'])
            else:
                server.update_run_status('BUILD FAILED', run['id'])
            fl_err = os.path.join(outdir, "build_err")
            fl_out = os.path.join(outdir, "build_out")
            err = open(fl_err, 'r').read()
            out = open(fl_out, 'r').read()
            server.save_build_logs(run['id'], err, out)
        except Exception as e:
            print(e)

if __name__ == "__main__":
    server = DB()
    server.handle_restart(socket.gethostbyname(socket.gethostname()))
    keep_pulling()
        
