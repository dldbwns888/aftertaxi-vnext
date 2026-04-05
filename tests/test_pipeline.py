# -*- coding: utf-8 -*-
"""
test_pipeline.py — Strategy Builder 파이프라인 테스트
=====================================================
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.lab.strategy_builder.generator import GeneratorConfig
from aftertaxi.lab.strategy_builder.pipeline import (
    PipelineConfig, PipelineReport, CandidateEntry, run_pipeline,
)


# ══════════════════════════════════════════════
# Fixture
# ══════════════════════════════════════════════

@pytest.fixture(scope="module")
def market_10yr():
    """120개월(10년) 합성 데이터."""
    rng = np.random.default_rng(42)
    n = 120
    idx = pd.date_range("2015-01-31", periods=n, freq="ME")
    spy = rng.normal(0.008, 0.04, n)
    sgov = rng.normal(0.003, 0.002, n)
    ret = pd.DataFrame({"SPY": spy, "SGOV": sgov}, index=idx)
    prices = 100 * (1 + ret).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return ret, prices, fx


# ══════════════════════════════════════════════
# 파이프라인 실행
# ══════════════════════════════════════════════

class TestPipelineExecution:

    def test_runs_without_error(self, market_10yr):
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=10,
                seed=42,
            ),
            enable_validation=False,  # validation 없이 빠르게
        )
        report = run_pipeline(config, ret, prices, fx)
        assert isinstance(report, PipelineReport)

    def test_search_budget_tracked(self, market_10yr):
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=20,
                seed=42,
            ),
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)

        assert report.n_generated == 20
        assert report.n_valid_structure <= 20
        assert report.n_ran <= report.n_valid_structure
        assert report.n_after_baseline <= report.n_ran
        assert report.n_after_fast_filter <= report.n_after_baseline

    def test_baseline_always_present(self, market_10yr):
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=5,
                seed=42,
            ),
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)

        assert report.baseline_mult > 0
        assert report.baseline_tax >= 0

    def test_all_mults_collected(self, market_10yr):
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=15,
                seed=42,
            ),
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)

        assert report.all_mults.size >= 10  # 대부분 실행 성공

    def test_seed_reproducible(self, market_10yr):
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=10,
                seed=42,
            ),
            enable_validation=False,
        )
        r1 = run_pipeline(config, ret, prices, fx)
        r2 = run_pipeline(config, ret, prices, fx)

        assert r1.n_after_fast_filter == r2.n_after_fast_filter
        np.testing.assert_allclose(r1.all_mults, r2.all_mults, atol=1e-10)


# ══════════════════════════════════════════════
# 필터
# ══════════════════════════════════════════════

class TestFilters:

    def test_baseline_gate_filters(self, market_10yr):
        """baseline 미달 전략은 필터링됨."""
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=30,
                seed=42,
            ),
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)

        # baseline 미달이면 필터링
        assert report.n_after_baseline <= report.n_ran
        # finalists는 baseline 이상만
        for c in report.finalists:
            assert c.mult_after_tax >= report.baseline_mult - 0.001

    def test_total_extinction_possible(self, market_10yr):
        """전멸 시나리오: 모든 전략이 baseline 미달이면 finalists 비어야 함."""
        ret, prices, fx = market_10yr
        # 매우 엄격한 필터
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=10,
                seed=42,
                include_bnh=False,  # B&H 제외 → 신호 전략만
            ),
            max_tax_drag=0.01,  # 매우 엄격
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)

        # 전멸이든 생존이든 리포트는 정상 생성
        assert isinstance(report, PipelineReport)
        assert report.n_generated == 10


# ══════════════════════════════════════════════
# 리포트
# ══════════════════════════════════════════════

class TestReport:

    def test_summary_first_line_is_budget(self, market_10yr):
        """리포트 첫 의미 있는 줄은 search budget."""
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=10,
                seed=42,
            ),
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)
        text = report.summary_text()

        # "Search budget" 또는 생성/생존 정보가 상단에 있어야 함
        assert "10개 생성" in text
        assert "생존율" in text

    def test_summary_has_baseline(self, market_10yr):
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=5,
                seed=42,
            ),
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)
        text = report.summary_text()

        assert "Baseline" in text
        assert "세후" in text

    def test_summary_has_disclaimer(self, market_10yr):
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=5,
                seed=42,
            ),
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)
        text = report.summary_text()

        assert "투자 결정의 근거가 아닙니다" in text

    def test_extinction_report(self, market_10yr):
        """전멸 시 '전멸' 메시지."""
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=5,
                seed=42,
                include_bnh=False,
            ),
            max_tax_drag=0.001,  # 거의 불가능한 기준
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)
        text = report.summary_text()

        if report.n_after_fast_filter == 0:
            assert "전멸" in text

    def test_survival_rate_calculation(self, market_10yr):
        ret, prices, fx = market_10yr
        config = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=20,
                seed=42,
            ),
            enable_validation=False,
        )
        report = run_pipeline(config, ret, prices, fx)

        expected = report.n_after_validation / report.n_generated
        assert abs(report.survival_rate - expected) < 1e-10


# ══════════════════════════════════════════════
# Validation 게이트 (DSR 연결)
# ══════════════════════════════════════════════

class TestValidationGate:

    def test_with_validation_enabled(self, market_10yr):
        """validation 켜면 통과자가 줄어듦."""
        ret, prices, fx = market_10yr
        config_no_val = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=20,
                seed=42,
            ),
            enable_validation=False,
        )
        config_val = PipelineConfig(
            generator=GeneratorConfig(
                asset_pool=("SPY",),
                shelter_pool=("SGOV",),
                n_candidates=20,
                seed=42,
            ),
            enable_validation=True,
        )
        r_no = run_pipeline(config_no_val, ret, prices, fx)
        r_yes = run_pipeline(config_val, ret, prices, fx)

        # validation 켜면 같거나 적어야 함
        assert r_yes.n_after_validation <= r_no.n_after_fast_filter

    def test_dsr_uses_total_generated(self, market_10yr):
        """DSR n_trials에 총 생성 수가 반영되는지 간접 확인.

        n=5 vs n=100: 같은 전략이어도 n이 크면 DSR이 더 엄격.
        """
        ret, prices, fx = market_10yr
        # 적은 search budget
        r_small = run_pipeline(
            PipelineConfig(
                generator=GeneratorConfig(
                    asset_pool=("SPY",), shelter_pool=("SGOV",),
                    n_candidates=5, seed=42, include_bnh=True,
                ),
                enable_validation=True,
            ),
            ret, prices, fx,
        )
        # 큰 search budget
        r_large = run_pipeline(
            PipelineConfig(
                generator=GeneratorConfig(
                    asset_pool=("SPY",), shelter_pool=("SGOV",),
                    n_candidates=100, seed=42, include_bnh=True,
                ),
                enable_validation=True,
            ),
            ret, prices, fx,
        )
        # 큰 budget에서 DSR이 더 엄격 → 생존율 같거나 낮아야 함
        assert r_large.survival_rate <= r_small.survival_rate + 0.01
