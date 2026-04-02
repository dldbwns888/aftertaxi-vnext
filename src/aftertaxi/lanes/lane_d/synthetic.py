# -*- coding: utf-8 -*-
"""
lanes/lane_d/synthetic.py — 합성 장기 시장 경로 생성
====================================================
Lane D = "역사와 무관한 가상 시장 100년에서 구조적으로 버티는가?"

Lane C와의 차이:
  Lane C = 역사 기반 bootstrap 분포 ("운이 나쁘면?")
  Lane D = 합성 장기 null world ("가상의 100년에서 살아남는가?")

  Lane C는 역사 길이만큼의 경로를 만든다.
  Lane D는 역사보다 훨씬 긴 경로(100년=1200개월)를 합성한다.

알고리즘: bootstrap_sign_flip (MVP)
  1. 역사 월간 수익률에서 block(12개월)을 무작위 추출 (replacement)
  2. 각 block에 ±1 sign flip 적용 (방향 제거)
  3. block을 이어붙여 target_months 길이의 경로 생성
  4. 결과: magnitude는 역사적, 방향은 완전 랜덤인 가상 시장

왜 이 알고리즘:
  - magnitude 분포(fat tail 포함) 보존
  - block으로 약한 자기상관 일부 유지
  - sign flip으로 방향성/트렌드 제거 → null world
  - 멀티자산이면 월 전체 벡터를 같이 뒤집음 (cross-asset 구조 보존)
  - Gaussian보다 현실적, HMM보다 단순하고 설명 가능

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
    preserve_fx: bool = True           # True면 FX 고정, False면 FX도 랜덤화 (미구현)


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

    rng = np.random.default_rng(config.seed)
    arr = source_returns.to_numpy()   # (T, N)
    T, N = arr.shape
    target = config.path_length_months
    bl = config.block_length

    # 합성 날짜 인덱스 (가상)
    synth_idx = pd.date_range("1900-01-31", periods=target, freq="ME")

    paths = []
    for _ in range(config.n_paths):
        chunks = []
        total = 0
        while total < target:
            # block 시작점 랜덤 추출 (replacement)
            max_start = max(T - bl, 1)
            start = rng.integers(0, max_start)
            end = min(start + bl, T)
            block = arr[start:end].copy()

            # 월 전체 벡터에 같은 sign flip (cross-asset 구조 보존)
            sign = rng.choice([-1.0, 1.0])
            block *= sign

            chunks.append(block)
            total += len(block)

        # target 길이로 자르기
        new_arr = np.vstack(chunks)[:target]

        paths.append(pd.DataFrame(
            new_arr,
            index=synth_idx,
            columns=source_returns.columns,
        ))

    return paths


def returns_to_prices(returns: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    """월간 수익률 → 누적 가격 DataFrame."""
    return base * (1 + returns).cumprod()
