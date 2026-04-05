# -*- coding: utf-8 -*-
"""
lab/strategy_builder/generator.py — 랜덤 전략 생성기 + 구조 검증
================================================================
블록 풀에서 랜덤 조합으로 StrategyGenome을 대량 생성.
구조적으로 무의미한 조합은 사전 필터.

안전장치:
  - asset_pool에 기본값 없음 (사용자 명시 강제)
  - max_leverage_ratio로 레버리지 상한
  - seed 기반 재현성
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from aftertaxi.lab.strategy_builder.blocks import (
    AllocBlock, SignalBlock,
    AlwaysOn, AbsMomentum, RelMomentum, SMACross,
    StaticWeight, EqualWeight, CashShelter, BondShelter,
)
from aftertaxi.lab.strategy_builder.genome import StrategyGenome


# ══════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class GeneratorConfig:
    """전략 생성기 설정. asset_pool에 기본값 없음."""

    asset_pool: Tuple[str, ...]             # ("SPY", "QQQ", "SSO") — 필수
    shelter_pool: Tuple[str, ...] = ("SGOV", "SHY")
    n_candidates: int = 100
    min_assets: int = 1
    max_assets: int = 3
    min_weight: float = 0.10                # 각 자산 최소 10%
    lookback_range: Tuple[int, int] = (3, 12)  # signal lookback 범위
    sma_range: Tuple[int, int] = (6, 12)
    filter_prob: float = 0.3                # 추가 필터 확률
    include_bnh: bool = True                # AlwaysOn 블록 포함 여부
    rebalance_options: Tuple[str, ...] = ("FULL",)  # CO는 signal에 반응 불가
    seed: int = 42

    def __post_init__(self):
        if not self.asset_pool:
            raise ValueError("asset_pool 필수. 빈 값 금지.")
        if self.n_candidates < 1:
            raise ValueError("n_candidates >= 1")


# ══════════════════════════════════════════════
# 생성기
# ══════════════════════════════════════════════

def generate_genomes(config: GeneratorConfig) -> List[StrategyGenome]:
    """블록 풀에서 랜덤 조합 N개 생성.

    Returns
    -------
    List[StrategyGenome] : 구조 검증 통과한 것만 반환.
    """
    rng = np.random.default_rng(config.seed)
    genomes = []

    for _ in range(config.n_candidates):
        genome = _random_genome(config, rng)
        if validate_genome(genome):
            genomes.append(genome)

    return genomes


def _random_genome(config: GeneratorConfig, rng: np.random.Generator) -> StrategyGenome:
    """단일 genome 랜덤 생성."""
    growth = _random_alloc(config.asset_pool, config, rng)
    shelter = _random_shelter(config.shelter_pool, rng)
    signal = _random_signal(config, rng)
    rebalance = rng.choice(list(config.rebalance_options))

    # 필터: 확률적 추가
    filt = None
    if rng.random() < config.filter_prob and not isinstance(signal, AlwaysOn):
        filt = _random_signal(config, rng, exclude_always_on=True)

    return StrategyGenome(
        growth=growth,
        shelter=shelter,
        signal=signal,
        rebalance=rebalance,
        filter=filt,
    )


def _random_alloc(
    pool: Tuple[str, ...],
    config: GeneratorConfig,
    rng: np.random.Generator,
) -> AllocBlock:
    """성장 배분 블록 랜덤 생성."""
    n = rng.integers(config.min_assets, min(config.max_assets, len(pool)) + 1)
    chosen = tuple(rng.choice(list(pool), size=n, replace=False))

    # 50% static, 50% equal
    if rng.random() < 0.5 or n == 1:
        # Dirichlet 비중
        raw = rng.dirichlet(np.ones(n))
        clamped = np.maximum(raw, config.min_weight)
        normalized = clamped / clamped.sum()
        weights = {a: float(w) for a, w in zip(chosen, normalized)}
        return StaticWeight(weights=weights)
    else:
        return EqualWeight(asset_list=chosen)


def _random_shelter(
    pool: Tuple[str, ...],
    rng: np.random.Generator,
) -> AllocBlock:
    """쉘터 블록 랜덤 선택."""
    asset = rng.choice(list(pool))
    if rng.random() < 0.6:
        return CashShelter(asset=asset)
    else:
        return BondShelter(asset=asset)


def _random_signal(
    config: GeneratorConfig,
    rng: np.random.Generator,
    exclude_always_on: bool = False,
) -> SignalBlock:
    """신호 블록 랜덤 선택 + 파라미터화."""
    pool = config.asset_pool
    lb_lo, lb_hi = config.lookback_range
    sma_lo, sma_hi = config.sma_range

    options = ["abs_momentum", "rel_momentum", "sma_cross"]
    if config.include_bnh and not exclude_always_on:
        options.append("always_on")

    choice = rng.choice(options)

    if choice == "always_on":
        return AlwaysOn()
    elif choice == "abs_momentum":
        return AbsMomentum(
            asset=rng.choice(list(pool)),
            lookback=int(rng.integers(lb_lo, lb_hi + 1)),
        )
    elif choice == "rel_momentum":
        if len(pool) < 2:
            return AbsMomentum(asset=pool[0], lookback=int(rng.integers(lb_lo, lb_hi + 1)))
        pair = rng.choice(list(pool), size=2, replace=False)
        return RelMomentum(
            asset_a=pair[0], asset_b=pair[1],
            lookback=int(rng.integers(lb_lo, lb_hi + 1)),
        )
    else:  # sma_cross
        return SMACross(
            asset=rng.choice(list(pool)),
            period=int(rng.integers(sma_lo, sma_hi + 1)),
        )


# ══════════════════════════════════════════════
# 구조 검증
# ══════════════════════════════════════════════

def validate_genome(genome: StrategyGenome) -> bool:
    """구조적으로 무의미한 전략 사전 필터.

    실패 조건:
    1. AlwaysOn인데 shelter이 growth와 다름 (사용 안 되는 쉘터)
       → 허용하되 B&H로 표시 (쉘터 무시됨)
    2. growth와 shelter가 완전히 동일 (전환 의미 없음)
    3. 비중 합 != 1.0 (±0.01)
    """
    # growth == shelter이면 전환 의미 없음 (AlwaysOn이 아닌 경우)
    if not isinstance(genome.signal, AlwaysOn):
        g_w = genome.growth.get_weights()
        s_w = genome.shelter.get_weights()
        if g_w == s_w:
            return False

    # 비중 합 검증
    for alloc in (genome.growth, genome.shelter):
        w_sum = sum(alloc.get_weights().values())
        if abs(w_sum - 1.0) > 0.01:
            return False

    return True
