import urllib.request
import time

try:
    start = time.time()
    req = urllib.request.Request('http://127.0.0.1:8000/api/system/status')
    with urllib.request.urlopen(req, timeout=5) as response:
        print(f"Status Code: {response.getcode()}")
        print(f"Response: {response.read().decode('utf-8')}")
        print(f"Time: {time.time() - start:.2f}s")
except Exception as e:
    print(f"Error: {e}")
