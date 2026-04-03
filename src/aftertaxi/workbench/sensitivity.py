# -*- coding: utf-8 -*-
"""
workbench/sensitivity.py — 민감도 히트맵
========================================
성장률 × 변동성 2D 그리드에서 세후 배수를 계산.
"내 전략이 어떤 시장 환경에서 망하는가"를 한눈에.

합성 데이터 모드 전용. 코어 무관.

사용법:
  from aftertaxi.workbench.sensitivity import run_sensitivity

  grid = run_sensitivity(
      strategy_payload={"type": "q60s40"},
      growth_range=[0.0, 0.04, 0.08, 0.12, 0.16],
      vol_range=[0.10, 0.16, 0.22, 0.30, 0.40],
  )
  # grid.matrix  → 5×5 numpy array
  # grid.to_dataframe()  → pandas DataFrame (index=vol, columns=growth)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class SensitivityGrid:
    """민감도 그리드 결과."""
    growth_values: List[float]
    vol_values: List[float]
    matrix: np.ndarray       # (n_vol × n_growth), 세후 배수
    metric_name: str = "mult_after_tax"

    def to_dataframe(self) -> pd.DataFrame:
        """pandas DataFrame (행=vol, 열=growth)."""
        return pd.DataFrame(
            self.matrix,
            index=[f"{v:.0%}" for v in self.vol_values],
            columns=[f"{g:.0%}" for g in self.growth_values],
        )

    def summary_text(self) -> str:
        df = self.to_dataframe()
        best = np.unravel_index(self.matrix.argmax(), self.matrix.shape)
        worst = np.unravel_index(self.matrix.argmin(), self.matrix.shape)
        return (
            f"민감도 분석: {len(self.growth_values)}×{len(self.vol_values)} 그리드\n"
            f"  최고: {self.matrix[best]:.2f}x "
            f"(성장 {self.growth_values[best[1]]:.0%}, 변동 {self.vol_values[best[0]]:.0%})\n"
            f"  최저: {self.matrix[worst]:.2f}x "
            f"(성장 {self.growth_values[worst[1]]:.0%}, 변동 {self.vol_values[worst[0]]:.0%})\n"
            f"  범위: {self.matrix.min():.2f}x ~ {self.matrix.max():.2f}x"
        )


def run_sensitivity(
    strategy_payload: dict,
    growth_range: Optional[List[float]] = None,
    vol_range: Optional[List[float]] = None,
    n_months: int = 240,
    monthly_contribution: float = 1000.0,
    fx_rate: float = 1300.0,
    seed: int = 42,
    account_type: str = "TAXABLE",
) -> SensitivityGrid:
    """성장률 × 변동성 민감도 그리드 실행.

    Parameters
    ----------
    strategy_payload : {"type": "q60s40"} 등
    growth_range : 연 성장률 리스트 (기본 0~16% 5단계)
    vol_range : 연 변동성 리스트 (기본 10~40% 5단계)
    """
    from aftertaxi.strategies.compile import compile_backtest
    from aftertaxi.core.facade import run_backtest
    from aftertaxi.apps.data_provider import load_synthetic

    if growth_range is None:
        growth_range = [0.0, 0.04, 0.08, 0.12, 0.16]
    if vol_range is None:
        vol_range = [0.10, 0.16, 0.22, 0.30, 0.40]

    payload = {
        "strategy": strategy_payload,
        "accounts": [{"type": account_type, "monthly_contribution": monthly_contribution}],
        "n_months": n_months,
    }
    config = compile_backtest(payload)
    assets = list(config.strategy.weights.keys())

    matrix = np.zeros((len(vol_range), len(growth_range)))

    for i, vol in enumerate(vol_range):
        for j, growth in enumerate(growth_range):
            data = load_synthetic(
                assets, n_months=n_months,
                annual_growth=growth, annual_vol=vol,
                fx_rate=fx_rate, seed=seed,
            )
            result = run_backtest(
                config, returns=data.returns,
                prices=data.prices, fx_rates=data.fx,
            )
            invested_krw = result.invested_usd * fx_rate
            matrix[i, j] = result.gross_pv_krw / invested_krw if invested_krw > 0 else 0

    return SensitivityGrid(
        growth_values=growth_range,
        vol_values=vol_range,
        matrix=matrix,
    )
