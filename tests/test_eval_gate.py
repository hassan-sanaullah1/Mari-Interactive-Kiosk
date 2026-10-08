"""The retrieval eval's regression gate, which decides whether a refactor may land.

A gate that passes everything is worse than no gate, so its own arithmetic is tested
here rather than trusted.
"""

from __future__ import annotations

import pytest

from eval.run_eval import LATENCY_TOLERANCE, TOLERANCE, compare_to_baseline

BASELINE = {
    "backend": "hybrid",
    "hit@1": 0.784,
    "hit@3": 0.950,
    "hit@5": 0.974,
    "mrr": 0.833,
    "fact_recall": 0.993,
    "abstain_rate": 1.0,
    "latency_ms": {"p50": 60.0, "p95": 300.0, "mean": 90.0},
}


def _report(**overrides) -> dict:
    return {**BASELINE, **overrides}


def test_identical_report_passes() -> None:
    assert compare_to_baseline(_report(), BASELINE) == []


def test_improvement_passes() -> None:
    better = _report(**{"hit@1": 0.85, "mrr": 0.90})
    assert compare_to_baseline(better, BASELINE) == []


def test_small_hit1_dip_is_tolerated_as_tie_noise() -> None:
    """hit@1 swings by about a point between runs on tied chunks alone."""
    within = _report(**{"hit@1": BASELINE["hit@1"] - TOLERANCE["hit@1"] + 0.001})
    assert compare_to_baseline(within, BASELINE) == []


def test_real_hit1_drop_is_caught() -> None:
    dropped = _report(**{"hit@1": BASELINE["hit@1"] - 0.05})
    regressions = compare_to_baseline(dropped, BASELINE)
    assert len(regressions) == 1
    assert "hit@1" in regressions[0]


@pytest.mark.parametrize("metric", ["hit@3", "hit@5", "mrr", "fact_recall"])
def test_each_quality_metric_is_gated(metric) -> None:
    dropped = _report(**{metric: BASELINE[metric] - 0.05})
    assert any(metric in line for line in compare_to_baseline(dropped, BASELINE))


def test_abstain_rate_has_no_slack() -> None:
    """Answering a question the corpus cannot support is never noise."""
    assert TOLERANCE["abstain_rate"] == 0.0
    dropped = _report(abstain_rate=0.99)
    assert any("abstain_rate" in line for line in compare_to_baseline(dropped, BASELINE))


def test_latency_within_tolerance_passes() -> None:
    slower = _report(latency_ms={**BASELINE["latency_ms"], "p50": 60.0 * LATENCY_TOLERANCE})
    assert compare_to_baseline(slower, BASELINE) == []


def test_latency_regression_is_caught() -> None:
    slower = _report(latency_ms={**BASELINE["latency_ms"], "p50": 120.0})
    assert any("p50" in line for line in compare_to_baseline(slower, BASELINE))


def test_several_regressions_are_all_reported() -> None:
    """One run should show everything that fell, not just the first thing."""
    bad = _report(**{"hit@1": 0.5, "mrr": 0.4, "fact_recall": 0.5})
    assert len(compare_to_baseline(bad, BASELINE)) == 3


def test_missing_metric_is_skipped_not_failed() -> None:
    """An older baseline without a metric must not read as a regression."""
    older = {key: value for key, value in BASELINE.items() if key != "mrr"}
    assert compare_to_baseline(_report(), older) == []
