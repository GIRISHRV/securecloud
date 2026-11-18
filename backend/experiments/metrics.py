"""Dependency-free classification and prevention metrics."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean


@dataclass(frozen=True)
class ScoredLabel:
    score: float
    label: bool
    predicted: bool


def safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def average_precision(items: list[ScoredLabel]) -> float | None:
    """Average precision, the step-wise area under the precision-recall curve."""
    positives = sum(item.label for item in items)
    if positives == 0:
        return None
    ranked = sorted(items, key=lambda item: item.score, reverse=True)
    true_positives = 0
    precision_at_positive: list[float] = []
    for rank, item in enumerate(ranked, start=1):
        if item.label:
            true_positives += 1
            precision_at_positive.append(true_positives / rank)
    return sum(precision_at_positive) / positives


def classification_metrics(items: list[ScoredLabel]) -> dict:
    tp = sum(item.predicted and item.label for item in items)
    fp = sum(item.predicted and not item.label for item in items)
    fn = sum(not item.predicted and item.label for item in items)
    tn = sum(not item.predicted and not item.label for item in items)
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": safe_ratio(fp, fp + tn),
        "pr_auc_average_precision": average_precision(items),
    }


def mean_or_none(values: list[float | None]) -> float | None:
    observed = [value for value in values if value is not None]
    return mean(observed) if observed else None


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    """Two-sided Wilson score interval for a binomial proportion."""
    if total <= 0:
        return None, None
    proportion = successes / total
    denominator = 1 + (z * z / total)
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * sqrt((proportion * (1 - proportion) / total) + (z * z / (4 * total * total)))
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)
