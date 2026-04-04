# -*- coding: utf-8 -*-
"""
workbench/analytics.py — 분석 도구 (analytics MVP)
==================================================
자산별 기여 분해 + underwater chart 데이터.

사용법:
  from aftertaxi.workbench.analytics import build_asset_contribution, build_underwater

  contributions = build_asset_contribution(weights, prices)
  underwater = build_underwater(monthly_values)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd


@dataclass
class AssetContribution:
    """자산별 수익 기여."""
    asset: str
    target_weight: float          # 목표 비중
    cumulative_return: float      # 자산 누적 수익률
    contribution_pct: float       # 전체 수익에서 이 자산 기여 %
    dollar_contribution: float    # 기여 금액 (USD, 근사)


def build_asset_contribution(
    weights: Dict[str, float],
    prices: pd.DataFrame,
    invested_usd: float = 0.0,
) -> List[AssetContribution]:
    """Brinson-style 자산별 기여 분해.

    근사 방식: target_weight × asset_cumulative_return.
    DCA에서는 정확한 기여 분해가 어려우므로 근사치.

    Parameters
    ----------
    weights : 목표 비중 {"QQQ": 0.6, "SSO": 0.4}
    prices : 가격 DataFrame (index=date, columns=assets)
    invested_usd : 총 투입금 (USD)
    """
    results = []
    total_weighted_return = 0.0
    asset_returns = {}

    for asset, w in weights.items():
        if asset not in prices.columns:
            continue
        px = prices[asset].dropna()
        if len(px) < 2:
            continue
        cum_ret = (px.iloc[-1] / px.iloc[0]) - 1.0
        weighted_ret = w * cum_ret
        asset_returns[asset] = (w, cum_ret, weighted_ret)
        total_weighted_return += weighted_ret

    for asset, (w, cum_ret, weighted_ret) in asset_returns.items():
        pct = (weighted_ret / total_weighted_return * 100) if abs(total_weighted_return) > 1e-10 else 0
        dollar = invested_usd * weighted_ret if invested_usd > 0 else 0
        results.append(AssetContribution(
            asset=asset,
            target_weight=w,
            cumulative_return=cum_ret,
            contribution_pct=pct,
            dollar_contribution=dollar,
        ))

    # 기여 큰 순으로 정렬
    results.sort(key=lambda x: abs(x.contribution_pct), reverse=True)
    return results


@dataclass
class UnderwaterData:
    """Drawdown 시리즈 데이터."""
    drawdown: np.ndarray      # 월별 drawdown (0 ~ -1)
    peak: np.ndarray          # 월별 peak
    max_drawdown: float       # 최대 drawdown
    max_recovery_months: int  # 최장 회복 기간 (월)


def build_underwater(monthly_values: np.ndarray) -> UnderwaterData:
    """월별 PV에서 drawdown + recovery 분석."""
    if len(monthly_values) == 0:
        return UnderwaterData(np.array([]), np.array([]), 0.0, 0)

    peak = np.maximum.accumulate(monthly_values)
    dd = monthly_values / np.where(peak > 0, peak, 1.0) - 1.0

    # 최장 회복 기간
    max_recovery = 0
    current_dd_start = None
    for i, d in enumerate(dd):
        if d < -0.001:
            if current_dd_start is None:
                current_dd_start = i
        else:
            if current_dd_start is not None:
                recovery = i - current_dd_start
                max_recovery = max(max_recovery, recovery)
                current_dd_start = None
    # 아직 회복 안 된 구간
    if current_dd_start is not None:
        max_recovery = max(max_recovery, len(dd) - current_dd_start)

    return UnderwaterData(
        drawdown=dd,
        peak=peak,
        max_drawdown=float(dd.min()),
        max_recovery_months=max_recovery,
    )
