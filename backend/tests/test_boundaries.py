import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import ProfileCreate

APP_DIR = Path(__file__).resolve().parents[1] / "app"

FORBIDDEN_IMPORTS = {
    "openai",
    "anthropic",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langgraph",
    "litellm",
    "transformers",
}


def payload(**overrides):
    base = {
        "applicant_name": "Demo Applicant",
        "village_id": "demo-nashik-a",
        "own_capital_paise": 5_000_000,
    }
    return base | overrides


@pytest.mark.parametrize("invalid_money", [12.5, "100", True, -1])
def test_money_rejects_invalid_values(invalid_money):
    with pytest.raises(ValidationError):
        ProfileCreate(**payload(own_capital_paise=invalid_money))


def test_money_is_integer_paise():
    profile = ProfileCreate(**payload())
    assert type(profile.own_capital_paise) is int
    assert profile.own_capital_paise == 5_000_000


def test_skills_are_deduplicated():
    profile = ProfileCreate(
        **payload(skills=["farming", "farming"])
    )
    assert profile.skills == ["farming"]


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        ProfileCreate(**payload(invented_credit_score=720))


def test_finance_and_viability_have_no_direct_llm_imports():
    for module in ("fin", "viability"):
        for path in (APP_DIR / module).rglob("*.py"):
            tree = ast.parse(path.read_text())

            for node in ast.walk(tree):
                roots = []

                if isinstance(node, ast.Import):
                    roots = [
                        alias.name.split(".")[0]
                        for alias in node.names
                    ]

                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots = [node.module.split(".")[0]]

                assert not FORBIDDEN_IMPORTS.intersection(roots), (
                    f"Forbidden LLM import in {path}"
                )


def test_finance_and_viability_never_import_app_llm():
    for module in ("fin", "viability"):
        for path in (APP_DIR / module).rglob("*.py"):
            tree = ast.parse(path.read_text())

            for node in ast.walk(tree):
                modules = []

                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]

                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]

                assert not any(
                    name == "app.llm" or name.startswith("app.llm.")
                    for name in modules
                ), f"Forbidden app.llm import in {path}"
