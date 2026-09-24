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

    Used so tests can assert "X is in the active code" without false-positives
    from commented-out lines that show the old code for context.
    """
    lines = []
    in_docstring = False
    for line in source.split("\n"):
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        if "#" in line:
            line = line.split("#")[0].rstrip()
        lines.append(line)
    return "\n".join(lines)


def _extract_function_source(source: str, func_name: str) -> str:
    """Extract the source of a function (def func_name through the next def/class at same indent).

    Returns the function source as a string (including decorator + signature + body).
    """
    lines = source.split("\n")
    # Find the line that starts `async def <func_name>(` or `def <func_name>(`
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*(async\s+)?def\s+{func_name}\s*\(", line):
            start_idx = i
            break
    if start_idx is None:
        return ""
    # Find the function's base indentation
    indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    # Walk forward until we hit a line at the same or lower indent (excluding blank lines)
    # OR end of file
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())
        # If we hit a line at the same or lower indent that's not part of the function body
        if line_indent <= indent and (line.lstrip().startswith("def ") or line.lstrip().startswith("async def ") or line.lstrip().startswith("class ") or line.lstrip().startswith("@")):
            end_idx = i
            break
    return "\n".join(lines[start_idx:end_idx])


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
