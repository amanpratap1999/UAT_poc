#!/usr/bin/env python3
"""
CI/CD integration script to trigger a Phase 7 agent run.
This script demonstrates how an external system (e.g. GitHub Actions, Jenkins)
authenticates with the multi-tenant API, queues a run, and polls for completion.
"""

import sys
import time
import requests

API_BASE = "http://localhost:8000/api/v1"

def main():
    print("--- Starting CI/CD Run Trigger ---")
    
    # 1. Authenticate to get a token (Using the default fallback admin)
    print("Authenticating...")
    auth_resp = requests.post(f"{API_BASE}/token", data={
        "username": "admin",
        "password": "admin"
    })
    
    if auth_resp.status_code != 200:
        print(f"Auth failed: {auth_resp.text}")
        sys.exit(1)
        
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Trigger the run
    print("Triggering run...")
    run_resp = requests.post(f"{API_BASE}/runs", json={
        "goal": "Verify Incident Management Lifecycle from CI"
    }, headers=headers)
    
    if run_resp.status_code != 200:
        print(f"Run trigger failed: {run_resp.text}")
        sys.exit(1)
        
    run_id = run_resp.json()["session_id"]
    print(f"Run queued successfully. Run ID: {run_id}")
    
    # 3. Poll for completion
    print("Polling for completion...")
    while True:
        status_resp = requests.get(f"{API_BASE}/runs/{run_id}", headers=headers)
        if status_resp.status_code != 200:
            print(f"Failed to fetch status: {status_resp.text}")
            sys.exit(1)
            
        data = status_resp.json()
        status = data["status"]
        
        print(f"Current status: {status}")
        
        if status in ["completed", "failed", "blocked", "cancelled"]:
            print(f"Run finished with status: {status}")
            print(f"Defect count: {data['defect_count']}")
            print(f"Duration: {data['duration_seconds']}s")
            
            if status == "completed":
                print("CI/CD pipeline passed!")
                sys.exit(0)
            else:
                print("CI/CD pipeline failed due to test failure or error.")
                sys.exit(1)
                
        time.sleep(10)

if __name__ == "__main__":
    main()
