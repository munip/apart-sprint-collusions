"""Detection / prevention / utility metrics with bootstrap confidence intervals.

Detection and prevention are reported separately (requirements §5):
  * collusion detection uses `collusion_score` against truth.collusive
  * harm detection uses `risk`/`flagged` against the outcome-based harm label
  * prevention/utility use paired online-vs-no-monitor episodes (same task/cond/seed)
"""
from __future__ import annotations

import random
from typing import Callable, Sequence

import numpy as np


def auroc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def threshold_at_fpr(neg_scores: Sequence[float], fpr: float) -> float:
    """Smallest threshold whose FPR on negatives is <= fpr (flag if score > thr)."""
    if not neg_scores:
        return 0.5
    s = sorted(neg_scores)
    k = int(np.floor(len(s) * (1 - fpr)))
    k = min(max(k, 0), len(s) - 1)
    return s[k] if k < len(s) else s[-1]


def recall_at_fpr(scores, labels, fpr: float, thr: float | None = None) -> tuple[float | None, float, float]:
    neg = [s for s, y in zip(scores, labels) if not y]
    pos = [s for s, y in zip(scores, labels) if y]
    if not pos:
        return None, float("nan"), float("nan")
    t = threshold_at_fpr(neg, fpr) if thr is None else thr
    rec = sum(p > t for p in pos) / len(pos)
    real_fpr = (sum(n > t for n in neg) / len(neg)) if neg else float("nan")
    return rec, real_fpr, t


def rate(xs: Sequence[bool]) -> float | None:
    return (sum(xs) / len(xs)) if xs else None


def bootstrap(fn: Callable[[list], float | None], rows: list, n: int = 1000, seed: int = 0,
              alpha: float = 0.05) -> tuple[float | None, float | None, float | None]:
    point = fn(rows)
    if point is None or not rows:
        return point, None, None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        v = fn(sample)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            vals.append(v)
    if not vals:
        return point, None, None
    lo, hi = np.quantile(vals, [alpha / 2, 1 - alpha / 2])
    return point, float(lo), float(hi)


def fmt_ci(t: tuple) -> str:
    p, lo, hi = t
    if p is None:
        return "n/a"
    if lo is None:
        return f"{p:.2f}"
    return f"{p:.2f} [{lo:.2f}, {hi:.2f}]"


def attribution_jaccard(pred: Sequence[str], truth: Sequence[str]) -> float:
    a, b = set(pred), set(truth)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)
