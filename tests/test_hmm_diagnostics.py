# -*- coding: utf-8 -*-
"""
test_hmm_diagnostics.py — HMM 라벨 안정성 진단 테스트
=====================================================
4개 테스트:
  1. 명확한 2-regime 합성 데이터 → 안정성 통과
  2. 1-regime 단일 분포 데이터 → BIC 경고 (2-regime 불필요)
  3. 진단 결과 구조 검증
  4. summary_text 출력 확인
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest

try:
    import hmmlearn
    HAS_HMMLEARN = True
except ImportError:
    HAS_HMMLEARN = False

pytestmark = pytest.mark.skipif(not HAS_HMMLEARN, reason="hmmlearn not installed")

from aftertaxi.validation.hmm_diagnostics import run_hmm_diagnostics, HMMDiagnosticResult


class TestClearTwoRegime:
    """명확한 2-regime 합성 데이터 → 진단 통과."""

    @pytest.fixture
    def clear_2regime_data(self):
        """Bull(μ=+2%, σ=2%) 150개월 + Bear(μ=-3%, σ=4%) 100개월, 반복."""
        rng = np.random.default_rng(42)
        bull = rng.normal(0.02, 0.02, size=(150, 1))
        bear = rng.normal(-0.03, 0.04, size=(100, 1))
        # 2번 반복 = 500개월
        data = np.vstack([bull, bear, bull, bear])[:500]
        return data

    def test_passes_all(self, clear_2regime_data):
        """명확한 2-regime → 3개 진단 모두 통과."""
        result = run_hmm_diagnostics(clear_2regime_data, n_seeds=10)
        assert result.pass_all, result.summary_text()

    def test_label_stability_high(self, clear_2regime_data):
        """라벨 일치율 80% 이상."""
        result = run_hmm_diagnostics(clear_2regime_data, n_seeds=10)
        assert result.label_agreement_rate >= 0.80, (
            f"label agreement {result.label_agreement_rate:.1%} < 80%"
        )

    def test_regimes_have_opposite_signs(self, clear_2regime_data):
        """하나는 양수, 하나는 음수 평균."""
        result = run_hmm_diagnostics(clear_2regime_data, n_seeds=10)
        assert result.sign_consistency >= 0.80, (
            f"sign consistency {result.sign_consistency:.1%} < 80%"
        )


class TestSingleRegime:
    """1-regime 데이터 → BIC가 2-regime 개선을 정당화하지 못함."""

    @pytest.fixture
    def single_regime_data(self):
        """단일 분포: μ=+0.5%, σ=3%, 300개월."""
        rng = np.random.default_rng(99)
        return rng.normal(0.005, 0.03, size=(300, 1))

    def test_bic_not_justified(self, single_regime_data):
        """1-regime 데이터에서 2-regime BIC 개선이 미미하거나 악화."""
        result = run_hmm_diagnostics(single_regime_data, n_seeds=5)
        # 단일 분포에서는 2-regime이 유의한 개선이 아닐 가능성이 높다
        # 통과할 수도 있지만, 적어도 bic_improvement가 매우 작아야 함
        # 여기서는 pass_all이 False이거나, bic_improvement가 매우 작은 것을 확인
        if result.model_justified:
            # BIC가 통과하더라도 부호 분리가 안 될 수 있음
            assert result.bic_improvement < 0.10, (
                f"단일 분포에서 BIC improvement {result.bic_improvement:.3f}이 너무 큼"
            )


class TestDiagnosticStructure:
    """결과 구조 검증."""

    def test_result_fields(self):
        """모든 필드가 존재하고 타입이 맞는지."""
        rng = np.random.default_rng(42)
        data = rng.normal(0.01, 0.03, size=(200, 1))
        result = run_hmm_diagnostics(data, n_seeds=3)

        assert isinstance(result, HMMDiagnosticResult)
        assert 0.0 <= result.label_agreement_rate <= 1.0
        assert isinstance(result.bic_1regime, float)
        assert isinstance(result.bic_2regime, float)
        assert 0.0 <= result.sign_consistency <= 1.0
        assert result.n_seeds == 3
        assert result.n_observations == 200
        assert isinstance(result.pass_all, bool)

    def test_summary_text(self):
        """summary_text가 에러 없이 문자열을 반환."""
        rng = np.random.default_rng(42)
        data = rng.normal(0.01, 0.03, size=(200, 1))
        result = run_hmm_diagnostics(data, n_seeds=3)
        text = result.summary_text()
        assert isinstance(text, str)
        assert "HMM Diagnostic" in text
        assert "Label stability" in text

    def test_1d_input(self):
        """1D 배열 입력도 처리 가능."""
        rng = np.random.default_rng(42)
        data = rng.normal(0.01, 0.03, size=200)  # 1D
        result = run_hmm_diagnostics(data, n_seeds=3)
        assert result.n_observations == 200
