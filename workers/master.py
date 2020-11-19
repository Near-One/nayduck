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
from multiprocessing import Process, Queue, Pool
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

def cp_exe(cmd):
    b = bash(cmd)
    print(b)

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
        bld_cp = bash(f'''find nearcore/target_expensive/{build_type}/deps/* -perm /a+x''')
        print(bld_cp)
        exe_files = bld_cp.stdout.split('\n')
        fls = {}
        for f in exe_files:
            if not f:
                continue
            base = os.path.basename(f)
            if "." in base:
                continue
            test_name = base.split('-')[0]
            if test_name in fls:
                if os.path.getctime(fls[test_name]) < os.path.getctime(f):
                    fls[test_name] = f
            else:
                fls[test_name] = f
        
        cmds = []
        for f in fls.values():
            cmds.append(f'cp {f} {build_id}/target_expensive/{build_type}/deps/')
        p = Pool(10)
        p.map(cp_exe, cmds)
        p.close()
            
def build_target(queue, features, release):
    print("Build target")
    bld = bash(f'''
            cd nearcore
            cargo build -j2 -p neard -p genesis-populate -p restaked --features adversarial {features} {release}
    ''', login=True)
    queue.put(bld)
            

def build_target_expensive(queue):
    print("Build expensive")
    bld = bash(f'''
            cd nearcore
            cargo test -j2 --workspace --no-run --all-features --target-dir target_expensive
            cargo test -j2 --no-run --all-features --target-dir target_expensive --package near-client --package nearcore --package near-chunks --package neard --package near-chain
    ''' , login=True)
    queue.put(bld)
            
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
                    return bld.returncode
            print("Build")
            queue = Queue()
            p1 = Process(target=build_target, args=(queue, features, release))
            p1.start()
            p2 = Process(target=build_target_expensive, args=(queue,))
            p2.start()
            p1.join()
            bld1 = queue.get()
            p2.join()
            bld2 = queue.get()
            fl_e.write(bld1.stderr)
            fl_e.write(bld2.stderr)
            fl_o.write(bld1.stdout)
            fl_o.write(bld2.stdout)
            if bld1.returncode != 0 or bld2.returncode != 0:
                bash(f'''rm -rf nearcore''')
                return bld1.returncode if bld1.returncode != 0 else bld2.returncode
            if is_release:
                cp(build_id, "release")
            else:
                cp(build_id, "debug")

            return bld.returncode

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
            finished_runs = server.get_builds_with_finished_tests(ip_address)
            cleanup_finished_runs(finished_runs)
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
            if code == 0:
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
        
