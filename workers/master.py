import os
import socket
import sys
import subprocess
import psutil
import shutil
from pathlib import Path, PurePath
import time
import requests
from db_master import MasterDB
from rc import bash, run
from multiprocessing import Process
from azure.storage.blob import BlobServiceClient, ContentSettings
from multiprocessing import Pool                                                



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

def cp(build_id, build_type):
        bash(f'''rm -rf {build_id}''')
        Path(f'{build_id}/target/{build_type}/').mkdir(parents=True, exist_ok=True)
        Path(f'{build_id}/target_expensive/{build_type}/deps').mkdir(parents=True, exist_ok=True)
        bld_cp = bash(f'''
            cp -r nearcore/target/{build_type}/neard {build_id}/target/{build_type}/neard
            cp -r nearcore/target/{build_type}/near {build_id}/target/{build_type}/near
            cp -r nearcore/target/{build_type}/genesis-populate {build_id}/target/{build_type}/genesis-populate
            cp -r nearcore/target/{build_type}/restaked {build_id}/target/{build_type}/restaked
        ''')
        '''find nearcore/target_expensive/{build_type}/deps/* -perm /a+x'''
        bld_cp = bash(f'''find nearcore/target_expensive/{build_type}/deps/* -perm /a+x''')
        exe_files = bld_cp.stdout.split('\n')
        fls = {}
        for f in exe_files:
            base = os.path.basename(f)
            test_name = base.split('-')[0]
            if test_name[0] in fls:
                if os.path.getctime(fls[test_name]) < os.path.getctime(f):
                    fls[test_name] = f
            else:
                fls[test_name] = f
        for fl in fls.values():
            bld_cp = bash(f'''cp {fl} {build_id}/target_expensive/{build_type}/deps/''')

        print(bld_cp)
            

def build(build_id, sha, outdir, features, is_release):
    if is_release:
        release = "--release"
    else:
        release = ""
    
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
            print("Build")
            bld = bash(f'''
                cd nearcore
                cargo build -j2 -p neard --features adversarial {features} {release}
                cargo build -j2 -p genesis-populate {features} {release}
                cargo build -j2 -p restaked {features} {release}
                cargo test -j2 --workspace --no-run --all-features --target-dir target_expensive
                cargo build -j2 -p neard --target-dir normal_target
            ''' , **kwargs, login=True)
            print(bld)
            if bld.returncode != 0:
                bash(f'''rm -rf nearcore''')
                return bld
            if is_release:
                cp(build_id, "release")
            else:
                cp(build_id, "debug")

            return bld

def cleanup_finished_runs(runs):
    for run in runs:
        bash(f'''
            rm -rf {run}
        ''')

def keep_pulling():
    ip_address = requests.get('https://checkip.amazonaws.com').text.strip()
    print(ip_address)
    server = MasterDB()
    server.handle_restart(ip_address)
  
    while True:
        time.sleep(5)
        try:
            server = MasterDB()
            #finished_runs = server.get_builds_with_finished_tests(ip_address)
            #cleanup_finished_runs(finished_runs)
            if not enough_space():
                print("Not enough space. Waiting for clean up.")
                bash(f''' rm -rf nearcore/target''')
                bash(f''' rm -rf nearcore/target_expensive''')
                continue
            new_build = server.get_new_build(ip_address)
            if not new_build:
                continue
            print(new_build)
            shutil.rmtree(os.path.abspath('output/'), ignore_errors=True)
            outdir = os.path.abspath('output/')
            Path(outdir).mkdir(parents=True, exist_ok=True)
            code = build(new_build['build_id'], new_build['sha'], outdir, new_build['features'], new_build['is_release'])
            server = MasterDB()
            if code.returncode == 0:
                status = 'BUILD DONE'
            else:
                status = 'BUILD FAILED'
            fl_err = os.path.join(outdir, "build_err")
            fl_out = os.path.join(outdir, "build_out")
            err = open(fl_err, 'r').read()
            out = open(fl_out, 'r').read()           
            server.update_run_status(new_build['build_id'], status, err, out)
        except Exception as e:
            print(e)

if __name__ == "__main__":
    keep_pulling()
        
