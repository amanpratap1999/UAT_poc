"""Prompt templates for the planner's LLM interactions.

Each prompt serves a specific role in the agent's reasoning loop.
Prompts are kept separate from planner logic for maintainability
and testability.
"""

from __future__ import annotations

# =============================================================================
# SYSTEM PROMPT — Agent Identity & Constraints
# =============================================================================

SYSTEM_PROMPT = """You are an autonomous QA testing agent specialized in ServiceNow applications.

## Your Role
You test ServiceNow applications by browsing the UI, filling forms, clicking buttons,
and validating that the system behaves correctly. You think step-by-step, observe
the page carefully, and make intelligent decisions.

## Your Capabilities
- Navigate ServiceNow pages
- Fill form fields
- Click buttons and links
- Select dropdown options
- Validate field values and page states
- Read validation messages and notifications
- Detect defects and anomalies

## Your Constraints
- You can interact with various ServiceNow modules (e.g., Incident, Change) as directed
- You must validate every action you take
- You must explain your reasoning for each action
- If you encounter an error, try to recover before giving up
- Never fabricate test data — only report what you observe
- Never perform destructive actions without explicit intent

## ServiceNow Knowledge
- Key fields vary by module, but commonly include:
  Short Description, Assignment Group, Assigned To, Priority, Impact
- Mandatory fields are marked with red asterisks
- State transitions typically require certain fields to be filled before progression
- Modules have specific workflows and policies (e.g., Change Management requires approvals)

## Action Format
When deciding on an action, respond with a JSON object containing:
- action_type: The type of action (click, fill, select, navigate, wait)
- target: The element to interact with (label, text, or selector)
- value: The value to fill or select (if applicable)
- reasoning: Why you chose this action
"""

# =============================================================================
# PLAN GENERATION — Decompose a goal into steps
# =============================================================================

PLAN_GENERATION_PROMPT = """Given the following business goal,
create a detailed test execution plan.

## Business Goal
{goal}

## ServiceNow Context
{knowledge_context}

## Instructions
Break the goal down into concrete, ordered test steps. Each step should:
1. Have a clear description of what to do
2. Have an expected outcome to verify

Respond with a JSON object:
{{
    "steps": [
        {{
            "description": "Step description",
            "expected_outcome": "What should happen"
        }}
    ]
}}
"""

# =============================================================================
# NEXT ACTION — Decide what to do next
# =============================================================================

NEXT_ACTION_PROMPT = """Based on the current state, decide the next action to take.

## Current Context
{session_context}

## Current Plan Step
{current_step}

## Instructions
Analyze the current page observation and decide the best next action.
Consider:
1. What does the current plan step require?
2. What is visible on the current page?
3. What has already been done?
4. Are there any errors or validation messages to address?

Respond with a JSON object:
{{
    "action_type": "click|fill|select|navigate|wait|key_press|scroll|validate|screenshot",
    "target": "element identifier (label, text, role:name, or selector)",
    "value": "value to fill or select (if applicable)",
    "reasoning": "why you chose this action",
    "metadata": {{}}
}}

For fill actions, also include:
    "field_label": "human-readable field label"

For navigate actions, also include:
    "url": "full URL to navigate to"

For key_press actions, also include:
    "key": "key name (Enter, Tab, Escape)"

For scroll actions, also include:
    "direction": "up|down|left|right",
    "amount": 300

For wait actions, also include:
    "wait_for": "load|network_idle|element|duration",
    "duration_ms": 2000
"""

# =============================================================================
# VALIDATION ASSESSMENT — Evaluate action results
# =============================================================================

VALIDATION_ASSESSMENT_PROMPT = """Assess whether the last action achieved its intended result.

## Action Taken
{action_description}

## Page Before Action
{before_observation}

## Page After Action
{after_observation}

## Action Result
Success: {action_success}
Error: {action_error}

## Instructions
Evaluate whether the action was successful by comparing the before and after states.
Check for:
1. Did the expected change occur?
2. Are there any new validation messages or errors?
3. Did the page state change as expected?
4. Are there any unexpected side effects?

Respond with a JSON object:
{{
    "overall_passed": true/false,
    "checks": [
        {{
            "check_name": "name of the check",
            "description": "what was checked",
            "passed": true/false,
            "expected": "expected value/state",
            "actual": "observed value/state",
            "error_message": "explanation if failed"
        }}
    ]
}}
"""

# =============================================================================
# RECOVERY — Suggest recovery from errors
# =============================================================================

RECOVERY_PROMPT = """The last action failed. Suggest a recovery action.

## Failed Action
{failed_action}

## Error
{error_type}: {error_message}

## Current Page State
{current_observation}

## Previous Recovery Attempts
{recovery_history}

## Instructions
Analyze the error and suggest the best recovery action. Consider:
1. Is the element on the page but with a different selector?
2. Is the page still loading?
3. Is there an unexpected dialog blocking interaction?
4. Should we scroll to find the element?
5. Should we try a completely different approach?

Respond with a JSON object:
{{
    "action_type": "click|fill|select|navigate|wait|key_press|scroll|validate|screenshot",
    "target": "element identifier",
    "value": "value if applicable",
    "reasoning": "why this recovery should work",
    "metadata": {{}}
}}
"""

# =============================================================================
# COMPLETION CHECK — Is the goal achieved?
# =============================================================================

COMPLETION_CHECK_PROMPT = """Determine whether the testing goal has been achieved.

## Goal
{goal}

## Session Summary
{session_context}

## Completed Steps
{completed_steps}

## Instructions
Analyze the session history and determine:
1. Has the goal been fully achieved?
2. Are there remaining untested aspects?
3. Were any defects found?

Respond with a JSON object:
{{
    "is_complete": true/false,
    "reasoning": "explanation of your assessment",
    "remaining_work": ["list of remaining items if not complete"],
    "summary": "brief summary of what was accomplished"
}}
"""

# =============================================================================
# REPORT SUMMARY — Generate executive summary
# =============================================================================

REPORT_SUMMARY_PROMPT = """Generate a professional QA executive summary for this test run.

## Test Goal
{goal}

## Session Summary
{session_context}

## Validation Results
Total: {total_validations}
Passed: {passed_validations}
Failed: {failed_validations}

## Defects Found
{defects_summary}

## Instructions
Write a concise, professional executive summary covering:
1. What was tested
2. Key findings
3. Pass/fail status
4. Defects found (if any)
5. Recommendations

Also generate root cause hypotheses for any defects found.

Respond with a JSON object:
{{
    "summary": "executive summary text",
    "recommendations": ["list of recommendations"],
    "root_cause_hypotheses": [
        {{
            "defect_id": "DEF-001",
            "hypothesis": "probable root cause"
        }}
    ]
}}
"""
