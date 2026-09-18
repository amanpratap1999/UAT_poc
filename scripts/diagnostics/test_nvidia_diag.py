import os
import time
import socket
import ssl
import httpx
from datetime import datetime
from dotenv import load_dotenv

def mask_key(key):
    if not key:
        return "None"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"

def print_section(title):
    print(f"\n{'='*50}\n{title}\n{'='*50}")

def test_dns():
    print_section("DNS Resolution")
    hostname = "integrate.api.nvidia.com"
    try:
        ip = socket.gethostbyname(hostname)
        print(f"[OK] DNS resolved {hostname} to {ip}")
    except Exception as e:
        print(f"[FAIL] DNS resolution failed: {type(e).__name__}: {str(e)}")

def test_tls():
    print_section("TLS Connectivity")
    hostname = "integrate.api.nvidia.com"
    port = 443
    context = ssl.create_default_context()
    try:
        start = time.time()
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                elapsed = time.time() - start
                print(f"[OK] TLS handshake successful in {elapsed:.3f}s")
                print(f"     Cipher: {ssock.cipher()}")
    except Exception as e:
        print(f"[FAIL] TLS connection failed: {type(e).__name__}: {str(e)}")

def test_models(api_key):
    print_section("GET /models")
    url = "https://integrate.api.nvidia.com/v1/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }
    try:
        start = time.time()
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=headers)
        elapsed = time.time() - start
        print(f"Status: {resp.status_code} (Elapsed: {elapsed:.3f}s)")
        
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            print(f"Total models returned: {len(models)}")
            target = "nvidia/nv-embedqa-e5-v5"
            found = [m for m in models if m.get("id") == target]
            if found:
                print(f"[OK] Model {target} is PRESENT. Details: {found[0]}")
            else:
                print(f"[WARN] Model {target} is NOT present in the models list.")
        else:
            print(f"Failed to fetch models: {resp.text}")
    except Exception as e:
        print(f"[FAIL] GET /models failed: {type(e).__name__}: {str(e)}")

def test_embedding(api_key, attempt_num):
    print_section(f"POST /embeddings (Attempt {attempt_num})")
    url = "https://integrate.api.nvidia.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "model": "nvidia/nv-embedqa-e5-v5",
        "input": ["ServiceNow incident management test"],
        "input_type": "query",
        "encoding_format": "float"
    }
    
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
    
    start = time.time()
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, headers=headers, json=payload)
        elapsed = time.time() - start
        print(f"Elapsed Time: {elapsed:.3f}s")
        print(f"HTTP Status Code: {resp.status_code}")
        print("Response Headers:")
        for k, v in resp.headers.items():
            print(f"  {k}: {v}")
        print("Response Body:")
        print(f"  {resp.text[:500]}..." if len(resp.text) > 500 else f"  {resp.text}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"Elapsed Time: {elapsed:.3f}s")
        print(f"Exception Type: {type(e).__name__}")
        print(f"Exception Message: {str(e)}")

def main():
    load_dotenv(dotenv_path=".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not found in .env")
        return
        
    print(f"Loaded API Key: {mask_key(api_key)}")
    
    test_dns()
    test_tls()
    test_models(api_key)
    
    # Send ONE request, then at most 3 additional separated by 10s
    for i in range(1, 5):
        test_embedding(api_key, i)
        if i < 4:
            print("\nWaiting 10 seconds before next request...")
            time.sleep(10)

if __name__ == "__main__":
    main()
