# -*- coding: utf-8 -*-
"""
workbench/export.py — 결과 내보내기
====================================
EngineResult → Excel/CSV. 코어 무관.

사용법:
  from aftertaxi.workbench.export import to_excel, to_csv

  to_excel(result, "output.xlsx", strategy_name="Q60S40")
  to_csv(result, "output.csv")

  # 멀티 전략
  to_excel_multi([r1, r2], ["Q60S40", "SPY"], "compare.xlsx")
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import EngineResult


def _result_to_summary_row(result: EngineResult, name: str = "") -> dict:
    """EngineResult → 요약 행 1개."""
    return {
        "전략": name,
        "기간(월)": result.n_months,
        "계좌수": result.n_accounts,
        "투입(USD)": result.invested_usd,
        "세전PV(USD)": result.gross_pv_usd,
        "세전배수": result.mult_pre_tax,
        "세후배수": result.mult_after_tax,
        "MDD": result.mdd,
        "세금assessed(KRW)": result.tax.total_assessed_krw,
        "세금paid(KRW)": result.tax.total_paid_krw,
        "건보료(KRW)": result.person.health_insurance_krw,
        "세금drag(%)": result.tax_drag * 100,
    }


def _result_to_monthly_df(result: EngineResult, name: str = "") -> pd.DataFrame:
    """EngineResult → 월별 PV DataFrame."""
    return pd.DataFrame({
        "month": range(1, len(result.monthly_values) + 1),
        "pv_usd": result.monthly_values,
        "strategy": name,
    })


def _result_to_accounts_df(result: EngineResult) -> pd.DataFrame:
    """EngineResult → 계좌별 요약."""
    rows = []
    for a in result.accounts:
        rows.append({
            "account_id": a.account_id,
            "type": a.account_type,
            "gross_pv_usd": a.gross_pv_usd,
            "invested_usd": a.invested_usd,
            "tax_assessed_krw": a.tax_assessed_krw,
            "capital_gains_tax_krw": a.capital_gains_tax_krw,
            "dividend_tax_krw": a.dividend_tax_krw,
            "health_insurance_krw": a.health_insurance_krw,
            "dividend_gross_usd": a.dividend_gross_usd,
            "mdd": a.mdd,
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════
# CSV
# ══════════════════════════════════════════════

def to_csv(
    result: EngineResult,
    path: Union[str, Path],
    strategy_name: str = "strategy",
) -> Path:
    """EngineResult → CSV (월별 PV)."""
    path = Path(path)
    df = _result_to_monthly_df(result, strategy_name)
    df.to_csv(path, index=False)
    return path


def to_csv_multi(
    results: List[EngineResult],
    names: List[str],
    path: Union[str, Path],
) -> Path:
    """여러 전략 → CSV (wide format)."""
    path = Path(path)
    frames = {}
    for r, n in zip(results, names):
        frames[n] = r.monthly_values

    max_len = max(len(v) for v in frames.values())
    df = pd.DataFrame({
        k: np.pad(v, (0, max_len - len(v)), constant_values=np.nan)
        for k, v in frames.items()
    })
    df.index.name = "month"
    df.index = df.index + 1
    df.to_csv(path)
    return path


# ══════════════════════════════════════════════
# Excel
# ══════════════════════════════════════════════

def to_excel(
    result: EngineResult,
    path: Union[str, Path],
    strategy_name: str = "strategy",
) -> Path:
    """EngineResult → Excel (요약 + 월별 + 계좌별)."""
    path = Path(path)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # 요약 시트
        summary = pd.DataFrame([_result_to_summary_row(result, strategy_name)])
        summary.to_excel(writer, sheet_name="요약", index=False)

        # 월별 PV
        monthly = _result_to_monthly_df(result, strategy_name)
        monthly.to_excel(writer, sheet_name="월별PV", index=False)

        # 계좌별
        if len(result.accounts) > 0:
            accounts = _result_to_accounts_df(result)
            accounts.to_excel(writer, sheet_name="계좌별", index=False)

    return path


def to_excel_multi(
    results: List[EngineResult],
    names: List[str],
    path: Union[str, Path],
) -> Path:
    """여러 전략 → Excel (비교표 + 각 전략 월별)."""
    path = Path(path)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # 비교 요약
        rows = [_result_to_summary_row(r, n) for r, n in zip(results, names)]
        pd.DataFrame(rows).to_excel(writer, sheet_name="비교", index=False)

        # 전략별 월별 PV (wide)
        frames = {}
        for r, n in zip(results, names):
            frames[n] = r.monthly_values
        max_len = max(len(v) for v in frames.values())
        df = pd.DataFrame({
            k: np.pad(v, (0, max_len - len(v)), constant_values=np.nan)
            for k, v in frames.items()
        })
        df.index.name = "month"
        df.index = df.index + 1
        df.to_excel(writer, sheet_name="월별PV")

    return path
