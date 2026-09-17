"""Human Test-Case Importer (XLSX).

Ingests human-authored test cases from real workbooks and maps them to
GeneratedTestCase models. Replaces the old whitespace-split parser with a
semantic step parser that understands:

- Numbered steps: ``1.``, ``1)``, ``Step 1:`` (the number is never treated
  as an action type).
- Natural-language navigation ("Navigate to System Definition > Tables").
- Common verbs: open, click, select, fill, type, set, enter, submit, save,
  update, wait, verify, assert, check, confirm, and similar actions.
- Expected-result clauses ("Verify that the Number field is visible").
- Multi-line step text (a step continues until the next numbered step).
- Extra whitespace and punctuation.
- Structured DSL syntax from earlier versions, e.g.::

    navigate to @url:`https://example.com`
    fill incident_state with Resolved
    click Save
    wait for Incident form

- Steps whose wording does not match a fixed template fall back to an LLM
  semantic parse (using the existing LLM client infrastructure), cached per
  unique step text via a stable hash in the shared StepCache.

Multi-sheet workbooks: iterates every relevant worksheet, skips index/summary
sheets (case-insensitive), preserves the worksheet (story) name, supports an
explicit sheet filter, handles empty sheets safely, and de-duplicates test
cases by (id, sheet).

Column mapping (Req 5):
- ``Test Scenario``          → title/scenario
- ``Test Case Description``  → actual goal/instruction text (source_user_story)
- ``User Story Ref``         → separate story-reference field (story_id); NEVER the goal/title
- ``Test Data`` / ``test_data`` → GeneratedTestCase.test_data
- Expected-result columns    → final assertions
- ``Preconditions``          → preconditions
- ``Priority``               → priority/risk
- ``Steps``                  → executable steps
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from openpyxl import load_workbook

from agent.core.logging import get_logger
from agent.domain.story import ExpectedAssertion, GeneratedTestCase, TestStep
from agent.execution.step_parser import StepParser

logger = get_logger(__name__)

# Worksheets that are navigation/index/summary pages, not story sheets.
_SKIP_SHEETS = {"index", "summary", "toc", "table of contents", "readme", "cover"}


class TestCaseImporter:
    """Parses Excel test cases into GeneratedTestCase models."""

    def __init__(self, file_path: str, llm_client: Any | None = None) -> None:
        self.file_path = file_path
        self._parser = StepParser(llm_client=llm_client)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def parse(self, sheet_name: str | None = None) -> list[GeneratedTestCase]:
        """Parse the XLSX file into a list of GeneratedTestCase objects.

        Args:
            sheet_name: Optional explicit worksheet name. When provided only
                that sheet is parsed; otherwise every non-index sheet is.
        """
        logger.info("parsing_test_cases_from_excel", file=self.file_path, sheet=sheet_name)
        try:
            wb = load_workbook(filename=self.file_path, data_only=True)
        except Exception as e:
            logger.error("excel_load_error", error=str(e), file=self.file_path)
            raise ValueError(f"Failed to load Excel file: {e}")

        if sheet_name is not None:
            if sheet_name not in wb.sheetnames:
                raise ValueError(
                    f"Worksheet '{sheet_name}' not found. Available: {wb.sheetnames}"
                )
            sheet_names = [sheet_name]
        else:
            sheet_names = list(wb.sheetnames)

        test_cases: list[GeneratedTestCase] = []
        seen_keys: set[tuple[str, str]] = set()

        for sname in sheet_names:
            if sname.strip().lower() in _SKIP_SHEETS:
                logger.info("skipping_index_sheet", sheet=sname)
                continue

            ws = wb[sname]

            header_row_idx, col_map = self._read_header(ws)
            if header_row_idx is None or not col_map:
                logger.info("skipping_sheet_no_headers", sheet=sname)
                continue

            sheet_cases = 0
            for row_idx, row in enumerate(
                ws.iter_rows(min_row=header_row_idx + 1, values_only=True),
                header_row_idx + 1,
            ):
                if not any(row):
                    continue

                tc = await self._row_to_test_case(
                    row, col_map, sname, row_idx
                )
                if tc is None:
                    continue

                key = (tc.id, sname)
                if key in seen_keys:
                    logger.info("duplicate_test_case_skipped", id=tc.id, sheet=sname)
                    continue
                seen_keys.add(key)
                test_cases.append(tc)
                sheet_cases += 1

            logger.info("sheet_parsed", sheet=sname, cases=sheet_cases)

        logger.info("excel_parsing_complete", num_cases=len(test_cases))
        return test_cases

    # ------------------------------------------------------------------
    # Header handling
    # ------------------------------------------------------------------

    def _read_header(self, ws: Any) -> tuple[int | None, dict[str, int | None]]:
        """Locate the header row (within the first 5 rows) and map columns.

        Returns (header_row_index, col_map) — header_row_index is the 1-based
        worksheet row holding the header, or None if the sheet is empty.
        """
        header_row_idx = None
        headers: dict[str, int] = {}
        for row in ws.iter_rows(min_row=1, max_row=5):
            if not any(cell.value for cell in row):
                continue
            if header_row_idx is None:
                header_row_idx = row[0].row
            for col_idx, cell in enumerate(row, 1):
                if cell.value and str(cell.value).strip():
                    headers[str(cell.value).strip().lower()] = col_idx - 1

        if header_row_idx is None or not headers:
            return None, {}

        col_map = {
            "id": self._find_col(headers, ["id", "test case id", "tc_id", "test id"]),
            "title": self._find_col(headers, ["test scenario", "scenario", "title", "test case name"]),
            "description": self._find_col(headers, ["test case description", "description", "goal", "instruction"]),
            "story_ref": self._find_col(headers, ["user story ref", "user story reference", "story ref", "story reference", "jira ref", "jira"]),
            "module": self._find_col(headers, ["module", "table", "area"]),
            "target": self._find_col(headers, ["target", "target record", "record", "incident number"]),
            "role": self._find_col(headers, ["role", "actor", "actor role", "persona"]),
            "preconditions": self._find_col(headers, ["preconditions", "precondition", "prerequisites", "prerequisite"]),
            "test_data": self._find_col(headers, ["test data", "test_data"]),
            "steps": self._find_col(headers, ["steps", "step", "action", "actions", "execution steps", "test steps"]),
            "expected": self._find_col(headers, ["expected result", "expected results", "expected", "final assertions", "acceptance criteria"]),
            "priority": self._find_col(headers, ["priority", "risk", "risk level"]),
            "test_type": self._find_col(headers, ["test type", "type", "category"]),
            "business_rules": self._find_col(headers, ["business rules", "business rule", "rules"]),
            "dependencies": self._find_col(headers, ["dependencies", "dependency", "depends on"]),
        }
        return header_row_idx, col_map

    def _find_col(self, headers: dict[str, int], aliases: list[str]) -> int | None:
        """Find a column index matching any of the aliases (exact-first)."""
        # Exact match wins before substring probing so 'User Story Ref' can
        # never be captured by a broader 'story' alias.
        for alias in aliases:
            if alias in headers:
                return headers[alias]
        for alias in aliases:
            for header, idx in headers.items():
                if alias in header:
                    return idx
        return None

    # ------------------------------------------------------------------
    # Row → GeneratedTestCase
    # ------------------------------------------------------------------

    def _cell(self, row: tuple[Any, ...], col: int | None) -> Any:
        if col is None or col >= len(row):
            return None
        return row[col]

    def _split_lines(self, value: Any) -> list[str]:
        if value is None:
            return []
        return [p.strip() for p in str(value).splitlines() if p.strip()]

    def _derive_test_type(self, raw: Any, title: str, description: str) -> str:
        """Derive the coverage taxonomy value (Req 9)."""
        text = f"{raw or ''} {title} {description}".lower()
        if "idempoten" in text:
            return "Idempotency"
        if "audit" in text:
            return "Audit"
        if "error isolation" in text or "isolation" in text:
            return "Error Isolation"
        if "end-to-end" in text or "end to end" in text or "e2e" in text:
            return "End-to-End"
        if raw:
            return str(raw).strip().title()
        return "Functional"

    async def _row_to_test_case(
        self,
        row: tuple[Any, ...],
        col_map: dict[str, int | None],
        sheet_name: str,
        row_idx: int,
    ) -> GeneratedTestCase | None:
        # --- Identity & story fields ---
        tc_id = self._cell(row, col_map["id"])
        tc_id = str(tc_id).strip() if tc_id else f"TC-AUTO-{uuid.uuid4().hex[:6].upper()}"

        title = self._cell(row, col_map["title"])
        title = str(title).strip() if title else ""

        description = self._cell(row, col_map["description"])
        description = str(description).strip() if description else ""

        story_ref = self._cell(row, col_map["story_ref"])
        story_ref = str(story_ref).strip() if story_ref else ""

        # Never use User Story Ref as the goal/title (Req 5). The description
        # column carries the actual goal/instruction text; the title is the
        # scenario. Fall back between them only when one is missing.
        goal = description or title or f"Human Authored Test Case ({sheet_name})"
        if not title:
            title = story_ref or goal[:80]

        module = self._cell(row, col_map["module"])
        module = str(module).strip() if module else "incident"

        target = self._cell(row, col_map["target"])
        target = str(target).strip() if target else None

        role = self._cell(row, col_map["role"])
        role = str(role).strip() if role else "admin"

        priority = self._cell(row, col_map["priority"])
        priority = str(priority).strip() if priority else "Medium"

        test_type_raw = self._cell(row, col_map["test_type"])
        test_type = self._derive_test_type(test_type_raw, title, description)

        preconditions = self._split_lines(self._cell(row, col_map["preconditions"]))

        # --- Test data (Req 5): JSON object or raw text ---
        test_data: dict[str, Any] = {}
        td_raw = self._cell(row, col_map["test_data"])
        if td_raw:
            td_text = str(td_raw).strip()
            if td_text.startswith("{"):
                try:
                    parsed = json.loads(td_text)
                    if isinstance(parsed, dict):
                        test_data = parsed
                    else:
                        test_data = {"raw": td_text}
                except Exception:
                    test_data = {"raw": td_text}
            else:
                test_data = {"raw": td_text}

        # --- Steps (Req 2): semantic parse of human text ---
        steps: list[TestStep] = []
        steps_raw = self._cell(row, col_map["steps"])
        if steps_raw:
            raw_steps = self._split_lines(steps_raw)
            parsed_steps = await self._parser.parse_steps(raw_steps)
            for idx, parsed in enumerate(parsed_steps, 1):
                steps.append(
                    TestStep(
                        step_number=idx,
                        action_type=parsed["action_type"],
                        target=parsed["target"],
                        value=parsed["value"],
                        expected_outcome=parsed["expected_outcome"],
                    )
                )

        # --- Expected-result column → final assertions ---
        assertions: list[ExpectedAssertion] = []
        expected_raw = self._cell(row, col_map["expected"])
        if expected_raw:
            for j, raw_assert in enumerate(self._split_lines(expected_raw), 1):
                field, operator, value = self._parse_assertion(raw_assert)
                assertions.append(
                    ExpectedAssertion(
                        assertion_id=f"AST-{tc_id}-{j}",
                        field=field,
                        operator=operator,
                        expected_value=value,
                        description=raw_assert.strip(),
                    )
                )

        # --- Story-scoped context (Req 8) ---
        business_rules = self._split_lines(self._cell(row, col_map["business_rules"]))
        dependencies = self._split_lines(self._cell(row, col_map["dependencies"]))

        story_context: dict[str, Any] = {
            "story_ref": story_ref,
            "sheet_name": sheet_name,
            "source_row": row_idx,
            "business_rules": business_rules,
            "dependencies": dependencies,
            "preconditions": list(preconditions),
            "acceptance_criteria": [
                a.description for a in assertions if a.description
            ],
            "test_data": dict(test_data),
            "source_file": self.file_path,
        }

        return GeneratedTestCase(
            id=tc_id,
            title=title,
            test_type=test_type,
            source_user_story=goal,
            story_id=story_ref or sheet_name,
            story_context=story_context,
            module=module,
            table=module,
            target_record=target,
            actor_role=role,
            preconditions=preconditions,
            test_data=test_data,
            ordered_steps=steps,
            final_assertions=assertions,
            risk_level=priority,
        )

    # ------------------------------------------------------------------
    # Assertion parsing
    # ------------------------------------------------------------------

    def _parse_assertion(self, raw_assert: str) -> tuple[str, str, str]:
        """Parse an expected-result line into (field, operator, value).

        Never raises; unparsable lines become an overall_state contains
        assertion so the text is still verified semantically.
        """
        text = re.sub(
            r"^(?:step\s*\d+\s*[:\-\.]|\d+[\.\)]\s*)",
            "",
            raw_assert,
            flags=re.IGNORECASE,
        ).strip()

        parts = [p.strip() for p in text.split("|") if p.strip()]
        if len(parts) >= 3:
            return parts[0], parts[1], parts[-1]
        if len(parts) == 2:
            return parts[0], "equals", parts[1]

        if ":" in text:
            k, v = text.split(":", 1)
            return k.strip(), "equals", v.strip()
        if "=" in text:
            k, v = text.split("=", 1)
            return k.strip(), "equals", v.strip()
        return "overall_state", "contains", text
