# -*- coding: utf-8 -*-
"""
workbench/sweep.py — 파라미터 스윕
===================================
전략 파라미터를 범위로 지정하면 모든 조합을 실행하고 순위를 매김.

사용법:
  from aftertaxi.workbench.sweep import run_sweep, SweepConfig

  sweep = SweepConfig(
      base_payload={"strategy": {"type": "custom"}, "accounts": [...]},
      param_grid={"weights.SPY": [0.4, 0.5, 0.6, 0.7],
                  "weights.SSO": [0.3, 0.4, 0.5, 0.6]},
  )
  result = run_sweep(sweep, returns, prices, fx)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import copy
import numpy as np
import pandas as pd


@dataclass
class SweepConfig:
    """스윕 설정."""
    base_payload: dict
    param_grid: Dict[str, List[Any]]  # "path.to.field": [val1, val2, ...]
    # 비중 파라미터는 합 1.0 강제
    normalize_weights: bool = True


@dataclass
class SweepResult:
    """스윕 결과."""
    rows: List[Dict]  # [{params, mult_after_tax, mdd, tax_drag, ...}, ...]
    best: Dict = field(default_factory=dict)
    worst: Dict = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def summary_text(self) -> str:
        if not self.rows:
            return "결과 없음"
        lines = [f"스윕 결과: {len(self.rows)}개 조합"]
        if self.best:
            lines.append(f"최고: {self.best.get('label', '?')} → {self.best.get('mult_after_tax', 0):.2f}x")
        if self.worst:
            lines.append(f"최저: {self.worst.get('label', '?')} → {self.worst.get('mult_after_tax', 0):.2f}x")
        return "\n".join(lines)


def _set_nested(d: dict, path: str, value: Any) -> dict:
    """점 경로로 중첩 dict에 값 설정. e.g. "weights.SPY" → d["weights"]["SPY"]"""
    keys = path.split(".")
    current = d
    for k in keys[:-1]:
        if k not in current:
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value
    return d


def _generate_combos(param_grid: Dict[str, List]) -> List[Dict[str, Any]]:
    """파라미터 그리드 → 모든 조합 생성."""
    import itertools
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = []
    for vals in itertools.product(*values):
        combos.append(dict(zip(keys, vals)))
    return combos


def run_sweep(
    config: SweepConfig,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
) -> SweepResult:
    """파라미터 스윕 실행."""
    from aftertaxi.strategies.compile import compile_backtest
    from aftertaxi.core.facade import run_backtest
    from aftertaxi.core.attribution import build_attribution

    combos = _generate_combos(config.param_grid)
    rows = []

    for combo in combos:
        payload = copy.deepcopy(config.base_payload)

        # 파라미터 적용
        for path, value in combo.items():
            # strategy.weights.SPY → payload["strategy"]["weights"]["SPY"]
            if path.startswith("strategy."):
                sub_path = path[len("strategy."):]
                if "strategy" not in payload:
                    payload["strategy"] = {}
                strat = payload["strategy"]
                if sub_path.startswith("weights."):
                    asset = sub_path[len("weights."):]
                    if "weights" not in strat:
                        strat["weights"] = {}
                    strat["weights"][asset] = value
                else:
                    strat[sub_path] = value
            elif path.startswith("accounts."):
                # accounts.0.monthly_contribution 등
                parts = path[len("accounts."):].split(".", 1)
                idx = int(parts[0])
                field_name = parts[1] if len(parts) > 1 else None
                accts = payload.get("accounts", [])
                while len(accts) <= idx:
                    accts.append({})
                if field_name:
                    accts[idx][field_name] = value
                payload["accounts"] = accts
            else:
                payload[path] = value

        # 비중 정규화
        if config.normalize_weights:
            weights = payload.get("strategy", {}).get("weights", {})
            if weights:
                total = sum(weights.values())
                if total > 0 and abs(total - 1.0) > 0.01:
                    payload["strategy"]["weights"] = {k: v / total for k, v in weights.items()}

        # 실행
        try:
            cfg = compile_backtest(payload)
            result = run_backtest(cfg, returns=returns, prices=prices, fx_rates=fx_rates)
            attr = build_attribution(result)

            label = ", ".join(f"{k}={v}" for k, v in combo.items())
            rows.append({
                "label": label,
                **combo,
                "mult_after_tax": result.mult_after_tax,
                "mdd": result.mdd,
                "tax_drag_pct": attr.tax_drag_pct,
                "net_pv_krw": result.net_pv_krw,
            })
        except Exception as e:
            label = ", ".join(f"{k}={v}" for k, v in combo.items())
            rows.append({"label": label, **combo, "error": str(e)})

    # 정렬
    valid = [r for r in rows if "error" not in r]
    if valid:
        valid.sort(key=lambda r: r["mult_after_tax"], reverse=True)
        best = valid[0]
        worst = valid[-1]
    else:
        best, worst = {}, {}

    return SweepResult(rows=rows, best=best, worst=worst)
