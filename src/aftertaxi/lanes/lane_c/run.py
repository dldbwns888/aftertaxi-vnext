# -*- coding: utf-8 -*-
"""
lane_c/run.py — Lane C Bootstrap Distribution Layer
====================================================
Block bootstrap 경로를 엔진에 반복 투입 → 세후 결과 분포.

Lane C는 독립 진실원이 아님.
source history(Lane A 또는 B)의 분포판이다.

출력:
  - median / percentile after-tax multiple
  - 파산확률 (mult < 1.0x)
  - worst 5% 평균 배수 (CVaR)
  - tax drag 분포
  - provenance (seed, source, 재현 정보)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.lanes.lane_c.bootstrap import (
    BootstrapConfig, PathProvenance, circular_block_bootstrap,
)


# ══════════════════════════════════════════════
# 분포 리포트
# ══════════════════════════════════════════════

@dataclass
class DistributionReport:
    """Bootstrap 결과 분포."""
    n_paths: int
    block_length: int
    path_length_months: int

    # 배수 분포
    mult_pre_tax_median: float
    mult_pre_tax_p5: float
    mult_pre_tax_p25: float
    mult_pre_tax_p75: float
    mult_pre_tax_p95: float

    mult_after_tax_median: float
    mult_after_tax_p5: float
    mult_after_tax_p25: float
    mult_after_tax_p75: float
    mult_after_tax_p95: float

    # 리스크
    failure_prob: float
    cvar_5pct: float
    median_mdd: float
    p95_mdd: float

    # 세금
    median_tax_drag: float
    p95_tax_drag: float

    # provenance
    seed: int = 0
    source_start: str = ""
    source_end: str = ""
    source_n_months: int = 0
    base_year: int = 2000

    # raw data
    all_mult_pre_tax: np.ndarray = field(repr=False, default_factory=lambda: np.array([]))
    all_mult_after_tax: np.ndarray = field(repr=False, default_factory=lambda: np.array([]))

    def summary_text(self) -> str:
        return (
            f"=== Lane C Distribution ({self.n_paths} paths, "
            f"B={self.block_length}M, L={self.path_length_months}M, "
            f"seed={self.seed}) ===\n"
            f"Source: {self.source_start} ~ {self.source_end} ({self.source_n_months}M)\n"
            f"After-tax mult: median={self.mult_after_tax_median:.2f}x, "
            f"5th={self.mult_after_tax_p5:.2f}x, "
            f"95th={self.mult_after_tax_p95:.2f}x\n"
            f"Failure prob (mult<1): {self.failure_prob:.1%}\n"
            f"CVaR 5%: {self.cvar_5pct:.2f}x\n"
            f"MDD: median={self.median_mdd:.1%}, p95={self.p95_mdd:.1%}\n"
            f"Tax drag: median={self.median_tax_drag:.1%}, p95={self.p95_tax_drag:.1%}"
        )


# ══════════════════════════════════════════════
# 실행
# ══════════════════════════════════════════════

def run_lane_c(
    source_returns: pd.DataFrame,
    source_fx_returns: Optional[pd.Series],
    config: BacktestConfig,
    bootstrap_config: BootstrapConfig = None,
    base_fx_rate: float = 1300.0,
    n_jobs: int = 1,
) -> DistributionReport:
    """Lane C 실행: bootstrap → 엔진 반복 → 분포 리포트.

    Parameters
    ----------
    source_returns : 원천 수익률 (Lane A 또는 B에서 추출)
    source_fx_returns : FX 월간 변화율 (None이면 고정 환율)
    config : BacktestConfig (계좌/전략 설정)
    bootstrap_config : 부트스트랩 설정
    base_fx_rate : 기준 환율
    n_jobs : 병렬 워커 수 (1이면 순차, -1이면 전체 CPU)
    """
    if bootstrap_config is None:
        bootstrap_config = BootstrapConfig()

    # 경로 생성
    paths = circular_block_bootstrap(source_returns, bootstrap_config, source_fx_returns)
    use_fx = source_fx_returns is not None

    # 엔진 실행 (병렬 or 순차)
    if n_jobs != 1:
        results = _run_parallel(paths, config, base_fx_rate, use_fx, n_jobs)
    else:
        results = [_run_single_path(p, config, base_fx_rate, use_fx) for p in paths]

    # 분포 계산
    mult_pre = np.array([r.mult_pre_tax for r in results])
    mult_post = np.array([r.mult_after_tax for r in results])
    mdds = np.array([r.mdd for r in results])
    tax_drags = np.array([r.tax_drag for r in results])

    p5_idx = mult_post <= np.percentile(mult_post, 5)
    cvar = float(mult_post[p5_idx].mean()) if p5_idx.any() else float(mult_post.min())

    # provenance (첫 경로에서 가져옴)
    prov = paths[0].get("provenance")

    return DistributionReport(
        n_paths=bootstrap_config.n_paths,
        block_length=bootstrap_config.block_length,
        path_length_months=bootstrap_config.path_length,
        mult_pre_tax_median=float(np.median(mult_pre)),
        mult_pre_tax_p5=float(np.percentile(mult_pre, 5)),
        mult_pre_tax_p25=float(np.percentile(mult_pre, 25)),
        mult_pre_tax_p75=float(np.percentile(mult_pre, 75)),
        mult_pre_tax_p95=float(np.percentile(mult_pre, 95)),
        mult_after_tax_median=float(np.median(mult_post)),
        mult_after_tax_p5=float(np.percentile(mult_post, 5)),
        mult_after_tax_p25=float(np.percentile(mult_post, 25)),
        mult_after_tax_p75=float(np.percentile(mult_post, 75)),
        mult_after_tax_p95=float(np.percentile(mult_post, 95)),
        failure_prob=float((mult_post < 1.0).mean()),
        cvar_5pct=cvar,
        median_mdd=float(np.median(mdds)),
        p95_mdd=float(np.percentile(mdds, 5)),
        median_tax_drag=float(np.median(tax_drags)),
        p95_tax_drag=float(np.percentile(tax_drags, 95)),
        seed=bootstrap_config.seed,
        source_start=prov.source_start if prov else "",
        source_end=prov.source_end if prov else "",
        source_n_months=prov.source_n_months if prov else 0,
        base_year=prov.base_year if prov else 2000,
        all_mult_pre_tax=mult_pre,
        all_mult_after_tax=mult_post,
    )


def _run_parallel(paths, config, base_fx_rate, use_fx, n_jobs):
    """joblib 병렬 실행. 결과 순서 보존."""
    from joblib import Parallel, delayed
    return Parallel(n_jobs=n_jobs)(
        delayed(_run_single_path)(p, config, base_fx_rate, use_fx)
        for p in paths
    )


def _run_single_path(
    path: dict,
    config: BacktestConfig,
    base_fx_rate: float,
    use_fx_returns: bool,
) -> EngineResult:
    """단일 bootstrap 경로 실행."""
    returns = path["returns"]
    prices = 100.0 * (1 + returns).cumprod()

    if use_fx_returns and path["fx_returns"] is not None:
        fx_rates = base_fx_rate * (1 + path["fx_returns"]).cumprod()
    else:
        fx_rates = pd.Series(base_fx_rate, index=returns.index)

    # config의 전체 설정 보존 (dividend_schedule, enable_health_insurance 등)
    path_config = BacktestConfig(
        accounts=config.accounts,
        strategy=config.strategy,
        n_months=len(returns),
        start_index=0,
        dividend_schedule=config.dividend_schedule,
        enable_health_insurance=config.enable_health_insurance,
    )

    return run_backtest(path_config, returns=returns, prices=prices, fx_rates=fx_rates)
