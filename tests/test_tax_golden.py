# -*- coding: utf-8 -*-
"""
tests/golden/test_tax_golden.py — 세금 골든 테스트
==================================================
실제 세법 예시 기반. 3자 대조: 법 조항 / 수기 계산 / 엔진 결과.

각 테스트는 독립적이며, 실패 시 세금 엔진의 정확도 문제를 의미.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from aftertaxi.core.tax_engine import (
    compute_capital_gains_tax,
    compute_isa_settlement,
    compute_dividend_tax,
)


class TestCapitalGainsTax:
    """양도소득세 22% + 기본공제 ₩250만."""

    def test_basic_gain_above_exemption(self):
        """양도차익 ₩1,000만. 공제 ₩250만. 과세표준 ₩750만. 세금 ₩165만.

        근거: 소득세법 제118조의2, 제118조의3.
        수기: (10,000,000 - 2,500,000) × 0.22 = 1,650,000
        """
        result = compute_capital_gains_tax(
            realized_gain_krw=10_000_000,
            realized_loss_krw=0,
            carryforward=[],
            current_year=2024,
            rate=0.22,
            exemption=2_500_000,
        )
        assert abs(result.tax_krw - 1_650_000) < 1, f"got {result.tax_krw}"

    def test_gain_below_exemption(self):
        """양도차익 ₩200만 < 공제 ₩250만. 세금 0.

        수기: 200만 - 250만 = 0 (음수면 0)
        """
        result = compute_capital_gains_tax(
            realized_gain_krw=2_000_000,
            realized_loss_krw=0,
            carryforward=[],
            current_year=2024,
            rate=0.22,
            exemption=2_500_000,
        )
        assert result.tax_krw == 0.0

    def test_gain_with_loss_offset(self):
        """양도차익 ₩1,500만, 양도차손 ₩500만. 순이익 ₩1,000만.
        공제 ₩250만. 과세표준 ₩750만. 세금 ₩165만.

        근거: 소득세법 제118조의4 (손익통산).
        수기: (15,000,000 - 5,000,000 - 2,500,000) × 0.22 = 1,650,000
        """
        result = compute_capital_gains_tax(
            realized_gain_krw=15_000_000,
            realized_loss_krw=5_000_000,
            carryforward=[],
            current_year=2024,
            rate=0.22,
            exemption=2_500_000,
        )
        assert abs(result.tax_krw - 1_650_000) < 1, f"got {result.tax_krw}"

    def test_loss_carryforward(self):
        """2023년 손실 ₩300만 이월 → 2024년 이익 ₩1,000만.
        순이익 ₩700만. 공제 ₩250만. 과세표준 ₩450만. 세금 ₩99만.

        근거: 소득세법 제118조의4 (이월결손금 5년).
        수기: (10,000,000 - 3,000,000 - 2,500,000) × 0.22 = 990,000
        """
        result = compute_capital_gains_tax(
            realized_gain_krw=10_000_000,
            realized_loss_krw=0,
            carryforward=[(2023, 3_000_000)],
            current_year=2024,
            rate=0.22,
            exemption=2_500_000,
        )
        assert abs(result.tax_krw - 990_000) < 1, f"got {result.tax_krw}"

    def test_net_loss_creates_carryforward(self):
        """순손실이면 세금 0 + 이월결손금 생성.

        차익 ₩100만, 차손 ₩500만. 순손실 ₩400만. 세금 0.
        """
        result = compute_capital_gains_tax(
            realized_gain_krw=1_000_000,
            realized_loss_krw=5_000_000,
            carryforward=[],
            current_year=2024,
            rate=0.22,
            exemption=2_500_000,
        )
        assert result.tax_krw == 0.0
        assert len(result.new_loss_carry) > 0  # 이월결손금 생성됨


class TestISASettlement:
    """ISA 비과세 ₩200만 + 초과분 9.9%."""

    def test_within_exempt(self):
        """순이익 ₩150만 < 비과세 ₩200만. 세금 0.

        근거: 조세특례제한법 제91조의18.
        """
        result = compute_isa_settlement(
            cumulative_gain_krw=1_500_000,
            cumulative_loss_krw=0,
            exempt_limit=2_000_000,
            excess_rate=0.099,
        )
        assert result.tax_krw == 0.0

    def test_above_exempt(self):
        """순이익 ₩500만. 비과세 ₩200만. 초과 ₩300만 × 9.9% = ₩297,000.

        수기: (5,000,000 - 2,000,000) × 0.099 = 297,000
        """
        result = compute_isa_settlement(
            cumulative_gain_krw=5_000_000,
            cumulative_loss_krw=0,
            exempt_limit=2_000_000,
            excess_rate=0.099,
        )
        assert abs(result.tax_krw - 297_000) < 1, f"got {result.tax_krw}"

    def test_gain_loss_netting(self):
        """ISA 내 손익통산. 이익 ₩800만, 손실 ₩200만. 순이익 ₩600만.
        비과세 ₩200만. 초과 ₩400만 × 9.9% = ₩396,000.

        수기: (8,000,000 - 2,000,000 - 2,000,000) × 0.099 = 396,000
        """
        result = compute_isa_settlement(
            cumulative_gain_krw=8_000_000,
            cumulative_loss_krw=2_000_000,
            exempt_limit=2_000_000,
            excess_rate=0.099,
        )
        assert abs(result.tax_krw - 396_000) < 1, f"got {result.tax_krw}"


class TestDividendTax:
    """배당소득 원천징수 + 종합과세."""

    def test_below_comprehensive_threshold(self):
        """연간 배당 ₩1,500만 < ₩2,000만. 원천징수로 종결. 추가세 0.

        근거: 소득세법 제14조.
        """
        result = compute_dividend_tax(
            annual_dividend_gross_usd=10_000,
            annual_withholding_usd=1_500,  # 15%
            fx_rate=1_300,  # ₩1,300만
        )
        # ₩1,300만 < ₩2,000만 → 추가세 없음
        assert result.additional_tax_krw == 0.0

    def test_above_comprehensive_threshold(self):
        """연간 배당이 ₩2,000만 초과 시 종합과세.

        gross $20,000 × 1,300 = ₩2,600만 > ₩2,000만 → 종합과세.
        """
        result = compute_dividend_tax(
            annual_dividend_gross_usd=20_000,
            annual_withholding_usd=3_000,  # 15%
            fx_rate=1_300,  # ₩2,600만
        )
        # 종합과세 적용 → 추가세 발생
        assert result.is_comprehensive is True
        assert result.additional_tax_krw >= 0  # 외국납부세액공제 후 음수가 될 수 있음
