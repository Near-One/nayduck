
# NayDuck
Test Infra for Near Protocol binary https://github.com/near/nearcore

# Raw notes on local setup

Could be helpful for debugging. Still some manual hacks are needed.
TODO: improve setup using scripts from `automation/` and `systemd/` folders.

nayduck/debug.py
```
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
```

nearcore/run.py

```
import requests
import json

url = "http://localhost:5005/api/run/new"  # Adjust this URL if your backend is running on a different host/port

payload = {
    "branch": "master", # Adjust this if you're using a different branch
    "sha": "bf93c6a9303e445b1524f534735fd120c615aefe", # Select a commit hash
    "title": "Run slow_chunk.py test", # Select a title
    "tests": ["pytest sanity/slow_chunk.py"], # Test command
    "requester": "Manual"
}

headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, data=json.dumps(payload), headers=headers)

if response.status_code == 200:
    result = response.json()
    if result["code"] == 0:
        run_id = result["response"].split("/")[-1]
        print(f"Test run created with ID: {run_id}")
    else:
        print(f"Failed to create test run. Error: {result['response']}")
else:
    print(f"Failed to create test run. Status code: {response.status_code}")
    print(response.text)

```

~/.nayduck/database.json

```
{
    "drivername": "postgresql",
    "host": "localhost",
    "port": 5432,
    "database": "nayduck",
    "username": "nayduck",
    "password": "nayduck"
}
```

~/.nayduck/blob-store.json

```
{
    "service": "Local",
    "path": "/tmp/nayduck-blobs"
}
```

~/.nayduck/auth.json

Everything is fake I guess.
```
{
    "key": "n/KobMworbirzyytiBtDw96NxHnEA5TAoFBfl7Pj1Sg=",
    "github-client-id": "dummy_client_id",
    "github-client-secret": "dummy_client_secret",
    "allowed_users": ["nayduck"]
}
```

Commands

```
gcloud compute ssh --project nearone-nayduck nayduck@builder01

sudo apt install libpq-dev python3-dev postgresql-client-common postgresql-client postgresql-contrib

git clone https://github.com/Near-One/nayduck
cd nayduck
pip3 install -r requirements.txt 
pip install psycopg2-binary
mkdir /datadrive
chown nayduck:nayduck /datadrive

sudo systemctl start postgresql
PGPASSWORD=nayduck createdb -h localhost -p 5432 -U nayduck nayduck
psql -d nayduck -f lib/schema.sql

cd frontend
npm install
npm run build
```

* Replace `scp_build` with local recursive copy
* Run `nayduck/debug.py` in background
* Run `nearcore/run.py` to launch test
* See result in http://localhost:5005/.