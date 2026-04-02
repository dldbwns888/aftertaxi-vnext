# -*- coding: utf-8 -*-
"""
workbench_adapter.py — 엔진 결과 → 워크벤치 직렬화
===================================================
EngineResult + ResultAttribution → JSON-ready dict.

새 계약을 만들지 않는다. 기존 result/attribution 필드를
워크벤치 UI가 소비하는 shape로 변환할 뿐.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from aftertaxi.core.contracts import EngineResult
from aftertaxi.core.attribution import ResultAttribution, build_attribution


def to_workbench_payload(
    result: EngineResult,
    strategy_name: str,
    description: str = "",
    attribution: Optional[ResultAttribution] = None,
) -> Dict[str, Any]:
    """단일 전략 결과를 워크벤치 payload로 변환.

    Parameters
    ----------
    result : EngineResult (facade 출력)
    strategy_name : 전략 이름
    description : 전략 설명
    attribution : ResultAttribution (None이면 자동 계산)

    Returns
    -------
    dict — workbench STRATEGIES[i] 구조와 1:1 매핑
    """
    if attribution is None:
        attribution = build_attribution(result)

    return {
        "name": strategy_name,
        "description": description,
        "result": {
            "gross_pv_usd": result.gross_pv_usd,
            "invested_usd": result.invested_usd,
            "gross_pv_krw": result.gross_pv_krw,
            "net_pv_krw": result.net_pv_krw,
            "reporting_fx_rate": result.reporting_fx_rate,
            "mdd": result.mdd,
            "n_months": result.n_months,
            "mult_pre_tax": result.mult_pre_tax,
            "mult_after_tax": result.mult_after_tax,
        },
        "attribution": {
            "total_transaction_cost_usd": attribution.total_transaction_cost_usd,
            "total_tax_assessed_krw": attribution.total_tax_assessed_krw,
            "total_capital_gains_tax_krw": attribution.total_capital_gains_tax_krw,
            "total_dividend_tax_krw": attribution.total_dividend_tax_krw,
            "total_health_insurance_krw": attribution.total_health_insurance_krw,
            "total_dividend_gross_usd": attribution.total_dividend_gross_usd,
            "total_dividend_withholding_usd": attribution.total_dividend_withholding_usd,
            "total_dividend_net_usd": attribution.total_dividend_net_usd,
            "cost_drag_pct": attribution.cost_drag_pct,
            "tax_drag_pct": attribution.tax_drag_pct,
            "withholding_drag_pct": attribution.withholding_drag_pct,
        },
    }


def to_workbench_json(
    payloads: List[Dict[str, Any]],
    indent: int = 2,
) -> str:
    """여러 전략 payload를 JSON 문자열로."""
    return json.dumps(payloads, indent=indent, ensure_ascii=False)
