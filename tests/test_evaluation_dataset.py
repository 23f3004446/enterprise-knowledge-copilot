import json
from pathlib import Path

from app.core.config import settings


def test_evaluation_dataset_has_30_mixed_cases() -> None:
    cases = json.loads(Path(settings.evaluation_questions_path).read_text(encoding="utf-8"))
    assert len(cases) == 30
    assert {case["role"] for case in cases} == {"EMPLOYEE", "MANAGER", "ADMIN"}
    assert any(case["answerable"] for case in cases)
    assert any(not case["answerable"] for case in cases)
    assert all({"query", "role", "expected_sources", "answerable"} <= case.keys() for case in cases)
