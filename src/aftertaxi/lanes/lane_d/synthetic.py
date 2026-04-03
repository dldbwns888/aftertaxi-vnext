# -*- coding: utf-8 -*-
"""
lanes/lane_d/synthetic.py — 합성 장기 시장 경로 생성
====================================================
Lane D = "역사와 무관한 가상 시장 100년에서 구조적으로 버티는가?"

Lane C와의 차이:
  Lane C = 역사 기반 bootstrap 분포 ("운이 나쁘면?")
  Lane D = 합성 장기 null world ("가상의 100년에서 살아남는가?")

2가지 생성 알고리즘:

1. sign_flip (기본값, null world)
   - 역사 magnitude 보존, 방향 완전 랜덤
   - block으로 약한 자기상관 유지
   - 가장 보수적인 null hypothesis

2. hmm_regime (레짐 전이 기반)
   - 역사에 HMM fit → Bull/Bear 레짐 추정
   - 레짐 전이 확률 + 레짐별 분포에서 새 경로 생성
   - Bull/Bear 비대칭성 + 레짐 지속성 보존
   - 레버리지 ETF의 변동성 끌림에 더 현실적

코어 변경 없음. 순수 경로 생성기.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SyntheticMarketConfig:
    """합성 시장 경로 생성 설정."""
    n_paths: int = 100
    path_length_months: int = 1200     # 100년
    seed: int = 42
    block_length: int = 12             # bootstrap block 크기 (월)
    base_fx_rate: float = 1300.0       # 고정 환율
    preserve_fx: bool = True           # True면 FX 고정
    mode: str = "sign_flip"            # "sign_flip" 또는 "hmm_regime"
    n_regimes: int = 2                 # HMM 레짐 수 (mode="hmm_regime"일 때)


def generate_synthetic_paths(
    source_returns: pd.DataFrame,
    config: Optional[SyntheticMarketConfig] = None,
) -> List[pd.DataFrame]:
    """역사 수익률에서 합성 장기 경로 생성.

    Parameters
    ----------
    source_returns : 역사 월간 수익률 DataFrame (T × N_assets)
    config : 생성 설정

    Returns
    -------
    list of DataFrame: 각 path_length_months × N_assets
    """
    if config is None:
        config = SyntheticMarketConfig()

    if config.mode == "hmm_regime":
        return _generate_hmm_paths(source_returns, config)
    else:
        return _generate_sign_flip_paths(source_returns, config)


def _generate_sign_flip_paths(
    source_returns: pd.DataFrame,
    config: SyntheticMarketConfig,
) -> List[pd.DataFrame]:
    """bootstrap_sign_flip: magnitude 보존 + 방향 랜덤."""
    rng = np.random.default_rng(config.seed)
    arr = source_returns.to_numpy()
    T, N = arr.shape
    target = config.path_length_months
    bl = config.block_length
    synth_idx = pd.date_range("1900-01-31", periods=target, freq="ME")

    paths = []
    for _ in range(config.n_paths):
        chunks = []
        total = 0
        while total < target:
            max_start = max(T - bl, 1)
            start = rng.integers(0, max_start)
            end = min(start + bl, T)
            block = arr[start:end].copy()
            sign = rng.choice([-1.0, 1.0])
            block *= sign
            chunks.append(block)
            total += len(block)

        new_arr = np.vstack(chunks)[:target]
        paths.append(pd.DataFrame(new_arr, index=synth_idx, columns=source_returns.columns))

    return paths


def _generate_hmm_paths(
    source_returns: pd.DataFrame,
    config: SyntheticMarketConfig,
) -> List[pd.DataFrame]:
    """HMM 레짐 기반 경로 생성.

    1. 역사 수익률에 GaussianHMM fit → 전이행렬 A, 레짐별 (μ_k, σ_k) 추정
    2. 경로 생성: 전이행렬로 매달 레짐 샘플링 → 해당 레짐의 N(μ_k, σ_k)에서 드로우
    3. 멀티자산: 레짐별 평균 벡터 + 공분산 행렬 보존

    sign_flip 대비 장점:
      - Bull/Bear 비대칭성 보존
      - 레짐 지속성 보존 (Bear 5개월 연속 등)
      - volatility drag에 민감한 레버리지 ETF 생존률 추정에 유리

    sign_flip 대비 단점:
      - 파라미터 추정이 역사에 의존 (fit 결과가 역사 편향)
      - fat tail은 가우시안 가정으로 일부 손실
      - n_regimes 선택이 결과에 영향
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        raise ImportError("hmmlearn 필요: pip install hmmlearn 또는 pip install -e '.[data]'")

    arr = source_returns.to_numpy()  # (T, N)
    T, N = arr.shape
    target = config.path_length_months
    synth_idx = pd.date_range("1900-01-31", periods=target, freq="ME")

    # 1. HMM fit (역사 전체로 한 번만)
    model = GaussianHMM(
        n_components=config.n_regimes,
        covariance_type="full",
        n_iter=200,
        random_state=config.seed,
    )
    model.fit(arr)

    # 추정된 파라미터 추출
    transmat = model.transmat_     # (K, K)
    means = model.means_           # (K, N)
    covars = model.covars_         # (K, N, N)
    startprob = model.startprob_   # (K,)

    # 2. 경로 생성
    rng = np.random.default_rng(config.seed)
    paths = []

    for _ in range(config.n_paths):
        # 초기 레짐
        state = rng.choice(config.n_regimes, p=startprob)
        path_arr = np.zeros((target, N))

        for t in range(target):
            # 현재 레짐에서 수익률 드로우
            path_arr[t] = rng.multivariate_normal(means[state], covars[state])
            # 다음 레짐 전이
            state = rng.choice(config.n_regimes, p=transmat[state])

        paths.append(pd.DataFrame(path_arr, index=synth_idx, columns=source_returns.columns))

    return paths


def returns_to_prices(returns: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    """월간 수익률 → 누적 가격 DataFrame."""
    return base * (1 + returns).cumprod()
