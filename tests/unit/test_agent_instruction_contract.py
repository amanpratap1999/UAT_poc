"""Guard the canonical repository contract and tool-specific entrypoints."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CANONICAL_DOCS = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    "DECISIONS.md",
    "README.md",
)

ENTRYPOINTS = (
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    ".agents/rules/uat-poc.md",
)


def test_canonical_project_contract_documents_exist() -> None:
    for relative_path in CANONICAL_DOCS:
        path = ROOT / relative_path
        assert path.is_file(), f"Missing canonical project contract: {relative_path}"


def test_all_agent_entrypoints_direct_to_canonical_contract() -> None:
    for relative_path in ENTRYPOINTS:
        path = ROOT / relative_path
        assert path.is_file(), f"Missing agent entrypoint: {relative_path}"
        content = path.read_text(encoding="utf-8")
        for canonical_doc in CANONICAL_DOCS:
            assert canonical_doc in content, (
                f"{relative_path} must direct agents to {canonical_doc}"
            )
        text = content.lower()
        assert "before" in text and "read" in text, (
            f"{relative_path} must explicitly require reading the contract before work"
        )

def test_canonical_agent_contract_documents_tool_native_entrypoint_exception() -> None:
    content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for entrypoint in (
        "CLAUDE.md",
        "GEMINI.md",
        ".github/copilot-instructions.md",
        ".agents/rules/*.md",
    ):
        assert entrypoint in content, (
            f"AGENTS.md must document the supported entrypoint exception: {entrypoint}"
        )

