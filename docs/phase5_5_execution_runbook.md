# Phase 5.5 Execution Runbook

## Objective
Execute the `scripts/run_phase5_5_validation.py` harness against a **real ServiceNow Personal Developer Instance (PDI)** without any mocks.

## Strict Execution Rules
- **No Production Code Changes:** Do not modify the agent's code during execution to force a pass. 
- **No Mocking:** If a system is unavailable, the gate fails or is marked `BLOCKED`.
- **Collect Raw Evidence:** Do not artificially retry or alter the environment to hide a failure. Failures are valuable data points.
- **Scoring Rubric:**
  - 🟢 **PASS**: Real environment + Real execution + Real evidence + Expected behavior.
  - 🟡 **CONDITIONAL**: Code path works, but real-world evidence is unavailable.
  - 🔴 **FAIL**: Real execution occurs and the expected behavior doesn't happen.
  - ⚫ **BLOCKED**: Required infrastructure for the experiment isn't available (e.g. no UI-TARS).

## Step-by-Step Instructions (For the User)

### 1. Provision the Environment
Ensure you have access to a real ServiceNow PDI.
Identify your UI-TARS endpoint (if available) and PostgreSQL connection (if available).

### 2. Configure Credentials Locally
In your PowerShell terminal, configure the environment variables. **Do not paste these into the AI chat:**

```powershell
$env:SERVICENOW_URL="https://devXXXXX.service-now.com"
$env:SERVICENOW_USERNAME="admin"
$env:SERVICENOW_PASSWORD="YOUR_PASSWORD"
$env:OPENAI_API_KEY="YOUR_OPENAI_KEY"
$env:UI_TARS_ENDPOINT="YOUR_ENDPOINT_URL"
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/servicenow_qa" # Optional
```

Verify they are loaded without printing secrets:
```powershell
if ($env:SERVICENOW_URL) { "SERVICENOW_URL configured" }
if ($env:OPENAI_API_KEY) { "OPENAI_API_KEY configured" }
```

### 3. Run the Validation Harness
Execute the harness exactly as implemented:
```powershell
python scripts/run_phase5_5_validation.py
```

### 4. Provide the Evidence
Once the execution completes (or fails), inspect the `validation_evidence/` directory.
Please share the console output and the contents of `validation_evidence/evidence.json` back into this chat. 

### 5. Post-Execution Audit
Once you provide the raw evidence, I will run a read-only Phase 5.5 Acceptance Audit to evaluate Gates 1 through 10 strictly against the rubric, definitively answering whether the architecture behaves as designed in the real world.
