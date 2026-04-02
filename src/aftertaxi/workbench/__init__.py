# -*- coding: utf-8 -*-
"""
workbench/run.py — 워크벤치 실행 파이프라인
============================================
JSON payload → compile → engine → attribution → workbench-ready 출력.

사용법:
  from aftertaxi.workbench.run import run_workbench

  payloads = [
      {"strategy": {"type": "q60s40"}, "accounts": [{"type": "TAXABLE"}]},
      {"strategy": {"type": "spy_bnh"}, "accounts": [{"type": "TAXABLE"}]},
  ]

  results = run_workbench(payloads, returns=returns, prices=prices, fx_rates=fx)
  # → List[dict] (workbench UI 소비 가능)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from aftertaxi.core.contracts import EngineResult
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.attribution import build_attribution
from aftertaxi.core.workbench_adapter import to_workbench_payload, to_workbench_json
from aftertaxi.strategies.compile import compile_backtest
from aftertaxi.validation import validate


def run_workbench(
    strategy_payloads: List[dict],
    *,
    returns: pd.DataFrame,
    prices: Optional[pd.DataFrame] = None,
    fx_rates: pd.Series,
    include_validation: bool = False,
) -> List[Dict[str, Any]]:
    """전략 비교 워크벤치 실행.

    Parameters
    ----------
    strategy_payloads : 전략별 JSON/dict 리스트
    returns : 월간 수익률 DataFrame
    prices : 가격 DataFrame (None이면 returns에서 역산)
    fx_rates : FX 환율 Series
    include_validation : True면 각 전략에 validation summary 추가

    Returns
    -------
    list of workbench-ready dicts
    """
    results = []

    for payload in strategy_payloads:
        # 1. compile
        config = compile_backtest(payload)
        strategy_name = config.strategy.name
        description = payload.get("description", "")

        # 2. engine
        engine_result = run_backtest(
            config,
            returns=returns,
            prices=prices,
            fx_rates=fx_rates,
        )

        # 3. attribution
        attribution = build_attribution(engine_result)

        # 4. workbench payload
        wb = to_workbench_payload(
            engine_result,
            strategy_name=strategy_name,
            description=description,
            attribution=attribution,
        )

        # 5. person-scope 추가
        wb["person"] = {
            "health_insurance_krw": engine_result.person.health_insurance_krw,
        }

        # 6. validation (optional)
        if include_validation:
            excess = engine_result.monthly_values
            if len(excess) > 1:
                import numpy as np
                pct = np.diff(excess) / excess[:-1]
                pct = pct[~np.isnan(pct)]
                report = validate(
                    result=engine_result,
                    excess_returns=pct,
                    strategy_name=strategy_name,
                )
                wb["validation"] = {
                    "overall_grade": report.overall_grade.value,
                    "n_pass": report.n_pass,
                    "n_warn": report.n_warn,
                    "n_fail": report.n_fail,
                    "checks": [
                        {"name": c.name, "grade": c.grade.value,
                         "value": c.value, "detail": c.detail}
                        for c in report.checks
                    ],
                }

        results.append(wb)

    return results


def run_workbench_json(
    strategy_payloads: List[dict],
    **kwargs,
) -> str:
    """run_workbench + JSON 직렬화."""
    results = run_workbench(strategy_payloads, **kwargs)
    return to_workbench_json(results)
