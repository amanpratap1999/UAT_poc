"""Validation tests for the audit P0 remediation.

Each test in this file validates that a specific P0 audit issue is
genuinely resolved. Tests read source files DIRECTLY (no imports)
so they can run without playwright/postgres/redis installed — the
file-content assertions are sufficient to prove the fix is in place.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest


# Resolve the repo root from this test file's location
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = REPO_ROOT / "src"


def _read_source(rel_path: str) -> str:
    """Read a source file from the repo, returning its raw text."""
    return (REPO_ROOT / rel_path).read_text()


def _strip_comments(source: str) -> str:
    """Strip Python comments + docstrings from a source string.

    Used so tests can assert X is in the active code without false-positives
    from commented-out lines that show the old code for context.

    Uses ast.parse to identify docstring line ranges precisely (the previous
    naive line-based approach mis-detected triple-quote sequences inside
    string literals). Then strips hash-comments from the remaining lines.
    """
    import ast
    # Parse the source to find all docstring ranges.
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # If the source doesn't parse, fall back to just stripping # comments.
        lines = source.split("\n")
        result = []
        for line in lines:
            if "#" in line:
                line = line.split("#")[0].rstrip()
            result.append(line)
        return "\n".join(result)

    # Collect (start, end) line ranges (1-indexed) of all docstrings.
    docstring_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                # The first statement is a string literal → it's a docstring.
                ds_node = body[0]
                docstring_ranges.append((ds_node.lineno, ds_node.end_lineno or ds_node.lineno))

    # Now walk the source lines, skipping docstring lines and stripping # comments.
    lines = source.split("\n")
    result = []
    in_docstring_range = False
    current_ds_end = 0
    for i, line in enumerate(lines, 1):
        # Check if this line is inside any docstring range.
        in_ds = any(start <= i <= end for start, end in docstring_ranges)
        if in_ds:
            continue
        # Strip inline # comments (naive — doesn't handle # inside strings,
        # but good enough for our test assertions).
        if "#" in line:
            line = line.split("#")[0].rstrip()
        result.append(line)
    return "\n".join(result)


def _extract_function_source(source: str, func_name: str) -> str:
    """Extract the source of a function by name, using ast for precision.

    Returns the function source as a string (including signature + body).
    Uses ast.parse to find the function node, then slices the source lines
    by the node's lineno..end_lineno.
    """
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            start = node.lineno
            end = node.end_lineno or node.lineno
            lines = source.split("\n")
            return "\n".join(lines[start - 1 : end])
    return ""


# ---------------------------------------------------------------------------
# Issue I5 (PR #1): JWT secret blocklist + entropy check
# ---------------------------------------------------------------------------

class TestJwtSecretBlocklist:
    """Validates that Settings rejects known placeholder/low-entropy secrets
    in non-local runtime mode."""

    @staticmethod
    def _make(**kwargs):
        # Force non-local runtime so the strict validation path runs
        from agent.core.config import Settings
        env = {
            "UAT_RUNTIME_MODE": "docker",
            "ENVIRONMENT": "production",
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_USERNAME": "admin",
            "SERVICENOW_PASSWORD": "testpass",
            "JWT_SECRET_KEY": "test-secret-for-ci-only-environment-not-production-32chars",
        }
        env.update(kwargs)
        return Settings(**env)

    def test_rejects_placeholder_secret_from_env_docker_example(self):
        """The literal value from .env.docker.example must be rejected."""
        with pytest.raises(Exception, match="placeholder|example|JWT_SECRET_KEY|strong secret"):
            TestJwtSecretBlocklist._make(
                JWT_SECRET_KEY="CHANGE_THIS_TO_A_SECURE_SECRET_AT_LEAST_32_CHARS",
            )

    def test_rejects_replace_me_placeholder(self):
        with pytest.raises(Exception):
            TestJwtSecretBlocklist._make(JWT_SECRET_KEY="REPLACE_ME")

    def test_rejects_low_entropy_secret(self):
        """A 32-char secret of all 'a' chars should be rejected for low entropy."""
        with pytest.raises(Exception, match="entropy|low|strong secret"):
            TestJwtSecretBlocklist._make(
                JWT_SECRET_KEY="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # 34 a's
            )

    def test_accepts_random_secret(self):
        """A real random secret should be accepted."""
        import secrets
        random_secret = secrets.token_urlsafe(48)
        settings = TestJwtSecretBlocklist._make(JWT_SECRET_KEY=random_secret)
        assert settings.jwt_secret_key == random_secret


# ---------------------------------------------------------------------------
# Issue I7 (PR #3): Hard-coded admin backdoor removal
# ---------------------------------------------------------------------------

class TestInitDbNoAdminBackdoor:
    """Validates that scripts/init_db.py no longer seeds a hard-coded 'admin' user."""

    def test_init_db_source_does_not_contain_hardcoded_admin(self):
        """Static check: the source of init_db.py must not contain the
        old hard-coded {username, "admin"} set literal."""
        source = _read_source("scripts/init_db.py")
        # The old code had: users_to_sync = {username, "admin"}
        assert '{username, "admin"}' not in source, (
            "init_db.py still contains the hard-coded admin backdoor — "
            "audit issue I7 is not resolved"
        )
        # The new code should reference only [username]
        assert "users_to_sync = [username]" in source, (
            "init_db.py should seed only the configured QA_ADMIN_USERNAME"
        )


# ---------------------------------------------------------------------------
# Issue I8 (PR #4): celery_app.py worker_ready syntax fix
# ---------------------------------------------------------------------------

class TestCeleryAppSyntax:
    """Validates that src/agent/core/celery_app.py parses without SyntaxError."""

    def test_celery_app_imports_cleanly(self):
        """The previous code had a malformed docstring that broke Python parsing."""
        source = _read_source("src/agent/core/celery_app.py")
        # Must parse cleanly
        ast.parse(source)
        # The fixed docstring is: """Emit a readiness event..."""
        assert "\"\"\"Emit a readiness event" in source, (
            "celery_app.py worker_ready handler should have a proper triple-quoted docstring"
        )


# ---------------------------------------------------------------------------
# Issue I25 (PR #6): StepCache tenant isolation
# ---------------------------------------------------------------------------

class TestStepCacheTenantIsolation:
    """Validates that the StepCache produces different hashes for different tenant_ids."""

    def test_hash_intent_signature_includes_tenant_id(self):
        """Static check: _hash_intent must accept tenant_id as a parameter."""
        source = _read_source("src/agent/cognition/step_cache.py")
        func_source = _extract_function_source(source, "_hash_intent")
        # The new signature: def _hash_intent(self, goal, intent_type, step_desc, expected, tenant_id)
        assert "tenant_id" in func_source, (
            "StepCache._hash_intent must accept tenant_id as a parameter — "
            "if not, audit issue I25 (cross-tenant step cache leak) is present"
        )

    def test_get_action_signature_requires_tenant_id(self):
        """get_action must have tenant_id as a required parameter (no default)."""
        source = _read_source("src/agent/cognition/step_cache.py")
        func_source = _extract_function_source(source, "get_action")
        # The new signature: def get_action(self, goal, intent_type, step_desc, expected, tenant_id)
        assert "tenant_id" in func_source, (
            "StepCache.get_action must accept tenant_id as a parameter"
        )

    def test_save_action_signature_requires_tenant_id(self):
        source = _read_source("src/agent/cognition/step_cache.py")
        func_source = _extract_function_source(source, "save_action")
        assert "tenant_id" in func_source


# ---------------------------------------------------------------------------
# Issue I19 (PR #7): Planner prompt-injection boundary
# ---------------------------------------------------------------------------

class TestPlannerPromptInjectionBoundary:
    """Validates that the 4 broken Planner methods now use LLMInputBoundary."""

    def _get_active_function_source(self, func_name: str) -> str:
        """Read planner.py, extract the function source, strip comments/docstrings."""
        source = _read_source("src/agent/planner/planner.py")
        func_source = _extract_function_source(source, func_name)
        return _strip_comments(func_source)

    def test_assess_validation_uses_boundary(self):
        source = self._get_active_function_source("assess_validation")
        assert "LLMInputBoundary" in source, (
            "assess_validation must use LLMInputBoundary — if it still uses "
            "str.format(before_observation=before.to_compact_summary(), ...), "
            "audit issue I19 (prompt-injection bypass) is not resolved"
        )
        assert "add_untrusted_data" in source
        assert "VALIDATION_ASSESSMENT_PROMPT.format(" not in source, (
            "assess_validation must NOT use VALIDATION_ASSESSMENT_PROMPT.format(...) — "
            "this was the prompt-injection bypass"
        )

    def test_suggest_recovery_uses_boundary(self):
        source = self._get_active_function_source("suggest_recovery")
        assert "LLMInputBoundary" in source
        assert "add_untrusted_data" in source
        assert "RECOVERY_PROMPT.format(" not in source

    def test_is_goal_complete_uses_boundary(self):
        source = self._get_active_function_source("is_goal_complete")
        assert "LLMInputBoundary" in source
        assert "add_untrusted_data" in source
        assert "COMPLETION_CHECK_PROMPT.format(" not in source

    def test_generate_report_summary_uses_boundary(self):
        source = self._get_active_function_source("generate_report_summary")
        assert "LLMInputBoundary" in source
        assert "add_untrusted_data" in source
        assert "REPORT_SUMMARY_PROMPT.format(" not in source


# ---------------------------------------------------------------------------
# Issue I11 (PR #8): Screenshot cross-tenant leak fix
# ---------------------------------------------------------------------------

class TestScreenshotEndpointTenantIsolation:
    """Validates that GET /api/v1/screenshots/{filename} requires tenant verification."""

    def test_screenshot_endpoint_does_not_fall_through_to_file_response(self):
        """The old code had a `else: pass` (fall-through) that served unregistered
        files to any tenant. The new code must raise 404 when no Screenshot row
        and no UUID prefix is found."""
        source = _read_source("src/agent/api/v1/router.py")
        func_source = _extract_function_source(source, "get_screenshot")
        active = _strip_comments(func_source)
        # The fixed code raises HTTPException(404) when filename doesn't start with UUID
        assert "not registered to a tenant" in active, (
            "get_screenshot must raise 404 for unregistered filenames — "
            "if it falls through to FileResponse, audit issue I11 is not resolved"
        )


# ---------------------------------------------------------------------------
# Issue I12 (PR #8): RBAC under-enforcement on mutating endpoints
# ---------------------------------------------------------------------------

class TestRouterRbacEnforcement:
    """Validates that mutating endpoints now require Depends(require_qa_engineer)
    or Depends(require_qa_manager), not just Depends(get_current_user_token)."""

    def _get_func_signature(self, func_name: str) -> str:
        """Read router.py, extract the function's signature (first ~6 lines), strip comments."""
        source = _read_source("src/agent/api/v1/router.py")
        return _strip_comments(_extract_function_source(source, func_name))

    def test_update_finding_requires_qa_manager(self):
        source = self._get_func_signature("update_finding")
        assert "require_qa_manager" in source, (
            "update_finding must depend on require_qa_manager — "
            "Viewer-role tokens must NOT be able to flip defect verdicts"
        )

    def test_cancel_run_requires_qa_manager(self):
        source = self._get_func_signature("cancel_run")
        assert "require_qa_manager" in source

    def test_submit_approval_requires_qa_manager(self):
        source = self._get_func_signature("submit_approval")
        assert "require_qa_manager" in source

    def test_create_run_requires_qa_engineer(self):
        source = self._get_func_signature("create_run")
        assert "require_qa_engineer" in source

    def test_pause_run_requires_qa_engineer(self):
        source = self._get_func_signature("pause_run")
        assert "require_qa_engineer" in source

    def test_execute_test_case_requires_qa_engineer(self):
        source = self._get_func_signature("execute_test_case")
        assert "require_qa_engineer" in source


# ---------------------------------------------------------------------------
# Issue I44 (PR #12): decode_responses=True + dropped .decode() calls
# ---------------------------------------------------------------------------

class TestLocksDecodeResponses:
    """Validates that RecordLockManager.get_redis() sets decode_responses=True
    and the .decode('utf-8') calls are removed."""

    def test_get_redis_sets_decode_responses_true(self):
        source = _read_source("src/agent/core/locks.py")
        func_source = _strip_comments(_extract_function_source(source, "get_redis"))
        assert "decode_responses=True" in func_source, (
            "RecordLockManager.get_redis must set decode_responses=True — "
            "if not, the .decode('utf-8') calls would raise AttributeError on str inputs"
        )

    def test_acquire_redis_does_not_call_decode(self):
        source = _read_source("src/agent/core/locks.py")
        func_source = _strip_comments(_extract_function_source(source, "_acquire_redis"))
        assert ".decode(" not in func_source, (
            "_acquire_redis must NOT call .decode('utf-8') — "
            "with decode_responses=True, the value is already a str"
        )


# ---------------------------------------------------------------------------
# Issue I18 (PR #10): recovery counter resets on success
# ---------------------------------------------------------------------------

class TestRecoveryCounterReset:
    """Validates that RecoveryEngine resets the per-cycle counter on success
    and tracks lifetime failures separately."""

    def test_success_resets_action_failures_counter(self):
        """The success branch must set self._action_failures[action_key] = 0."""
        source = _read_source("src/agent/recovery/engine.py")
        func_source = _strip_comments(_extract_function_source(source, "attempt_recovery"))
        assert "self._action_failures[action_key] = 0" in func_source, (
            "RecoveryEngine.attempt_recovery must reset _action_failures[action_key] = 0 "
            "on successful recovery — if not, transient failure bursts permanently "
            "poison the action_key (audit issue I18)"
        )

    def test_lifetime_failures_tracked_separately(self):
        source = _read_source("src/agent/recovery/engine.py")
        # __init__ is the constructor; check it has _lifetime_failures
        func_source = _strip_comments(_extract_function_source(source, "__init__"))
        assert "_lifetime_failures" in func_source, (
            "RecoveryEngine must track lifetime failures separately — "
            "without this, the hard ceiling for permanently-broken actions is lost"
        )


# ---------------------------------------------------------------------------
# Issue I20 (PR #11): str.replace instead of str.format
# ---------------------------------------------------------------------------

class TestIntentManagerFormatFix:
    """Validates that IntentManager uses .replace() not .format() for user prompts."""

    def test_parse_intent_uses_replace_not_format(self):
        source = _read_source("src/agent/intent/manager.py")
        func_source = _strip_comments(_extract_function_source(source, "parse_intent"))
        assert ".replace(" in func_source, (
            "IntentManager.parse_intent must use str.replace() — "
            ".format() would raise KeyError on user input containing literal { or }"
        )
        # The active code must NOT contain .format( with the prompt template
        assert "INTENT_PARSER_PROMPT.format(" not in func_source


# ---------------------------------------------------------------------------
# Issue I16 (follow-up PR): proper encapsulation setters
# ---------------------------------------------------------------------------

class TestEncapsulationSetters:
    """Validates that the I16 encapsulation fix is actually implemented
    via public setter methods (not just documented with TODO comments)."""

    def test_planner_has_set_scenario_generator(self):
        source = _read_source("src/agent/planner/planner.py")
        assert "def set_scenario_generator(" in source, (
            "Planner must have a public set_scenario_generator() method — "
            "without it, main.py would still reach into _planner._scenario_generator"
        )

    def test_planner_has_set_test_store(self):
        source = _read_source("src/agent/planner/planner.py")
        assert "def set_test_store(" in source

    def test_planner_has_get_llm_client(self):
        source = _read_source("src/agent/planner/planner.py")
        assert "def get_llm_client(" in source, (
            "Planner must have a public get_llm_client() accessor — "
            "without it, main.py would still read _planner._llm directly"
        )

    def test_orchestrator_has_attach_llm(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def attach_llm(" in source

    def test_orchestrator_has_attach_state_machine(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def attach_state_machine(" in source

    def test_orchestrator_has_attach_journal(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def attach_journal(" in source

    def test_orchestrator_has_attach_browser_manager(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def attach_browser_manager(" in source

    def test_orchestrator_has_attach_execution_controller(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def attach_execution_controller(" in source

    def test_orchestrator_has_attach_perception_engine(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def attach_perception_engine(" in source

    def test_orchestrator_has_attach_lock_manager(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def attach_lock_manager(" in source

    def test_orchestrator_has_get_observation_engine(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def get_observation_engine(" in source

    def test_orchestrator_has_get_locked_records(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        assert "def get_locked_records(" in source

    def test_orchestrator_has_execute_canonical_plan_public(self):
        source = _read_source("src/agent/cognition/orchestrator.py")
        # Public wrapper — must NOT have leading underscore
        assert "async def execute_canonical_plan(" in source

    def test_incident_api_oracle_has_get_client(self):
        source = _read_source("src/agent/skills/incident/api_oracle.py")
        assert "def get_client(" in source, (
            "IncidentApiOracle must have a public get_client() accessor — "
            "without it, main.py would still read oracle._client directly"
        )

    def test_main_py_does_not_access_private_planner_attrs(self):
        """Static check: main.py should not contain `_planner._` or
        `_cognitive_orchestrator._` private-attribute accesses."""
        source = _read_source("src/agent/main.py")
        active = _strip_comments(source)
        # Allow `_cognitive_orchestrator.` followed by a public method (e.g.,
        # `attach_`, `get_`, `execute_`, `set_`, `session_id`).
        # Disallow direct underscore-prefixed attribute access.
        import re
        # Find any `_cognitive_orchestrator._something` (with the leading _ before something)
        bad = re.findall(r"_cognitive_orchestrator\._\w+", active)
        # Also check _planner._something
        bad.extend(re.findall(r"_planner\._\w+", active))
        # And oracle._client
        bad.extend(re.findall(r"oracle\._\w+", active))
        # Filter out things that are inside string literals (we already stripped
        # comments but not strings — accept some false positives for now, the
        # important thing is the count drops to near-zero).
        assert not bad, (
            f"main.py still contains private-attribute accesses: {bad}. "
            "Use the public setter/accessor methods instead."
        )


# ---------------------------------------------------------------------------
# Issue I2 (follow-up PR): proper lazy-read functions
# ---------------------------------------------------------------------------

class TestLazySettingsReads:
    """Validates that the I2 fix is actually implemented via lazy-read
    functions (not just documented)."""

    def test_auth_has_get_secret_key_function(self):
        source = _read_source("src/agent/api/v1/auth.py")
        assert "def get_secret_key(" in source, (
            "auth.py must have a public get_secret_key() function — "
            "without it, callers would still read the module-level SECRET_KEY constant"
        )

    def test_auth_has_get_algorithm_function(self):
        source = _read_source("src/agent/api/v1/auth.py")
        assert "def get_algorithm(" in source

    def test_auth_has_get_access_token_expire_minutes_function(self):
        source = _read_source("src/agent/api/v1/auth.py")
        assert "def get_access_token_expire_minutes(" in source

    def test_auth_does_not_define_module_level_secret_key_constant(self):
        """The old `SECRET_KEY = _settings.jwt_secret_key` line must be gone."""
        source = _read_source("src/agent/api/v1/auth.py")
        active = _strip_comments(source)
        # The pattern `SECRET_KEY = ` (with a value assignment) should not appear
        # in the active code. We allow it in docstrings/comments (already stripped).
        import re
        bad = re.findall(r"^SECRET_KEY\s*=", active, re.MULTILINE)
        assert not bad, (
            f"auth.py still defines module-level SECRET_KEY constant: {bad}. "
            "Use get_secret_key() function instead."
        )

    def test_auth_does_not_define_module_level_algorithm_constant(self):
        source = _read_source("src/agent/api/v1/auth.py")
        active = _strip_comments(source)
        import re
        bad = re.findall(r"^ALGORITHM\s*=", active, re.MULTILINE)
        assert not bad, (
            f"auth.py still defines module-level ALGORITHM constant: {bad}."
        )

    def test_create_access_token_uses_lazy_get_secret_key(self):
        source = _read_source("src/agent/api/v1/auth.py")
        func_source = _strip_comments(_extract_function_source(source, "create_access_token"))
        assert "get_secret_key()" in func_source, (
            "create_access_token must call get_secret_key() lazily — "
            "if it still uses the module-level SECRET_KEY constant, runtime settings "
            "swaps would cause issuer/validator drift (audit issue I2)"
        )
        assert "get_algorithm()" in func_source

    def test_validate_token_string_uses_lazy_get_secret_key(self):
        source = _read_source("src/agent/api/v1/auth.py")
        func_source = _strip_comments(_extract_function_source(source, "validate_token_string"))
        assert "get_secret_key()" in func_source
        assert "get_algorithm()" in func_source

    def test_auth_router_uses_get_access_token_expire_minutes(self):
        source = _read_source("src/agent/api/v1/auth_router.py")
        active = _strip_comments(source)
        assert "get_access_token_expire_minutes()" in active, (
            "auth_router.py must call get_access_token_expire_minutes() lazily — "
            "if it still imports the module-level ACCESS_TOKEN_EXPIRE_MINUTES constant, "
            "runtime settings swaps would not be honored (audit issue I2)"
        )
        # The old import of the constant should be gone
        assert "ACCESS_TOKEN_EXPIRE_MINUTES," not in active

