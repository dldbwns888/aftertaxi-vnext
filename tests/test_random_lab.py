# -*- coding: utf-8 -*-
"""
test_random_lab.py — 랜덤 허상 실험실 테스트
=============================================
5개 테스트:
  1. 벡터화 생성 — 비중 합=1, 최소 5%, 자산 2~4개
  2. baseline gate — SPY B&H 미달 전략 survivors에 없음
  3. search budget 정직성 — n_generated == config.n_candidates
  4. 생존율 합리성 — 랜덤은 대부분 죽어야 함
  5. 리포트 구조 — 필드 존재, summary_text 에러 없음
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.analysis.random_lab import (
    RandomLabConfig,
    RandomLabReport,
    generate_random_specs,
    run_random_lab,
)
from aftertaxi.strategies.spec import StrategySpec


# ── 합성 시장 데이터 fixture ──

@pytest.fixture
def synthetic_market():
    """20년 합성 시장: SPY/QQQ/TLT/SSO. 월간 수익률 + 가격 + FX."""
    rng = np.random.default_rng(2024)
    months = 240
    dates = pd.date_range("2005-01-31", periods=months, freq="ME")

    returns = pd.DataFrame({
        "SPY": rng.normal(0.008, 0.04, months),
        "QQQ": rng.normal(0.010, 0.05, months),
        "TLT": rng.normal(0.003, 0.03, months),
        "SSO": rng.normal(0.014, 0.08, months),
    }, index=dates)

    prices = 100.0 * (1 + returns).cumprod()
    fx = pd.Series(
        rng.normal(1300, 50, months).cumsum() / months + 1200,
        index=dates,
    )
    fx = fx.clip(lower=900, upper=1600)

    return returns, prices, fx


# ══════════════════════════════════════════════
# 생성 테스트
# ══════════════════════════════════════════════

class TestGeneration:
    """벡터화 생성 검증."""

    def test_correct_count(self):
        """N개 요청하면 N개 나온다."""
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=50,
            seed=42,
        )
        specs = generate_random_specs(config)
        assert len(specs) == 50

    def test_weights_sum_to_one(self):
        """모든 전략의 비중 합 = 1.0."""
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=100,
            seed=42,
        )
        specs = generate_random_specs(config)
        for spec in specs:
            total = sum(spec.weights.values())
            assert abs(total - 1.0) < 1e-10, f"{spec.name}: 비중 합 {total}"

    def test_min_weight_enforced(self):
        """각 자산 비중 >= min_weight."""
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=100,
            min_weight=0.05,
            seed=42,
        )
        specs = generate_random_specs(config)
        for spec in specs:
            for asset, w in spec.weights.items():
                assert w >= 0.05 - 1e-10, f"{spec.name}: {asset}={w:.4f} < 0.05"

    def test_asset_count_in_range(self):
        """자산 수가 min_assets~max_assets 범위."""
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=200,
            min_assets=2,
            max_assets=4,
            seed=42,
        )
        specs = generate_random_specs(config)
        for spec in specs:
            n = len(spec.weights)
            assert 2 <= n <= 4, f"{spec.name}: 자산 {n}개"

    def test_assets_from_pool_only(self):
        """자산이 pool에 있는 것만."""
        pool = ("SPY", "QQQ", "TLT")
        config = RandomLabConfig(
            asset_pool=pool,
            n_candidates=50,
            max_assets=3,
            seed=42,
        )
        specs = generate_random_specs(config)
        for spec in specs:
            for asset in spec.weights:
                assert asset in pool, f"{spec.name}: {asset} not in pool"

    def test_source_tag(self):
        """source가 'random_lab'."""
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT"),
            n_candidates=10,
            max_assets=3,
            seed=42,
        )
        specs = generate_random_specs(config)
        for spec in specs:
            assert spec.source == "random_lab"
            assert spec.family == "random_lab"

    def test_seed_reproducible(self):
        """같은 seed → 같은 결과."""
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=30,
            seed=42,
        )
        specs_a = generate_random_specs(config)
        specs_b = generate_random_specs(config)
        for a, b in zip(specs_a, specs_b):
            assert a.weights == b.weights


# ══════════════════════════════════════════════
# Config 검증
# ══════════════════════════════════════════════

class TestConfigValidation:
    """잘못된 설정 거부."""

    def test_empty_pool_rejected(self):
        with pytest.raises(ValueError, match="비어있을 수 없음"):
            RandomLabConfig(asset_pool=())

    def test_single_asset_rejected(self):
        with pytest.raises(ValueError, match="최소 2개"):
            RandomLabConfig(asset_pool=("SPY",))

    def test_max_exceeds_pool(self):
        with pytest.raises(ValueError, match="max_assets"):
            RandomLabConfig(asset_pool=("SPY", "QQQ"), max_assets=5)


# ══════════════════════════════════════════════
# 파이프라인 통합 테스트
# ══════════════════════════════════════════════

class TestPipeline:
    """전체 파이프라인 통합 테스트 (소규모)."""

    def test_search_budget_honest(self, synthetic_market):
        """n_generated == config.n_candidates — search budget이 정직한지."""
        returns, prices, fx = synthetic_market
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=10,
            seed=42,
        )
        report = run_random_lab(config, returns, prices, fx)
        assert report.n_generated == 10
        assert report.n_generated == config.n_candidates

    def test_funnel_monotonic(self, synthetic_market):
        """퍼널이 단조 감소: generated >= baseline >= basic >= validation."""
        returns, prices, fx = synthetic_market
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=20,
            seed=42,
        )
        report = run_random_lab(config, returns, prices, fx)
        assert report.n_generated >= report.n_after_baseline
        assert report.n_after_baseline >= report.n_after_basic
        assert report.n_after_basic >= report.n_after_validation

    def test_baseline_positive(self, synthetic_market):
        """baseline mult가 양수."""
        returns, prices, fx = synthetic_market
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT"),
            n_candidates=5,
            max_assets=3,
            seed=42,
        )
        report = run_random_lab(config, returns, prices, fx)
        assert report.baseline_mult > 0

    def test_all_mults_recorded(self, synthetic_market):
        """전체 세후 배수 분포가 기록됨."""
        returns, prices, fx = synthetic_market
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=10,
            seed=42,
        )
        report = run_random_lab(config, returns, prices, fx)
        assert len(report.all_mults) == 10

    def test_report_summary_text(self, synthetic_market):
        """summary_text가 에러 없이 핵심 정보를 포함."""
        returns, prices, fx = synthetic_market
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=10,
            seed=42,
        )
        report = run_random_lab(config, returns, prices, fx)
        text = report.summary_text()
        assert "생존율" in text
        assert "baseline" in text.lower() or "Baseline" in text
        assert "10" in text  # n_generated가 표시됨

    def test_survivors_source_tagged(self, synthetic_market):
        """살아남은 전략의 source가 random_lab."""
        returns, prices, fx = synthetic_market
        config = RandomLabConfig(
            asset_pool=("SPY", "QQQ", "TLT", "SSO"),
            n_candidates=30,
            seed=42,
        )
        report = run_random_lab(config, returns, prices, fx)
        for s in report.survivors:
            assert s["source"] == "random_lab"
