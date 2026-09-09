from scripts.evaluate_hard_cases import HARD_CASES, main


def test_hard_case_suite_has_safety_coverage():
    names = {name for name, _ in HARD_CASES}
    for required in {"missing-evidence", "contradictory-evidence", "high-value-ceiling", "prompt-injection-notes", "graph-escalation"}:
        assert required in names


def test_hard_case_report_passes():
    report = main()
    assert report["passed"] >= 6
