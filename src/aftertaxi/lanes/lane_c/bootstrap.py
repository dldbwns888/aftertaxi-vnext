# -*- coding: utf-8 -*-
"""
lane_c/bootstrap.py — Circular Block Bootstrap 샘플러
=====================================================
월간 수익률 패널에서 블록 단위로 리샘플링하여 합성 경로 생성.

핵심 원칙:
  1. 블록 = cross-section 전체 (자산별 따로 X → 상관구조 보존)
  2. Circular: 끝→처음 순환으로 edge bias 최소화
  3. seed 고정 → 재현성 보장 (common random numbers)
  4. 각 경로에 provenance 메타 포함 → 재현 가능
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class BootstrapConfig:
    """부트스트랩 설정."""
    n_paths: int = 1000          # 생성할 경로 수
    path_length: int = 240       # 경로 길이 (월, 20년=240)
    block_length: int = 24       # 블록 길이 (월)
    seed: int = 42               # 재현성
    base_year: Optional[int] = None  # 합성 경로 시작 연도 (None이면 source에서 추론)


@dataclass(frozen=True)
class PathProvenance:
    """단일 경로의 재현 정보."""
    path_id: int
    seed: int
    block_length: int
    path_length: int
    source_start: str        # source 데이터 시작일
    source_end: str          # source 데이터 종료일
    source_n_months: int     # source 데이터 길이
    block_starts: tuple      # 블록 시작 인덱스 (재현용)
    base_year: int           # 합성 경로 시작 연도


def circular_block_bootstrap(
    returns: pd.DataFrame,
    config: BootstrapConfig,
    fx_returns: Optional[pd.Series] = None,
) -> list:
    """Circular block bootstrap로 합성 경로 생성.

    Parameters
    ----------
    returns : DataFrame, index=datetime, columns=assets, values=monthly returns
    config : BootstrapConfig
    fx_returns : Series (optional), FX 월간 변화율. 있으면 같은 블록으로 리샘플.

    Returns
    -------
    list of dict, 각각:
      {"returns": DataFrame, "fx_returns": Series or None,
       "path_id": int, "provenance": PathProvenance}
    """
    rng = np.random.default_rng(config.seed)
    T = len(returns)
    B = config.block_length
    L = config.path_length

    # 블록 개수 (한 경로당)
    n_blocks = int(np.ceil(L / B))

    # 날짜축 기준 연도
    base_year = config.base_year
    if base_year is None:
        base_year = returns.index[0].year
    syn_idx = pd.date_range(f"{base_year}-01-31", periods=L, freq="ME")

    # source provenance
    src_start = str(returns.index[0].date())
    src_end = str(returns.index[-1].date())

    # returns를 numpy로 변환 (속도)
    ret_values = returns.values  # (T, n_assets)
    assets = returns.columns.tolist()

    fx_values = None
    if fx_returns is not None:
        fx_aligned = fx_returns.reindex(returns.index).fillna(0.0)
        fx_values = fx_aligned.values

    paths = []
    for path_id in range(config.n_paths):
        # 블록 시작점 랜덤 선택
        block_starts = rng.integers(0, T, size=n_blocks)

        # circular 인덱싱으로 블록 연결
        indices = []
        for start in block_starts:
            for j in range(B):
                indices.append((start + j) % T)
        indices = indices[:L]

        # 합성 returns
        syn_ret = ret_values[indices]
        syn_df = pd.DataFrame(syn_ret, index=syn_idx, columns=assets)

        # 합성 FX returns
        syn_fx = None
        if fx_values is not None:
            syn_fx = pd.Series(fx_values[indices], index=syn_idx, name="fx_return")

        # provenance
        prov = PathProvenance(
            path_id=path_id,
            seed=config.seed,
            block_length=B,
            path_length=L,
            source_start=src_start,
            source_end=src_end,
            source_n_months=T,
            block_starts=tuple(block_starts.tolist()),
            base_year=base_year,
        )

        paths.append({
            "returns": syn_df,
            "fx_returns": syn_fx,
            "path_id": path_id,
            "provenance": prov,
        })

    return paths
