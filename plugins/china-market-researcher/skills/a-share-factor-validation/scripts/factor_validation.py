#!/usr/bin/env python3
"""Dependency-light, auditable A-share factor validation primitives.

Input rows must already be point-in-time clean and contain ``date``,
``ts_code``, ``factor`` and ``forward_return``. ``forward_return`` is the return
from the first permitted execution time after the signal, never a same-close
return. This module evaluates evidence; it does not place orders.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _date(value: Any) -> str:
    text = str(value).replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError("date must be YYYYMMDD")
    date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return text


def validate_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    required = {"date", "ts_code", "factor", "forward_return"}
    output: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for number, raw in enumerate(rows, 1):
        missing = required - set(raw)
        if missing:
            raise ValueError(f"row {number} missing {sorted(missing)}")
        row = dict(raw)
        row["date"] = _date(row["date"])
        row["ts_code"] = str(row["ts_code"]).upper()
        row["factor"] = _finite(row["factor"], "factor")
        row["forward_return"] = _finite(row["forward_return"], "forward_return")
        row["tradable"] = str(row.get("tradable", "true")).lower() not in {"0", "false", "no", "n"}
        marker = (row["date"], row["ts_code"])
        if marker in seen:
            raise ValueError(f"duplicate date/security key: {marker}")
        seen.add(marker)
        output.append(row)
    return sorted(output, key=lambda row: (row["date"], row["ts_code"]))


def _ranks(values: Sequence[float]) -> List[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][1] == ordered[position][1]:
            end += 1
        average_rank = (position + 1 + end) / 2.0
        for cursor in range(position, end):
            result[ordered[cursor][0]] = average_rank
        position = end
    return result


def spearman(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) != len(right) or len(left) < 3:
        return None
    x, y = _ranks(left), _ranks(right)
    mean_x, mean_y = statistics.mean(x), statistics.mean(y)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - mean_x) ** 2 for a in x) * sum((b - mean_y) ** 2 for b in y))
    return numerator / denominator if denominator else None


def cross_sectional_ic(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("tradable", True):
            grouped[str(row["date"])].append(row)
    output: List[Dict[str, Any]] = []
    for day, items in sorted(grouped.items()):
        value = spearman([float(row["factor"]) for row in items], [float(row["forward_return"]) for row in items])
        if value is not None:
            output.append({"date": day, "ic": value, "coverage": len(items)})
    return output


def block_bootstrap_mean(
    values: Sequence[float], *, block_length: int = 5, iterations: int = 2000, seed: int = 0
) -> Dict[str, Optional[float]]:
    if not values:
        return {"mean": None, "ci_low": None, "ci_high": None}
    if block_length < 1 or iterations < 100:
        raise ValueError("block_length >= 1 and iterations >= 100 are required")
    rng = random.Random(seed)
    size = len(values)
    samples: List[float] = []
    for _ in range(iterations):
        draw: List[float] = []
        while len(draw) < size:
            start = rng.randrange(size)
            draw.extend(values[(start + offset) % size] for offset in range(block_length))
        samples.append(statistics.mean(draw[:size]))
    samples.sort()
    return {
        "mean": statistics.mean(values),
        "ci_low": samples[int(iterations * 0.025)],
        "ci_high": samples[min(iterations - 1, int(iterations * 0.975))],
    }


def benjamini_hochberg(p_values: Mapping[str, float], q: float = 0.05) -> Dict[str, Dict[str, Any]]:
    if not 0 < q < 1:
        raise ValueError("q must be between 0 and 1")
    ordered = sorted(
        ((name, _finite(value, "p_value")) for name, value in p_values.items()),
        key=lambda item: item[1],
    )
    count = len(ordered)
    adjusted: Dict[str, float] = {}
    running = 1.0
    for rank in range(count, 0, -1):
        name, value = ordered[rank - 1]
        running = min(running, value * count / rank)
        adjusted[name] = min(1.0, running)
    return {
        name: {"p_value": value, "adjusted_p": adjusted[name], "fdr_reject": adjusted[name] <= q}
        for name, value in ordered
    }


def purged_walk_forward(
    dates: Sequence[str], *, test_size: int, min_train_size: int, purge_days: int = 1, embargo_days: int = 0
) -> List[Dict[str, List[str]]]:
    unique = sorted({_date(value) for value in dates})
    if min(test_size, min_train_size) < 1 or min(purge_days, embargo_days) < 0:
        raise ValueError("invalid split sizes")
    splits: List[Dict[str, List[str]]] = []
    test_start = min_train_size + purge_days
    while test_start + test_size <= len(unique):
        train_end = test_start - purge_days
        train = unique[:train_end]
        test = unique[test_start:test_start + test_size]
        if embargo_days:
            train = [item for item in train if item < test[0]][:-embargo_days] or []
        splits.append({"train": train, "test": test})
        test_start += test_size
    return splits


def long_short_backtest(
    rows: Sequence[Mapping[str, Any]], *, quantile: float = 0.2, cost_bps: float = 10.0
) -> Dict[str, Any]:
    if not 0 < quantile <= 0.5 or cost_bps < 0:
        raise ValueError("quantile must be in (0, .5] and cost_bps nonnegative")
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("tradable", True):
            grouped[str(row["date"])].append(row)
    previous: Dict[str, float] = {}
    daily: List[Dict[str, Any]] = []
    trades = 0
    for day, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda row: float(row["factor"]))
        bucket = max(1, int(len(ordered) * quantile))
        if len(ordered) < bucket * 2:
            continue
        short, long = ordered[:bucket], ordered[-bucket:]
        weights = {str(row["ts_code"]): 0.5 / bucket for row in long}
        weights.update({str(row["ts_code"]): -0.5 / bucket for row in short})
        gross = sum(weights[str(row["ts_code"])] * float(row["forward_return"]) for row in long + short)
        names = set(previous) | set(weights)
        turnover = sum(abs(weights.get(name, 0.0) - previous.get(name, 0.0)) for name in names)
        trades += sum(1 for name in names if weights.get(name, 0.0) != previous.get(name, 0.0))
        net = gross - turnover * cost_bps / 10000.0
        daily.append({"date": day, "gross_return": gross, "net_return": net, "turnover": turnover})
        previous = weights
    returns = [row["net_return"] for row in daily]
    equity, peak, max_drawdown = 1.0, 1.0, 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    sharpe = None
    if len(returns) > 1 and statistics.stdev(returns) > 0:
        sharpe = statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(252)
    wins = sum(value > 0 for value in returns)
    return {
        "dates": len(daily),
        "trade_events": trades,
        "gross_total_return": math.prod(1 + row["gross_return"] for row in daily) - 1 if daily else None,
        "net_total_return": equity - 1 if daily else None,
        "annualized_sharpe": sharpe,
        "max_drawdown": max_drawdown if daily else None,
        "winning_dates": wins,
        "date_win_rate": wins / len(returns) if returns else None,
        "round_trip_trade_win_rate": None,
        "win_rate_note": "date_win_rate is the fraction of positive portfolio dates; round-trip win rate requires an explicit lot-level position ledger and is not inferred here.",
        "average_turnover": statistics.mean(row["turnover"] for row in daily) if daily else None,
        "daily": daily,
        "execution_contract": "forward_return begins after signal availability; caller must enforce T+1, limits and suspension flags",
    }


def cscv_probability_of_backtest_overfit(config_returns: Mapping[str, Sequence[float]]) -> Dict[str, Any]:
    names = sorted(config_returns)
    if len(names) < 2:
        raise ValueError("at least two configurations are required")
    lengths = {len(config_returns[name]) for name in names}
    if len(lengths) != 1 or next(iter(lengths)) < 4:
        raise ValueError("configuration return vectors must share at least four observations")
    observations = next(iter(lengths))
    block_count = min(10, observations if observations % 2 == 0 else observations - 1)
    if block_count < 4:
        raise ValueError("insufficient observations for CSCV")
    blocks = [list(range(start, observations, block_count)) for start in range(block_count)]
    logits: List[float] = []
    for selected in itertools.combinations(range(block_count), block_count // 2):
        insample = {index for block in selected for index in blocks[block]}
        outsample = [index for index in range(observations) if index not in insample]
        best = max(names, key=lambda name: statistics.mean(config_returns[name][index] for index in insample))
        ordered = sorted(names, key=lambda name: statistics.mean(config_returns[name][index] for index in outsample))
        rank = ordered.index(best) + 1
        relative_rank = (rank - 0.5) / len(names)
        logits.append(math.log(relative_rank / (1 - relative_rank)))
    return {
        "pbo": sum(value <= 0 for value in logits) / len(logits),
        "combinations": len(logits),
        "block_count": block_count,
        "interpretation": "selection-overfit diagnostic, not a probability that live performance will fail",
    }


def future_perturbation_invariant(
    original: Sequence[Mapping[str, Any]], perturbed: Sequence[Mapping[str, Any]], *, cutoff: str
) -> bool:
    key = _date(cutoff)
    left = validate_rows([row for row in original if _date(row["date"]) <= key])
    right = validate_rows([row for row in perturbed if _date(row["date"]) <= key])
    return left == right and cross_sectional_ic(left) == cross_sectional_ic(right)


def analyze(rows: Sequence[Mapping[str, Any]], *, cost_bps: float = 10.0, seed: int = 0) -> Dict[str, Any]:
    clean = validate_rows(rows)
    ic = cross_sectional_ic(clean)
    ic_values = [row["ic"] for row in ic]
    return {
        "status": "inconclusive",
        "decision_status_requires_preregistered_gates": True,
        "observations": len(clean),
        "dates": len({row["date"] for row in clean}),
        "securities": len({row["ts_code"] for row in clean}),
        "ic": block_bootstrap_mean(ic_values, seed=seed),
        "backtest": long_short_backtest(clean, cost_bps=cost_bps),
        "limitations": [
            "No production claim: live data permissions, corporate actions, auction fills and capacity remain external validations.",
            "This runner never promotes a factor automatically; preregistered economic, statistical, robustness and implementation gates must be evaluated outside this summary.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with args.csv_file.open(newline="", encoding="utf-8-sig") as stream:
        report = analyze(list(csv.DictReader(stream)), cost_bps=args.cost_bps, seed=args.seed)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
