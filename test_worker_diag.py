import os
import sys
import time
import socket
import ssl
import httpx
import asyncio
from datetime import datetime
from openai import AsyncOpenAI

def mask_key(key):
    if not key: return "None"
    if len(key) <= 8: return "****"
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

def test_httpx_embedding(api_key):
    print_section("STEP 1: Worker httpx POST /embeddings")
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
        print("Response Body Summary:")
        if resp.status_code == 200:
            data = resp.json()
            if "data" in data and len(data["data"]) > 0:
                emb = data["data"][0].get("embedding", [])
                print(f"  Returned valid vector of length {len(emb)}. First 3: {emb[:3]}")
            else:
                print(f"  {resp.text[:200]}...")
        else:
            print(f"  {resp.text[:500]}...")
        return resp.status_code == 200
    except Exception as e:
        elapsed = time.time() - start
        print(f"Elapsed Time: {elapsed:.3f}s")
        print(f"Exception Type: {type(e).__name__}")
        print(f"Exception Message: {str(e)}")
        return False

async def test_async_openai(api_key):
    print_section("STEP 2: Worker AsyncOpenAI POST /embeddings")
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://integrate.api.nvidia.com/v1",
        max_retries=0,
        timeout=15.0
    )
    
    start = time.time()
    try:
        resp = await client.embeddings.create(
            model="nvidia/nv-embedqa-e5-v5",
            input=["ServiceNow incident management test"]
        )
        elapsed = time.time() - start
        print(f"Elapsed Time: {elapsed:.3f}s")
        print(f"Successfully received response. Vector length: {len(resp.data[0].embedding)}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"Elapsed Time: {elapsed:.3f}s")
        print(f"Exception Class: {type(e).__name__}")
        print(f"Exception Message: {str(e)}")
        
        current_exc = e
        chain_idx = 1
        while current_exc.__cause__ or current_exc.__context__:
            cause = current_exc.__cause__ or current_exc.__context__
            print(f"  [Cause {chain_idx}] {type(cause).__name__}: {str(cause)}")
            current_exc = cause
            chain_idx += 1
        
        print("\nTesting closing behavior...")
        try:
            await client.close()
            print("Successfully closed client.")
        except Exception as close_err:
            print(f"Error during close: {str(close_err)}")

def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not found in environment")
        return
        
    print(f"Loaded API Key: {mask_key(api_key)}")
    
    test_dns()
    test_tls()
    
    success = test_httpx_embedding(api_key)
    
    if success:
        print("\nhttpx test succeeded. Proceeding to AsyncOpenAI test...")
        asyncio.run(test_async_openai(api_key))
    else:
        print("\nhttpx test failed. Skipping AsyncOpenAI test.")

if __name__ == "__main__":
    main()
