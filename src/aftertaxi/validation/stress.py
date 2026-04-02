# -*- coding: utf-8 -*-
"""
validation/stress.py — 랜덤 시장 생존 테스트
=============================================
"전략이 진짜 구조가 있는 건가, 완전 무작위 시장에서도 우연히 살아남는가?"

귀무가설(null): 시장 방향이 완전 무작위.
방법: 역사 수익률의 크기(magnitude)는 유지, 방향(sign)만 랜덤.

알고리즘:
  1. vector_sign_flip: 월별 자산 벡터 전체에 같은 ±1
     - 자산 간 상대 구조 유지
     - "시장 방향만 랜덤"이라는 해석에 가장 부합
  2. bootstrap_sign_flip: block bootstrap + sign flip
     - 더 현실적인 null (자기상관 일부 유지)

FX는 기본적으로 역사 그대로 고정 (preserve_fx=True).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import BacktestConfig, EngineResult
from aftertaxi.core.facade import run_backtest
from aftertaxi.validation.reports import CheckResult, Grade


@dataclass
class RandomScenarioConfig:
    n_paths: int = 100
    seed: int = 42
    mode: str = "vector_sign_flip"  # "bootstrap_sign_flip"
    block_length: int = 12
    preserve_fx: bool = True


@dataclass
class RandomScenarioReport:
    """랜덤 시장 생존 테스트 결과."""
    n_paths: int
    survival_rate: float          # mult_after_tax > 1인 비율
    median_mult: float
    p5_mult: float
    p95_mult: float
    failure_prob: float           # mult_after_tax < 0.5인 비율
    actual_percentile: Optional[float]  # 실제 전략이 null 분포에서 몇 %tile
    all_mults: np.ndarray         # 전체 mult 배열

    def to_check_result(self) -> CheckResult:
        """ValidationReport에 넣을 수 있는 CheckResult로 변환."""
        if self.actual_percentile is not None and self.actual_percentile > 90:
            grade = Grade.PASS
            detail = (f"실제 전략이 null 분포 {self.actual_percentile:.0f}%tile. "
                      f"생존율 {self.survival_rate:.0%}, 중앙 {self.median_mult:.2f}x")
        elif self.actual_percentile is not None and self.actual_percentile > 50:
            grade = Grade.WARN
            detail = (f"실제 전략이 null 분포 {self.actual_percentile:.0f}%tile. "
                      f"우연 가능성 있음.")
        else:
            grade = Grade.FAIL
            detail = (f"실제 전략이 null 분포 {self.actual_percentile or 0:.0f}%tile. "
                      f"랜덤보다 못함.")

        return CheckResult(
            name="random_market_survival",
            grade=grade,
            value=self.actual_percentile or 0.0,
            threshold=90.0,
            detail=detail,
        )


# ══════════════════════════════════════════════
# 경로 생성
# ══════════════════════════════════════════════

def generate_vector_sign_flip(
    returns: pd.DataFrame,
    n_paths: int,
    seed: int = 42,
) -> List[pd.DataFrame]:
    """월별 자산 벡터 전체에 같은 ±1 sign flip."""
    rng = np.random.default_rng(seed)
    arr = returns.to_numpy()
    paths = []
    for _ in range(n_paths):
        signs = rng.choice([-1.0, 1.0], size=len(arr))
        new_arr = arr * signs[:, None]
        paths.append(pd.DataFrame(new_arr, index=returns.index, columns=returns.columns))
    return paths


def generate_bootstrap_sign_flip(
    returns: pd.DataFrame,
    n_paths: int,
    block_length: int = 12,
    seed: int = 42,
) -> List[pd.DataFrame]:
    """Block bootstrap + sign flip. 더 현실적인 null."""
    rng = np.random.default_rng(seed)
    T = len(returns)
    arr = returns.to_numpy()
    paths = []
    for _ in range(n_paths):
        chunks = []
        total = 0
        while total < T:
            start = rng.integers(0, max(T - block_length + 1, 1))
            block = arr[start:start + block_length].copy()
            sign = rng.choice([-1.0, 1.0])
            block *= sign
            chunks.append(block)
            total += len(block)
        new_arr = np.vstack(chunks)[:T]
        paths.append(pd.DataFrame(new_arr, index=returns.index, columns=returns.columns))
    return paths


# ══════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════

def run_random_market_survival(
    source_returns: pd.DataFrame,
    fx_rates: pd.Series,
    config: BacktestConfig,
    random_config: Optional[RandomScenarioConfig] = None,
    actual_result: Optional[EngineResult] = None,
    prices: Optional[pd.DataFrame] = None,
) -> RandomScenarioReport:
    """랜덤 시장 생존 테스트 실행.

    Parameters
    ----------
    source_returns : 역사 월간 수익률
    fx_rates : FX 환율 (preserve_fx=True면 그대로 사용)
    config : BacktestConfig (전략 + 계좌 설정)
    random_config : 랜덤 시나리오 설정
    actual_result : 실제 전략 결과 (percentile 계산용)
    prices : 가격 DataFrame (None이면 returns에서 역산)
    """
    if random_config is None:
        random_config = RandomScenarioConfig()

    # 경로 생성
    if random_config.mode == "vector_sign_flip":
        paths = generate_vector_sign_flip(
            source_returns, random_config.n_paths, random_config.seed)
    elif random_config.mode == "bootstrap_sign_flip":
        paths = generate_bootstrap_sign_flip(
            source_returns, random_config.n_paths,
            random_config.block_length, random_config.seed)
    else:
        raise ValueError(f"Unknown mode: {random_config.mode}")

    # 각 경로에서 엔진 실행
    mults = []
    for path_returns in paths:
        try:
            # 가격 역산 (returns → prices)
            path_prices = 100.0 * (1 + path_returns).cumprod()

            result = run_backtest(
                config,
                returns=path_returns,
                prices=path_prices,
                fx_rates=fx_rates,
            )
            mults.append(result.mult_after_tax)
        except Exception:
            mults.append(0.0)  # 실패한 경로는 전멸로 처리

    mults = np.array(mults)

    # 통계
    survival_rate = float(np.mean(mults > 1.0))
    failure_prob = float(np.mean(mults < 0.5))

    # 실제 전략 대비 percentile
    actual_pct = None
    if actual_result is not None:
        actual_mult = actual_result.mult_after_tax
        actual_pct = float(np.mean(mults <= actual_mult) * 100)

    return RandomScenarioReport(
        n_paths=len(mults),
        survival_rate=survival_rate,
        median_mult=float(np.median(mults)),
        p5_mult=float(np.percentile(mults, 5)),
        p95_mult=float(np.percentile(mults, 95)),
        failure_prob=failure_prob,
        actual_percentile=actual_pct,
        all_mults=mults,
    )
