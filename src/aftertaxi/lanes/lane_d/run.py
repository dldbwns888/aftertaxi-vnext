# -*- coding: utf-8 -*-
"""
lanes/lane_d/run.py — Lane D 합성 장기 생존 시뮬레이션
======================================================
"가상의 100년 시장 100경로에서 이 전략이 살아남는가?"

Lane A: 실제 ETF/FX
Lane B: 장기 역사/Shiller 합성
Lane C: 역사 기반 bootstrap 분포 ("운이 나쁘면?")
Lane D: 합성 장기 null world ("가상 100년에서 버티는가?")

코어 변경 없음. facade.run_backtest()를 반복 호출할 뿐.

사용법:
  from aftertaxi.lanes.lane_d.run import run_lane_d
  from aftertaxi.lanes.lane_d.synthetic import SyntheticMarketConfig

  report = run_lane_d(
      source_returns=historical_returns,
      backtest_config=config,
      synthetic_config=SyntheticMarketConfig(n_paths=100),
  )
  print(report.summary_text())
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import BacktestConfig, EngineResult
from aftertaxi.core.facade import run_backtest
from aftertaxi.lanes.lane_d.synthetic import (
    SyntheticMarketConfig, generate_synthetic_paths, returns_to_prices,
)


@dataclass(frozen=True)
class SyntheticSurvivalReport:
    """Lane D 합성 장기 생존 시뮬레이션 결과.

    생존 정의: mult_after_tax > 1.0 (투입 원금 보전)
    """
    n_paths: int
    path_length_months: int
    path_length_years: float

    # 생존 통계
    survival_rate: float          # mult > 1 비율
    failure_prob: float           # mult < 0.5 비율

    # 배수 분포
    median_mult_after_tax: float
    p5_mult_after_tax: float
    p95_mult_after_tax: float
    mean_mult_after_tax: float

    # MDD 분포
    median_mdd: float
    p95_mdd: float               # 95%tile worst MDD (가장 가혹한 5%)

    # 실제 전략 대비
    actual_percentile: Optional[float]  # 실제 전략이 합성 분포에서 몇 %tile

    # raw 배열
    all_mult_after_tax: np.ndarray
    all_mdd: np.ndarray

    def summary_text(self) -> str:
        lines = [
            f"═══ Lane D: Synthetic {self.path_length_years:.0f}yr Survival ═══",
            f"  경로: {self.n_paths}개 × {self.path_length_months}개월",
            f"",
            f"  생존률:   {self.survival_rate:.1%}  (mult > 1)",
            f"  실패율:   {self.failure_prob:.1%}  (mult < 0.5)",
            f"",
            f"  세후 배수:",
            f"    중앙:   {self.median_mult_after_tax:.2f}x",
            f"    5%:     {self.p5_mult_after_tax:.2f}x",
            f"    95%:    {self.p95_mult_after_tax:.2f}x",
            f"    평균:   {self.mean_mult_after_tax:.2f}x",
            f"",
            f"  MDD:",
            f"    중앙:   {self.median_mdd:.1%}",
            f"    95%:    {self.p95_mdd:.1%}  (worst 5%)",
        ]
        if self.actual_percentile is not None:
            lines.append(f"")
            lines.append(f"  실제 전략: 합성 분포 {self.actual_percentile:.0f}%tile")

        return "\n".join(lines)


def run_lane_d(
    source_returns: pd.DataFrame,
    backtest_config: BacktestConfig,
    synthetic_config: Optional[SyntheticMarketConfig] = None,
    actual_result: Optional[EngineResult] = None,
) -> SyntheticSurvivalReport:
    """Lane D 합성 장기 생존 시뮬레이션 실행.

    Parameters
    ----------
    source_returns : 역사 월간 수익률 (경로 생성의 원재료)
    backtest_config : 전략+계좌 설정 (compile 결과)
    synthetic_config : 합성 경로 설정
    actual_result : 실제 전략 결과 (percentile 계산용, optional)
    """
    if synthetic_config is None:
        synthetic_config = SyntheticMarketConfig()

    # 1. 합성 경로 생성
    paths = generate_synthetic_paths(source_returns, synthetic_config)

    # 2. 각 경로에서 엔진 실행
    mults = []
    mdds = []

    for path_returns in paths:
        try:
            path_prices = returns_to_prices(path_returns)
            fx = pd.Series(synthetic_config.base_fx_rate, index=path_returns.index)

            result = run_backtest(
                backtest_config,
                returns=path_returns,
                prices=path_prices,
                fx_rates=fx,
            )
            mults.append(result.mult_after_tax)
            mdds.append(result.mdd)
        except Exception:
            # 실패한 경로: 전멸
            mults.append(0.0)
            mdds.append(-1.0)

    mults = np.array(mults)
    mdds = np.array(mdds)

    # 3. 통계 계산
    survival_rate = float(np.mean(mults > 1.0))
    failure_prob = float(np.mean(mults < 0.5))

    actual_pct = None
    if actual_result is not None:
        actual_mult = actual_result.mult_after_tax
        actual_pct = float(np.mean(mults <= actual_mult) * 100)

    return SyntheticSurvivalReport(
        n_paths=len(mults),
        path_length_months=synthetic_config.path_length_months,
        path_length_years=synthetic_config.path_length_months / 12.0,
        survival_rate=survival_rate,
        failure_prob=failure_prob,
        median_mult_after_tax=float(np.median(mults)),
        p5_mult_after_tax=float(np.percentile(mults, 5)),
        p95_mult_after_tax=float(np.percentile(mults, 95)),
        mean_mult_after_tax=float(np.mean(mults)),
        median_mdd=float(np.median(mdds)),
        p95_mdd=float(np.percentile(mdds, 5)),  # 5%tile of MDD = worst 5%
        actual_percentile=actual_pct,
        all_mult_after_tax=mults,
        all_mdd=mdds,
    )
