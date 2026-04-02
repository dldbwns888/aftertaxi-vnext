# -*- coding: utf-8 -*-
"""
lanes/lane_d/compare.py — DCA vs Lump Sum 비교 리포트
=====================================================
"Lane D 생존률이 전략 때문인가, 적립식 때문인가?"

비교 방식:
  DCA:      엔진 실행 (세금, 정산, 납입 전부 반영)
  Lump Sum: 가중 누적수익률 직접 계산 (C/O에서 매도 없음 = 세금 0)

두 모드가 같은 합성 경로를 사용하므로,
차이는 순수하게 "월적립 평균 매수 효과"에서 온다.

Lump Sum 계산이 엔진을 안 쓰는 이유:
  C/O 모드에서 lump sum은 초기 일괄 매수 → 보유 → 최종 가치.
  중간에 매도가 없으므로 양도세 0. 엔진 없이 누적수익률로 정확.

코어 변경 없음.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import BacktestConfig, EngineResult
from aftertaxi.lanes.lane_d.synthetic import (
    SyntheticMarketConfig, generate_synthetic_paths,
)
from aftertaxi.lanes.lane_d.run import (
    SyntheticSurvivalReport, _run_single_path, returns_to_prices,
)


@dataclass(frozen=True)
class LumpSumResult:
    """단일 경로의 lump sum 결과."""
    final_mult: float    # 최종 배수 (= 누적 수익률)
    mdd: float           # 최대 낙폭


@dataclass(frozen=True)
class LaneDComparisonReport:
    """DCA vs Lump Sum 비교 리포트.

    기존 SyntheticSurvivalReport 계약은 안 깨짐.
    이 리포트가 상위 래퍼.
    """
    dca_report: SyntheticSurvivalReport
    n_paths: int
    path_length_months: int

    # Lump Sum 분포
    ls_survival_rate: float
    ls_failure_prob: float
    ls_median_mult: float
    ls_p5_mult: float
    ls_p95_mult: float
    ls_median_mdd: float
    ls_all_mults: np.ndarray
    ls_all_mdds: np.ndarray

    # 비교 (DCA - Lump Sum)
    survival_delta: float         # DCA 생존률 - LS 생존률
    median_mult_delta: float      # DCA 중앙 배수 - LS 중앙 배수

    def summary_text(self) -> str:
        lines = [
            f"═══ Lane D: DCA vs Lump Sum ({self.path_length_months // 12}yr × {self.n_paths} paths) ═══",
            f"",
            f"  {'':20s} {'DCA':>10s} {'Lump Sum':>10s} {'Delta':>10s}",
            f"  {'─' * 52}",
            f"  {'생존률':20s} {self.dca_report.survival_rate:>9.1%} {self.ls_survival_rate:>9.1%} {self.survival_delta:>+9.1%}",
            f"  {'중앙 배수':20s} {self.dca_report.median_mult_after_tax:>10.2f} {self.ls_median_mult:>10.2f} {self.median_mult_delta:>+10.2f}",
            f"  {'5% 배수':20s} {self.dca_report.p5_mult_after_tax:>10.2f} {self.ls_p5_mult:>10.2f}",
            f"  {'95% 배수':20s} {self.dca_report.p95_mult_after_tax:>10.2f} {self.ls_p95_mult:>10.2f}",
            f"  {'중앙 MDD':20s} {self.dca_report.median_mdd:>9.1%} {self.ls_median_mdd:>9.1%}",
            f"",
        ]

        # 해석
        if self.survival_delta > 0.05:
            lines.append(f"  → DCA 효과가 크다: 적립식이 생존률을 {self.survival_delta:.0%}p 올림")
        elif self.survival_delta < -0.05:
            lines.append(f"  → Lump Sum이 더 나음: DCA가 오히려 생존률을 깎음")
        else:
            lines.append(f"  → 납입 방식 차이 미미: 생존은 전략 구조에 의존")

        return "\n".join(lines)


# ══════════════════════════════════════════════
# Lump Sum 계산 (엔진 없이)
# ══════════════════════════════════════════════

def _compute_lump_sum(
    path_returns: pd.DataFrame,
    weights: dict,
) -> LumpSumResult:
    """단일 경로의 lump sum 결과 계산.

    가중 포트폴리오 누적수익률 = 매달 rebalanced portfolio.
    MDD는 누적 가치 경로에서 계산.
    """
    # 가중 월간 수익률
    w_ret = np.zeros(len(path_returns))
    for asset, w in weights.items():
        if asset in path_returns.columns:
            w_ret += w * path_returns[asset].values

    # 누적 가치 경로
    cumulative = np.cumprod(1 + w_ret)

    # 배수
    final_mult = float(cumulative[-1]) if len(cumulative) > 0 else 0.0

    # MDD
    if len(cumulative) > 0:
        peak = np.maximum.accumulate(cumulative)
        drawdown = cumulative / peak - 1.0
        mdd = float(drawdown.min())
    else:
        mdd = 0.0

    return LumpSumResult(final_mult=final_mult, mdd=mdd)


# ══════════════════════════════════════════════
# 비교 실행
# ══════════════════════════════════════════════

def run_lane_d_comparison(
    source_returns: pd.DataFrame,
    backtest_config: BacktestConfig,
    synthetic_config: Optional[SyntheticMarketConfig] = None,
    n_jobs: int = 1,
) -> LaneDComparisonReport:
    """DCA vs Lump Sum 비교 실행.

    같은 합성 경로에서 두 모드를 비교.
    DCA = 엔진 실행, Lump Sum = 가중 누적수익률.

    Parameters
    ----------
    source_returns : 역사 월간 수익률
    backtest_config : 전략+계좌 설정
    synthetic_config : 합성 경로 설정
    n_jobs : 병렬 워커 수 (DCA 엔진 실행용)
    """
    if synthetic_config is None:
        synthetic_config = SyntheticMarketConfig()

    weights = backtest_config.strategy.weights

    # 1. 같은 합성 경로 생성 (공유)
    paths = generate_synthetic_paths(source_returns, synthetic_config)

    # 2. DCA: 엔진 실행
    fx_rate = synthetic_config.base_fx_rate
    if n_jobs != 1:
        from joblib import Parallel, delayed
        dca_results = Parallel(n_jobs=n_jobs)(
            delayed(_run_single_path)(p, backtest_config, fx_rate)
            for p in paths
        )
    else:
        dca_results = [_run_single_path(p, backtest_config, fx_rate) for p in paths]

    dca_mults = np.array([r[0] for r in dca_results])
    dca_mdds = np.array([r[1] for r in dca_results])

    # 3. Lump Sum: 누적수익률 계산
    ls_results = [_compute_lump_sum(p, weights) for p in paths]
    ls_mults = np.array([r.final_mult for r in ls_results])
    ls_mdds = np.array([r.mdd for r in ls_results])

    # 4. DCA report 조립
    dca_report = SyntheticSurvivalReport(
        n_paths=len(dca_mults),
        path_length_months=synthetic_config.path_length_months,
        path_length_years=synthetic_config.path_length_months / 12.0,
        survival_rate=float(np.mean(dca_mults > 1.0)),
        failure_prob=float(np.mean(dca_mults < 0.5)),
        median_mult_after_tax=float(np.median(dca_mults)),
        p5_mult_after_tax=float(np.percentile(dca_mults, 5)),
        p95_mult_after_tax=float(np.percentile(dca_mults, 95)),
        mean_mult_after_tax=float(np.mean(dca_mults)),
        median_mdd=float(np.median(dca_mdds)),
        p95_mdd=float(np.percentile(dca_mdds, 5)),
        actual_percentile=None,
        all_mult_after_tax=dca_mults,
        all_mdd=dca_mdds,
    )

    # 5. 비교 조립
    ls_survival = float(np.mean(ls_mults > 1.0))
    ls_failure = float(np.mean(ls_mults < 0.5))
    dca_survival = dca_report.survival_rate

    return LaneDComparisonReport(
        dca_report=dca_report,
        n_paths=len(dca_mults),
        path_length_months=synthetic_config.path_length_months,
        ls_survival_rate=ls_survival,
        ls_failure_prob=ls_failure,
        ls_median_mult=float(np.median(ls_mults)),
        ls_p5_mult=float(np.percentile(ls_mults, 5)),
        ls_p95_mult=float(np.percentile(ls_mults, 95)),
        ls_median_mdd=float(np.median(ls_mdds)),
        ls_all_mults=ls_mults,
        ls_all_mdds=ls_mdds,
        survival_delta=dca_survival - ls_survival,
        median_mult_delta=dca_report.median_mult_after_tax - float(np.median(ls_mults)),
    )
