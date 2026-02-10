import requests

url = "http://localhost:3102/loki/api/v1/query_range"
params = {
    "query": '{namespace="demo"}',
    "limit": "5"
}

try:
    response = requests.get(url, params=params, timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Headers: {response.headers}")
    if response.status_code == 200:
        data = response.json()
        print(f"Success: {data.get('status')}")
        print(f"Results: {len(data.get('data', {}).get('result', []))}")
    else:
        print(f"Error: {response.text[:200]}")
except Exception as e:
    print(f"Exception: {e}")
