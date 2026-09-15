"""Excel-based Test Case Importer.

Ingests human-authored test cases (XLSX) and maps them to GeneratedTestCase models.
Supports columns:
- ID
- Story / Goal
- Module
- Target Record
- Actor Role
- Preconditions (newline separated)
- Steps (newline separated, e.g., '1. step one|expected outcome')
- Final Assertions (newline separated)
- Risk Level
"""

import uuid
from typing import Any

from openpyxl import load_workbook

from agent.domain.story import GeneratedTestCase, TestStep, ExpectedAssertion, AcceptanceCriterion
from agent.core.logging import get_logger

logger = get_logger(__name__)


class TestCaseImporter:
    """Parses Excel test cases into GeneratedTestCase models."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    def parse(self) -> list[GeneratedTestCase]:
        """Parse the XLSX file into a list of GeneratedTestCase objects."""
        logger.info("parsing_test_cases_from_excel", file=self.file_path)
        try:
            wb = load_workbook(filename=self.file_path, data_only=True)
            ws = wb.active
        except Exception as e:
            logger.error("excel_load_error", error=str(e), file=self.file_path)
            raise ValueError(f"Failed to load Excel file: {e}")

        test_cases = []

        # Read header to map column names to indices
        headers = {}
        for col_idx, cell in enumerate(next(ws.iter_rows(min_row=1, max_row=1)), 1):
            if cell.value:
                headers[str(cell.value).strip().lower()] = col_idx - 1

        if not headers:
            return test_cases

        # Map common aliases
        col_map = {
            "id": self._find_col(headers, ["id", "test case id", "tc_id", "test id"]),
            "story": self._find_col(headers, ["story", "user story", "goal", "description"]),
            "module": self._find_col(headers, ["module", "table", "area"]),
            "target": self._find_col(headers, ["target", "target record", "record", "incident"]),
            "role": self._find_col(headers, ["role", "actor", "actor role", "persona"]),
            "preconditions": self._find_col(headers, ["preconditions", "prerequisites"]),
            "steps": self._find_col(headers, ["steps", "action", "actions", "execution steps"]),
            "expected_results": self._find_col(headers, ["expected", "expected result", "final assertions"]),
            "risk": self._find_col(headers, ["risk", "risk level", "priority"]),
        }

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
            if not any(row):  # skip empty rows
                continue

            tc_id = str(row[col_map["id"]] or f"TC-AUTO-{uuid.uuid4().hex[:6].upper()}") if col_map["id"] is not None else f"TC-AUTO-{uuid.uuid4().hex[:6].upper()}"
            story = str(row[col_map["story"]] or "Human Authored Test Case") if col_map["story"] is not None else "Human Authored Test Case"
            module = str(row[col_map["module"]] or "incident") if col_map["module"] is not None else "incident"
            target = str(row[col_map["target"]]) if col_map["target"] is not None and row[col_map["target"]] else None
            role = str(row[col_map["role"]] or "admin") if col_map["role"] is not None else "admin"
            risk = str(row[col_map["risk"]] or "Medium") if col_map["risk"] is not None else "Medium"
            
            # Parse lists
            preconditions = []
            if col_map["preconditions"] is not None and row[col_map["preconditions"]]:
                preconditions = [p.strip() for p in str(row[col_map["preconditions"]]).split('\n') if p.strip()]

            # Parse steps (format: "Action | Expected Outcome")
            steps = []
            if col_map["steps"] is not None and row[col_map["steps"]]:
                raw_steps = [s.strip() for s in str(row[col_map["steps"]]).split('\n') if s.strip()]
                for i, raw_step in enumerate(raw_steps, 1):
                    parts = raw_step.split('|')
                    action = parts[0].strip()
                    expected = parts[1].strip() if len(parts) > 1 else "Action completes successfully"
                    
                    # Naive parsing for simple text actions like 'fill username with admin'
                    action_type = "navigate"
                    target = ""
                    value = ""
                    if " " in action:
                        action_type, rest = action.split(" ", 1)
                        if " " in rest:
                            target, value = rest.split(" ", 1)
                        else:
                            target = rest
                    
                    steps.append(TestStep(
                        step_number=i,
                        action_type=action_type.lower(),
                        target=target,
                        value=value,
                        expected_outcome=expected
                    ))

            # Parse assertions
            assertions = []
            if col_map["expected_results"] is not None and row[col_map["expected_results"]]:
                raw_assertions = [a.strip() for a in str(row[col_map["expected_results"]]).split('\n') if a.strip()]
                for j, raw_assert in enumerate(raw_assertions, 1):
                    parts = raw_assert.split('|')
                    target_field = parts[0].strip()
                    operator = parts[1].strip() if len(parts) > 2 else "equals"
                    value = parts[-1].strip() if len(parts) > 1 else target_field
                    
                    if len(parts) == 1:
                        target_field = "overall_state"
                        value = parts[0].strip()
                    
                    assertions.append(ExpectedAssertion(
                        assertion_id=f"AST-{j}",
                        field=target_field,
                        operator=operator,
                        expected_value=value
                    ))

            tc = GeneratedTestCase(
                id=tc_id,
                source_user_story=story,
                module=module,
                table=module,
                target_record=target,
                actor_role=role,
                preconditions=preconditions,
                ordered_steps=steps,
                final_assertions=assertions,
                risk_level=risk
            )
            test_cases.append(tc)

        logger.info("excel_parsing_complete", num_cases=len(test_cases))
        return test_cases

    def _find_col(self, headers: dict[str, int], aliases: list[str]) -> int | None:
        """Find a column index matching any of the aliases."""
        for alias in aliases:
            for header, idx in headers.items():
                if alias in header:
                    return idx
        return None
