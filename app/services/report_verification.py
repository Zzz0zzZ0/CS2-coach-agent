"""Verify the deterministic report contract against normalized demo input.

Recomputation detects stale or altered metrics, citations and report text. It is
not an independent parser, an NLP fact checker, or a coaching-quality judgment.
"""

from app.agentic.nodes.analyst_node import render_analyst_report
from app.agentic.nodes.coach_node import _PRIORITIES, _render_report
from app.services.metrics_service import build_current_match_evidence, calculate_metrics


def _differences(expected, actual, path):
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                yield {"path": f"{path}.{key}", "reason": "missing_or_extra_field"}
            else:
                yield from _differences(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            yield {"path": path, "reason": "length_mismatch", "expected": len(expected), "actual": len(actual)}
        for index, (left, right) in enumerate(zip(expected, actual)):
            yield from _differences(left, right, f"{path}[{index}]")
    elif expected != actual or isinstance(expected, bool) != isinstance(actual, bool):
        yield {"path": path, "reason": "value_mismatch", "expected": expected, "actual": actual}


def _check(name, expected, actual, checked_count):
    differences = list(_differences(expected, actual, name))
    return {"id": name, "status": "fail" if differences else "pass",
            "checked_count": checked_count, "mismatch_count": len(differences),
            "mismatches": differences[:20]}


def verify_report_facts(state: dict) -> dict:
    result = {
        "scope": "deterministic_report_contract",
        "checks": [],
        "limitations": [
            "核验范围为规范化输入、派生指标、当前来源与固定报告模板的一致性。",
            "复用指标计算与报告模板，不是独立解析器或通用自然语言事实核验。",
            "不核验历史证据正文、战术因果或训练建议质量。",
        ],
    }
    match = state.get("match")
    if not isinstance(match, dict) or not isinstance(match.get("rounds"), list):
        result["checks"] = [{"id": "source_input", "status": "not_checked",
                             "reason": "normalized_round_input_unavailable"}]
        return result

    rounds = match["rounds"]
    numbers = [row.get("round_number") for row in rounds
               if isinstance(row, dict)]
    valid_numbers = (len(numbers) == len(rounds)
                     and all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in numbers))
    valid_numbers = valid_numbers and len(set(numbers)) == len(numbers)
    if not valid_numbers:
        result["checks"] = [{"id": "source_input", "status": "fail",
                             "reason": "round_numbers_must_be_unique_positive_integers"}]
        return result

    # The normalized event payload is the source of truth, never the report's
    # own metrics or evidence. This also catches jointly corrupted output fields.
    try:
        metrics = calculate_metrics(rounds)
        evidence = build_current_match_evidence(match, metrics)
    except (TypeError, ValueError, KeyError, AttributeError):
        result["checks"] = [{"id": "source_input", "status": "fail",
                             "reason": "normalized_round_input_invalid"}]
        return result

    result["checks"].append(_check("source_metrics", metrics, state.get("metrics", {}), len(metrics)))
    # Retrieval rank scores are not facts. Source identity, scope and body are.
    fields = ("source_id", "metadata", "content")
    actual_evidence = state.get("current_evidence", [])
    expected_sources = [{key: item.get(key) for key in fields} for item in evidence]
    actual_sources = [{key: item.get(key) for key in fields} if isinstance(item, dict) else item
                      for item in actual_evidence] if isinstance(actual_evidence, list) else actual_evidence
    result["checks"].append(_check("source_evidence", expected_sources, actual_sources, len(evidence)))

    decision = state.get("coach_decision")
    priorities = decision.get("priority_ids") if isinstance(decision, dict) else None
    valid_priorities = (isinstance(priorities, list) and bool(priorities)
                        and len(priorities) <= 3
                        and all(isinstance(p, str) and p in _PRIORITIES for p in priorities)
                        and len(set(priorities)) == len(priorities))
    if not valid_priorities:
        result["checks"].append({"id": "coach_priorities", "status": "fail",
                                 "reason": "missing_or_invalid_priority_ids"})

    reports = {"analyst_report": render_analyst_report(match, metrics)}
    if valid_priorities:
        reports["coach_report"] = _render_report(metrics, priorities)
    for name, expected in reports.items():
        field = "coach_advice" if name == "coach_report" else name
        # Keep every line: missing caveats, extra claims and changes to a valid
        # citation's round association must fail, even if all IDs exist.
        expected_lines = expected.splitlines()
        actual_lines = str(state.get(field, "")).splitlines()
        result["checks"].append(_check(name, expected_lines, actual_lines, len(expected_lines)))
    return result
