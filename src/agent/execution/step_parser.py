"""Semantic human test-step parser.

Converts real human-written test steps into structured action tuples
``(action_type, target, value, expected_outcome)`` for ``GeneratedTestCase``
execution. Replaces the old whitespace-split parser.

Supported input (all case-insensitive, whitespace/punctuation tolerant):

Numbered steps::

    1. Navigate to System Definition > Tables.
    2) Open the Incident table
    Step 3: Verify that the Number field is visible.

Natural language::

    Set the state to Resolved.
    Click Save.
    Type a short description into the Summary field
    Wait for the Incident form to load
    Confirm the record was saved

Structured DSL (legacy scripted format)::

    navigate to @url:`https://example.com`
    fill incident_state with Resolved
    click Save
    wait for Incident form

Inline expected results use the ``|`` separator::

    Click Save | Incident changes are persisted

Step numbers are stripped and NEVER treated as an action type. Multi-line
steps are merged: a continuation line (no step number of its own) is folded
into the previous step. Steps whose wording does not match any template are
parsed by the LLM (using the existing client infrastructure); each unique
step text is cached under a stable hash in the shared StepCache so it is
never parsed twice. If no LLM is available (or it fails) the step degrades
to a safe ``validate`` action — invalid text can never raise an unhandled
``ValueError``.
"""

from __future__ import annotations

import re
from typing import Any

from agent.core.logging import get_logger
from agent.core.types import ActionType

logger = get_logger(__name__)

# Ordered verb → action type mapping. Order matters: more specific verbs
# first ("select" before "set", etc.).
_VERB_MAP: list[tuple[str, str]] = [
    ("navigate", "navigate"),
    ("go to", "navigate"),
    ("open", "navigate"),
    ("login", "navigate"),
    ("log in", "navigate"),
    ("click", "click"),
    ("press", "key_press"),
    ("submit", "click"),
    ("save", "click"),
    ("update", "click"),
    ("choose", "select"),
    ("select", "select"),
    ("pick", "select"),
    ("set", "fill"),
    ("fill", "fill"),
    ("type", "fill"),
    ("enter", "fill"),
    ("input", "fill"),
    ("provide", "fill"),
    ("wait", "wait"),
    ("verify", "validate"),
    ("assert", "validate"),
    ("check", "validate"),
    ("confirm", "validate"),
    ("ensure", "validate"),
    ("validate", "validate"),
    ("scroll", "scroll"),
    ("screenshot", "screenshot"),
    ("capture", "screenshot"),
]

_VALID_ACTION_TYPES = {a.value for a in ActionType}

# New-step markers: "1.", "1)", "1:", "Step 1:", "Step 1 -", "(1)"
_STEP_NUMBER_RE = re.compile(
    r"^\s*(?:\(?\d+\)|\d+\s*[.):\-]|\bstep\s*\d+\s*[:\-\.])\s*",
    re.IGNORECASE,
)

# Structured token: @url:`https://...` / @field:`incident.state`
_TOKEN_RE = re.compile(r"@(\w+):`([^`]*)`")

# ServiceNow lifecycle display names, for nicer expected outcomes.
_STATE_WORDS = (
    "new", "in progress", "on hold", "resolved", "closed", "canceled", "cancelled",
)


class StepParser:
    """Parses human-written step text into structured actions."""

    def __init__(self, llm_client: Any | None = None) -> None:
        self._llm = llm_client
        self._step_cache: Any | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def parse_steps(self, raw_lines: list[str]) -> list[dict[str, Any]]:
        """Parse a list of raw step lines into action dicts.

        Continuation lines are merged into the previous step first, then each
        merged step is parsed (template → cache → LLM → safe fallback).
        """
        merged = self._merge_continuation_lines(raw_lines)
        parsed_steps: list[dict[str, Any]] = []
        for text in merged:
            parsed_steps.append(await self.parse_step(text))
        return parsed_steps

    async def parse_step(self, raw_step: str) -> dict[str, Any]:
        """Parse one step text into {action_type, target, value, expected_outcome}.

        Never raises: unknown wording falls back to a ``validate`` action
        carrying the original text as its expected outcome.
        """
        # Inline expected outcome: "action | expected"
        action_text, expected_outcome = self._split_expected(raw_step)

        # Structured DSL first (explicit tokens win).
        structured = self._parse_structured(action_text)
        if structured is not None:
            at, target, value = structured
            return self._result(at, target, value, expected_outcome)

        # Deterministic template parse.
        s_at, s_target, s_value = self._parse_template(action_text)
        if s_at is not None:
            if not expected_outcome:
                expected_outcome = self._default_outcome(s_at, s_target, s_value, action_text)
            return self._result(s_at, s_target, s_value, expected_outcome)

        # Unrecognized wording → cache → LLM → safe fallback.
        parsed = await self._parse_with_llm(action_text)
        if parsed is not None:
            at = parsed.get("action_type") or ""
            if at in _VALID_ACTION_TYPES:
                if not expected_outcome:
                    expected_outcome = (
                        parsed.get("expected_outcome")
                        or self._default_outcome(at, parsed.get("target", ""), parsed.get("value", ""), action_text)
                    )
                return self._result(
                    at,
                    str(parsed.get("target", "")),
                    str(parsed.get("value", "")),
                    expected_outcome,
                )

        # Safe terminal fallback: treat as validation of the stated intent.
        logger.info("step_parse_fallback_validate", step=action_text[:80])
        return self._result("validate", action_text.strip(), "", expected_outcome or action_text.strip())

    # ------------------------------------------------------------------
    # Merging & splitting
    # ------------------------------------------------------------------

    def _merge_continuation_lines(self, raw_lines: list[str]) -> list[str]:
        """Fold continuation lines into the step they belong to.

        A line that does not start its own step number continues the previous
        step (multi-line step text).
        """
        merged: list[str] = []
        for line in raw_lines:
            line = (line or "").strip()
            if not line:
                continue
            starts_new = bool(_STEP_NUMBER_RE.match(line)) or bool(merged) is False
            if starts_new or not merged:
                merged.append(line)
            else:
                merged[-1] = f"{merged[-1]} {line}"
        return merged

    def _split_expected(self, raw_step: str) -> tuple[str, str]:
        """Split 'action | expected outcome' (only the first pipe counts)."""
        if "|" in raw_step:
            left, _, right = raw_step.partition("|")
            return left.strip(), right.strip()
        return raw_step.strip(), ""

    # ------------------------------------------------------------------
    # Structured DSL
    # ------------------------------------------------------------------

    def _parse_structured(self, text: str) -> tuple[str, str, str] | None:
        """Parse legacy DSL lines like ``navigate to @url:`...` ``."""
        tokens = dict(_TOKEN_RE.findall(text))
        low = " ".join(text.split()).lower()

        if "url" in tokens and low.startswith(("navigate", "go", "open")):
            return "navigate", tokens["url"], tokens["url"]
        if "field" in tokens or "target" in tokens:
            field = tokens.get("field") or tokens.get("target") or ""
            value = tokens.get("value") or ""
            if value:
                return "fill", field, value
            return "validate", field, ""

        m = re.match(r"^fill\s+(\S+)\s+with\s+(.+)$", text.strip(), re.IGNORECASE)
        if m:
            return "fill", m.group(1), m.group(2).strip()
        m = re.match(r"^click\s+(.+)$", text.strip(), re.IGNORECASE)
        if m:
            return "click", m.group(1).strip(), ""
        m = re.match(r"^wait\s+for\s+(.+)$", text.strip(), re.IGNORECASE)
        if m:
            return "wait", m.group(1).strip(), ""
        m = re.match(r"^navigate\s+to\s+(.+)$", text.strip(), re.IGNORECASE)
        if m:
            return "navigate", m.group(1).strip(), ""
        return None

    # ------------------------------------------------------------------
    # Natural-language templates
    # ------------------------------------------------------------------

    def _parse_template(self, text: str) -> tuple[str | None, str, str]:
        """Best-effort deterministic parse. Returns (None, '', '') if the
        wording does not start with a recognized verb."""
        # Strip leading step numbering/punctuation.
        body = _STEP_NUMBER_RE.sub("", text).strip()
        body = body.rstrip(" .;").strip()
        if not body:
            return None, "", ""
        low = body.lower()

        verb: str | None = None
        for candidate, action_type in _VERB_MAP:
            if low.startswith(candidate + " ") or low == candidate:
                verb = candidate
                break
        if verb is None:
            return None, "", ""

        rest = body[len(verb):].strip().lstrip("the ").strip()

        if verb == "navigate":
            dest = self._strip_leading_to(rest)
            return "navigate", dest, dest
        if verb in ("go to", "open", "login", "log in"):
            dest = self._strip_leading_to(rest)
            return "navigate", dest, dest
        if verb in ("click", "press", "submit", "save", "update"):
            target = self._strip_leading_to(rest).strip()
            if verb == "press":
                return "key_press", target, target
            if verb in ("submit", "save", "update") and not target:
                target = "Save"
            return "click", target, ""
        if verb in ("select", "choose", "pick"):
            # "select Resolved from State" / "select the State as Resolved"
            m = re.match(r"^(.+?)\s+from\s+(.+)$", rest, re.IGNORECASE)
            if m:
                return "select", m.group(2).strip(), m.group(1).strip()
            m = re.match(r"^(.+?)\s+(?:as|to|=)\s+(.+)$", rest, re.IGNORECASE)
            if m:
                return "select", m.group(1).strip(), m.group(2).strip()
            return "select", rest, ""
        if verb in ("fill", "type", "enter", "input", "set", "provide"):
            m = re.match(r"^(.+?)\s+(?:with|into|in|to|as)\s+(.+)$", rest, re.IGNORECASE)
            if m:
                field, value = m.group(1).strip(), m.group(2).strip()
                # "Type X into Y" swaps the roles.
                if verb == "type" and "into" in low[len(verb):]:
                    pm = re.match(r"^(.+?)\s+into\s+(.+)$", rest, re.IGNORECASE)
                    if pm:
                        field, value = pm.group(2).strip(), pm.group(1).strip()
                return "fill", field, value
            return "fill", rest, ""
        if verb == "wait":
            m = re.match(r"^for\s+(.+)$", rest, re.IGNORECASE)
            target = m.group(1).strip() if m else rest
            m_secs = re.match(r"^(\d+)\s*(?:s|sec|secs|seconds)?$", target, re.IGNORECASE)
            if m_secs:
                return "wait", "", m_secs.group(1)
            return "wait", target, ""
        if verb in ("verify", "assert", "check", "confirm", "ensure", "validate"):
            # Keep the full clause as the expected outcome text.
            field = re.sub(r"^(?:that\s+)?", "", rest, flags=re.IGNORECASE).strip()
            return "validate", field or "overall_state", ""
        if verb in ("scroll",):
            return "scroll", rest, ""
        if verb in ("screenshot", "capture"):
            return "screenshot", rest, ""
        return None, "", ""

    def _strip_leading_to(self, text: str) -> str:
        return re.sub(r"^to\s+", "", text.strip(), flags=re.IGNORECASE).strip()

    def _default_outcome(self, action_type: str, target: str, value: str, action_text: str) -> str:
        """Human-readable default expected outcome for a parsed action."""
        if action_type == "navigate":
            return f"Navigation to '{target}' completes and the page loads"
        if action_type == "click":
            return f"Element '{target}' is clicked and the UI responds"
        if action_type == "fill":
            if value:
                for state in _STATE_WORDS:
                    if value.lower() == state:
                        return f"Field '{target}' is set to {value.title()}"
                return f"Field '{target}' contains the value '{value}'"
            return f"Field '{target}' accepts input"
        if action_type == "select":
            return f"Option '{value or target}' is selected" if value else f"Option in '{target}' is selected"
        if action_type == "wait":
            return f"Wait for '{target or 'page'}' completes"
        if action_type == "validate":
            return action_text.strip() or "Validation passes"
        if action_type == "key_press":
            return f"Key '{value or target}' is pressed"
        if action_type == "screenshot":
            return "Screenshot captured"
        return "Action completes successfully"

    # ------------------------------------------------------------------
    # LLM fallback with stable-hash caching
    # ------------------------------------------------------------------

    def _get_step_cache(self) -> Any | None:
        if self._step_cache is None:
            try:
                from agent.cognition.step_cache import StepCache

                self._step_cache = StepCache()
            except Exception as e:
                logger.debug("step_cache_unavailable", error=str(e))
                return None
        return self._step_cache

    async def _parse_with_llm(self, action_text: str) -> dict[str, Any] | None:
        """Semantic parse via LLM, cached per unique step text."""
        if not self._llm:
            return None

        cache = self._get_step_cache()
        cached = None
        if cache is not None:
            try:
                cached = cache.get_parsed_step(action_text)
            except Exception:
                cached = None
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        prompt = (
            "Convert the following human-written UI test step into a JSON object "
            "with exactly these string fields: action_type, target, value, "
            "expected_outcome. action_type MUST be one of: "
            + ", ".join(sorted(_VALID_ACTION_TYPES))
            + ". target is the element/field/URL name. value is the text to "
            "input or select (empty string if none). expected_outcome is a short "
            "sentence describing what should happen.\n\nTest step: "
            + action_text.strip()
            + "\n\nRespond with ONLY the JSON object."
        )
        try:
            response = await self._llm.complete_json(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a test-step semantic parser. Respond only with "
                            "valid JSON matching the requested schema."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
            )
            if isinstance(response, dict):
                if cache is not None:
                    try:
                        cache.save_parsed_step(action_text, response)
                    except Exception:
                        pass
                return response
        except Exception as e:
            logger.warning("llm_step_parse_failed", error=str(e), step=action_text[:80])
        return None

    # ------------------------------------------------------------------

    @staticmethod
    def _result(action_type: str, target: str, value: str, expected_outcome: str) -> dict[str, Any]:
        return {
            "action_type": action_type,
            "target": (target or "").strip(),
            "value": (value or "").strip(),
            "expected_outcome": (expected_outcome or "Action completes successfully").strip(),
        }
