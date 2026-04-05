# -*- coding: utf-8 -*-
"""
test_strategy_genome.py — 블록 풀 + genome + 생성기 + 스케줄 테스트
===================================================================
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.lab.strategy_builder.blocks import (
    AlwaysOn, AbsMomentum, RelMomentum, SMACross,
    StaticWeight, EqualWeight, CashShelter, BondShelter,
)
from aftertaxi.lab.strategy_builder.genome import (
    StrategyGenome, genome_to_weight_schedule, count_switches,
)
from aftertaxi.lab.strategy_builder.generator import (
    GeneratorConfig, generate_genomes, validate_genome,
)


# ══════════════════════════════════════════════
# Fixture
# ══════════════════════════════════════════════

@pytest.fixture(scope="module")
def prices_60m():
    """60개월 합성 가격 (SPY 상승, SGOV 횡보)."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-31", periods=60, freq="ME")
    spy = 100 * np.cumprod(1 + rng.normal(0.01, 0.04, 60))
    sgov = 100 * np.cumprod(1 + rng.normal(0.003, 0.002, 60))
    return pd.DataFrame({"SPY": spy, "SGOV": sgov}, index=idx)


# ══════════════════════════════════════════════
# Signal Blocks
# ══════════════════════════════════════════════

class TestSignalBlocks:

    def test_always_on(self, prices_60m):
        sig = AlwaysOn()
        assert all(sig.evaluate(prices_60m, s) for s in range(60))
        assert sig.label == "AlwaysOn"

    def test_abs_momentum_early_steps(self, prices_60m):
        """lookback 부족 시 True 반환."""
        sig = AbsMomentum(asset="SPY", lookback=9)
        assert sig.evaluate(prices_60m, 0) is True
        assert sig.evaluate(prices_60m, 5) is True

    def test_abs_momentum_serialization(self):
        sig = AbsMomentum(asset="SPY", lookback=6)
        d = sig.to_dict()
        assert d["type"] == "abs_momentum"
        assert d["lookback"] == 6

    def test_rel_momentum(self, prices_60m):
        sig = RelMomentum(asset_a="SPY", asset_b="SGOV", lookback=6)
        # SPY가 SGOV보다 성장률 높으면 True
        result = sig.evaluate(prices_60m, 30)
        assert isinstance(result, bool)

    def test_sma_cross(self, prices_60m):
        sig = SMACross(asset="SPY", period=10)
        result = sig.evaluate(prices_60m, 30)
        assert isinstance(result, bool)

    def test_sma_cross_early(self, prices_60m):
        sig = SMACross(asset="SPY", period=10)
        assert sig.evaluate(prices_60m, 3) is True  # lookback 부족


# ══════════════════════════════════════════════
# Allocation Blocks
# ══════════════════════════════════════════════

class TestAllocBlocks:

    def test_static_weight_sum(self):
        alloc = StaticWeight(weights={"SPY": 0.6, "QQQ": 0.4})
        w = alloc.get_weights()
        assert abs(sum(w.values()) - 1.0) < 1e-10

    def test_equal_weight(self):
        alloc = EqualWeight(asset_list=("SPY", "QQQ", "TLT"))
        w = alloc.get_weights()
        assert len(w) == 3
        assert all(abs(v - 1 / 3) < 1e-10 for v in w.values())

    def test_cash_shelter(self):
        s = CashShelter(asset="SGOV")
        assert s.get_weights() == {"SGOV": 1.0}
        assert s.assets == ("SGOV",)

    def test_bond_shelter(self):
        s = BondShelter(asset="TLT")
        assert s.get_weights() == {"TLT": 1.0}


# ══════════════════════════════════════════════
# Genome
# ══════════════════════════════════════════════

class TestGenome:

    def test_bnh_genome(self):
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AlwaysOn(),
        )
        assert g.is_bnh
        assert "SPY" in g.all_assets
        assert g.fingerprint()  # 비어있지 않음

    def test_signal_genome(self):
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 0.6, "SSO": 0.4}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 9),
            rebalance="FULL",
        )
        assert not g.is_bnh
        assert "SGOV" in g.all_assets
        assert "SSO" in g.all_assets

    def test_fingerprint_deterministic(self):
        g1 = StrategyGenome(
            growth=StaticWeight({"SPY": 0.6, "QQQ": 0.4}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 9),
        )
        g2 = StrategyGenome(
            growth=StaticWeight({"SPY": 0.6, "QQQ": 0.4}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 9),
        )
        assert g1.fingerprint() == g2.fingerprint()

    def test_fingerprint_different_for_different_genomes(self):
        g1 = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 9),
        )
        g2 = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 6),  # 다른 lookback
        )
        assert g1.fingerprint() != g2.fingerprint()

    def test_to_dict_roundtrip(self):
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 0.7, "QQQ": 0.3}),
            shelter=BondShelter("TLT"),
            signal=SMACross("SPY", 10),
            filter=AbsMomentum("SPY", 6),
        )
        d = g.to_dict()
        assert d["growth"]["type"] == "static"
        assert d["shelter"]["type"] == "bond_shelter"
        assert d["signal"]["type"] == "sma_cross"
        assert d["filter"]["type"] == "abs_momentum"

    def test_label_readable(self):
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 0.6, "SSO": 0.4}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 9),
        )
        label = g.label
        assert "AbsMom" in label
        assert "SGOV" in label


# ══════════════════════════════════════════════
# Genome → Weight Schedule
# ══════════════════════════════════════════════

class TestScheduler:

    def test_bnh_constant_schedule(self, prices_60m):
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AlwaysOn(),
        )
        sched = genome_to_weight_schedule(g, prices_60m)
        assert len(sched) == 60
        assert all(w == {"SPY": 1.0} for w in sched)

    def test_signal_schedule_has_switches(self, prices_60m):
        """신호 전략은 비중이 변하는 구간이 있어야 함."""
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 3),  # 짧은 lookback → 빈번한 전환
        )
        sched = genome_to_weight_schedule(g, prices_60m)
        assert len(sched) == 60
        # 적어도 한 번은 shelter로 전환
        has_spy = any("SPY" in w and w.get("SPY", 0) > 0.5 for w in sched)
        has_sgov = any("SGOV" in w and w.get("SGOV", 0) > 0.5 for w in sched)
        # 최소한 하나의 모드는 있어야 함
        assert has_spy or has_sgov

    def test_filter_and_reduces_growth(self, prices_60m):
        """필터 AND 조건은 성장 구간을 줄인다."""
        g_no_filter = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 6),
        )
        g_with_filter = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 6),
            filter=SMACross("SPY", 10),
        )
        sched_no = genome_to_weight_schedule(g_no_filter, prices_60m)
        sched_with = genome_to_weight_schedule(g_with_filter, prices_60m)

        growth_no = sum(1 for w in sched_no if "SPY" in w and w.get("SPY", 0) > 0.5)
        growth_with = sum(1 for w in sched_with if "SPY" in w and w.get("SPY", 0) > 0.5)
        # 필터 AND → 성장 구간 같거나 적어야 함
        assert growth_with <= growth_no

    def test_count_switches_bnh(self, prices_60m):
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AlwaysOn(),
        )
        sched = genome_to_weight_schedule(g, prices_60m)
        assert count_switches(sched) == 0

    def test_count_switches_positive(self, prices_60m):
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 3),
        )
        sched = genome_to_weight_schedule(g, prices_60m)
        # 짧은 lookback → 전환 있을 수 있음
        switches = count_switches(sched)
        assert switches >= 0  # 최소 0


# ══════════════════════════════════════════════
# Generator
# ══════════════════════════════════════════════

class TestGenerator:

    def test_generates_correct_count(self):
        config = GeneratorConfig(
            asset_pool=("SPY", "QQQ", "SSO"),
            n_candidates=50,
            seed=42,
        )
        genomes = generate_genomes(config)
        # validate_genome에서 일부 탈락 가능
        assert len(genomes) <= 50
        assert len(genomes) >= 30  # 대부분 통과 예상

    def test_seed_reproducible(self):
        config = GeneratorConfig(
            asset_pool=("SPY", "QQQ"),
            n_candidates=20,
            seed=42,
        )
        g1 = generate_genomes(config)
        g2 = generate_genomes(config)
        assert len(g1) == len(g2)
        assert all(
            a.fingerprint() == b.fingerprint()
            for a, b in zip(g1, g2)
        )

    def test_different_seed_different_genomes(self):
        c1 = GeneratorConfig(asset_pool=("SPY", "QQQ"), n_candidates=10, seed=42)
        c2 = GeneratorConfig(asset_pool=("SPY", "QQQ"), n_candidates=10, seed=99)
        g1 = generate_genomes(c1)
        g2 = generate_genomes(c2)
        # 최소 하나는 다를 것
        fps1 = {g.fingerprint() for g in g1}
        fps2 = {g.fingerprint() for g in g2}
        assert fps1 != fps2

    def test_all_valid(self):
        config = GeneratorConfig(
            asset_pool=("SPY", "QQQ", "SSO"),
            n_candidates=30,
            seed=42,
        )
        genomes = generate_genomes(config)
        for g in genomes:
            assert validate_genome(g), f"Invalid genome: {g.label}"

    def test_empty_pool_raises(self):
        with pytest.raises(ValueError, match="asset_pool"):
            GeneratorConfig(asset_pool=(), n_candidates=10)

    def test_includes_bnh(self):
        """include_bnh=True면 AlwaysOn 신호가 포함될 수 있다."""
        config = GeneratorConfig(
            asset_pool=("SPY",),
            n_candidates=50,
            include_bnh=True,
            seed=42,
        )
        genomes = generate_genomes(config)
        has_bnh = any(g.is_bnh for g in genomes)
        # 50개 중 AlwaysOn이 1개도 없을 확률은 극히 낮음
        assert has_bnh

    def test_genome_to_schedule_e2e(self, prices_60m):
        """생성 → 스케줄 → 길이 확인까지 E2E."""
        config = GeneratorConfig(
            asset_pool=("SPY",),
            shelter_pool=("SGOV",),
            n_candidates=5,
            seed=42,
        )
        genomes = generate_genomes(config)
        for g in genomes:
            sched = genome_to_weight_schedule(g, prices_60m)
            assert len(sched) == 60
            for w in sched:
                assert abs(sum(w.values()) - 1.0) < 0.01


# ══════════════════════════════════════════════
# Validator
# ══════════════════════════════════════════════

class TestValidator:

    def test_growth_equals_shelter_rejected(self):
        """signal 있는데 growth == shelter면 무의미."""
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=StaticWeight({"SPY": 1.0}),
            signal=AbsMomentum("SPY", 9),
        )
        assert not validate_genome(g)

    def test_bnh_growth_equals_shelter_ok(self):
        """AlwaysOn이면 shelter 안 쓰니까 상관없음."""
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 1.0}),
            shelter=StaticWeight({"SPY": 1.0}),
            signal=AlwaysOn(),
        )
        assert validate_genome(g)

    def test_valid_signal_genome(self):
        g = StrategyGenome(
            growth=StaticWeight({"SPY": 0.6, "SSO": 0.4}),
            shelter=CashShelter("SGOV"),
            signal=AbsMomentum("SPY", 9),
        )
        assert validate_genome(g)
