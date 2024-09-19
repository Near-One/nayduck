import requests
import json

url = "http://localhost:3000/api/run/new"  # Adjust this URL if your backend is running on a different host/port

payload = {
    "branch": "master",  # Adjust this if you're using a different branch
    "sha": "HEAD",  # This will use the latest commit on the branch
    "title": "Run slow_chunk.py test",
    "tests": ["pytest sanity/rpc_hash.py"],
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
