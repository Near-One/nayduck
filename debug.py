import multiprocessing
import subprocess
import time
import os
from dotenv import load_dotenv

def run_component(module):
    try:
        subprocess.run(['python3', '-m', module], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running {module}: {e}")

if __name__ == '__main__':
    load_dotenv()
    components = ['backend.backend', 'workers.builder', 'workers.worker']
    processes = []

    for component in components:
        p = multiprocessing.Process(target=run_component, args=(component,))
        p.start()
        processes.append(p)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()
