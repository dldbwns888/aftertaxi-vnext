# -*- coding: utf-8 -*-
"""
test_tax_engine.py — 세금 순수 함수 단위 테스트
================================================
ledger 없이 tax_engine만 테스트. 상태 없음 보장.
"""

import pytest

from aftertaxi.core.tax_engine import (
    compute_capital_gains_tax,
    compute_isa_settlement,
    CapitalGainsTaxResult,
    ISASettlementResult,
)


class TestCapitalGainsTax:

    def test_simple_gain(self):
        """단순 이익: 500만 이익, 250만 공제, 세율 22%."""
        r = compute_capital_gains_tax(
            realized_gain_krw=5_000_000,
            realized_loss_krw=0,
            carryforward=[], current_year=2023,
        )
        assert abs(r.tax_krw - (2_500_000 * 0.22)) < 1.0
        assert abs(r.exemption_used_krw - 2_500_000) < 1.0
        assert abs(r.taxable_base_krw - 2_500_000) < 1.0

    def test_gain_below_exemption(self):
        """이익이 공제 이하면 세금 0."""
        r = compute_capital_gains_tax(
            realized_gain_krw=2_000_000,
            realized_loss_krw=0,
            carryforward=[], current_year=2023,
        )
        assert r.tax_krw == 0.0
        assert abs(r.exemption_used_krw - 2_000_000) < 1.0

    def test_net_loss_creates_carry(self):
        """순손실 → 이월결손금 생성."""
        r = compute_capital_gains_tax(
            realized_gain_krw=100_000,
            realized_loss_krw=500_000,
            carryforward=[], current_year=2023,
        )
        assert r.tax_krw == 0.0
        assert len(r.new_loss_carry) == 1
        assert r.new_loss_carry[0] == (2023, 400_000)

    def test_carryforward_offset_preserves_year(self):
        """이월결손금 부분상쇄 시 연도 유지."""
        r = compute_capital_gains_tax(
            realized_gain_krw=600_000,
            realized_loss_krw=0,
            carryforward=[(2020, 1_000_000)],
            current_year=2023,
        )
        assert r.tax_krw == 0.0  # 600k < 1M carry
        assert len(r.carryforward_remaining) == 1
        yr, amt = r.carryforward_remaining[0]
        assert yr == 2020  # 연도 유지!
        assert abs(amt - 400_000) < 1.0
        assert len(r.carryforward_used) == 1
        assert r.carryforward_used[0] == (2020, 600_000)

    def test_multi_year_carry_fifo(self):
        """여러 연도 이월결손금 — 오래된 것부터 소진."""
        r = compute_capital_gains_tax(
            realized_gain_krw=300_000,
            realized_loss_krw=0,
            carryforward=[(2019, 200_000), (2021, 500_000)],
            current_year=2023,
        )
        # 2019년 200k 전소, 2021년 100k 소진 → 400k 남음
        assert len(r.carryforward_used) == 2
        assert r.carryforward_used[0] == (2019, 200_000)
        assert r.carryforward_used[1] == (2021, 100_000)
        assert len(r.carryforward_remaining) == 1
        assert r.carryforward_remaining[0][0] == 2021
        assert abs(r.carryforward_remaining[0][1] - 400_000) < 1.0

    def test_expiry(self):
        """5년 만료."""
        r = compute_capital_gains_tax(
            realized_gain_krw=100_000,
            realized_loss_krw=0,
            carryforward=[(2017, 500_000)],  # 6년 전 → 만료
            current_year=2023,
        )
        # carry 사용 불가, 100k에 공제 적용
        assert len(r.carryforward_used) == 0
        assert len(r.carryforward_remaining) == 0
        assert r.tax_krw == 0.0  # 100k < 250만 공제

    def test_loss_preserves_old_carry(self):
        """순손실 시 기존 carry 보존 (L2 regression)."""
        r = compute_capital_gains_tax(
            realized_gain_krw=0,
            realized_loss_krw=200_000,
            carryforward=[(2020, 500_000)],
            current_year=2022,
        )
        assert len(r.carryforward_remaining) == 1
        assert r.carryforward_remaining[0] == (2020, 500_000)
        assert len(r.new_loss_carry) == 1
        assert r.new_loss_carry[0] == (2022, 200_000)

    def test_pure_function_no_side_effects(self):
        """같은 입력 → 같은 출력. 상태 없음."""
        args = dict(
            realized_gain_krw=1_000_000,
            realized_loss_krw=0,
            carryforward=[(2020, 300_000)],
            current_year=2023,
        )
        r1 = compute_capital_gains_tax(**args)
        r2 = compute_capital_gains_tax(**args)
        assert r1.tax_krw == r2.tax_krw
        assert r1.carryforward_remaining == r2.carryforward_remaining


class TestISASettlement:

    def test_below_exempt(self):
        """순이익이 비과세 한도 이하면 세금 0."""
        r = compute_isa_settlement(1_500_000, 0)
        assert r.tax_krw == 0.0
        assert abs(r.exempt_amount_krw - 1_500_000) < 1.0

    def test_above_exempt(self):
        """순이익 500만, 비과세 200만 → 초과 300만에 9.9%."""
        r = compute_isa_settlement(5_000_000, 0)
        assert abs(r.tax_krw - (3_000_000 * 0.099)) < 1.0
        assert abs(r.excess_amount_krw - 3_000_000) < 1.0

    def test_net_loss(self):
        """순손실이면 세금 0."""
        r = compute_isa_settlement(1_000_000, 3_000_000)
        assert r.tax_krw == 0.0
        assert r.net_gain_krw < 0

    def test_loss_offsets_gain(self):
        """이익 300만, 손실 200만 → 순이익 100만 < 200만 비과세."""
        r = compute_isa_settlement(3_000_000, 2_000_000)
        assert r.tax_krw == 0.0
        assert abs(r.net_gain_krw - 1_000_000) < 1.0


# ══════════════════════════════════════════════
# 배당소득세
# ══════════════════════════════════════════════

class TestDividendTax:

    def test_below_threshold_no_additional(self):
        """금융소득 2천만원 이하 → 분리과세, 추가 세금 0."""
        from aftertaxi.core.tax_engine import compute_dividend_tax
        r = compute_dividend_tax(
            annual_dividend_gross_usd=10_000,  # $10k × 1300 = 1300만
            annual_withholding_usd=1_500,
            fx_rate=1300,
        )
        assert not r.is_comprehensive
        assert r.additional_tax_krw == 0.0
        assert abs(r.annual_dividend_gross_krw - 13_000_000) < 1.0

    def test_above_threshold_comprehensive(self):
        """금융소득 2천만원 초과 → 종합과세, 추가 세금 발생."""
        from aftertaxi.core.tax_engine import compute_dividend_tax
        r = compute_dividend_tax(
            annual_dividend_gross_usd=20_000,  # $20k × 1300 = 2600만 > 2000만
            annual_withholding_usd=3_000,
            fx_rate=1300,
        )
        assert r.is_comprehensive
        # domestic_tax = 26M × 0.154 = 4,004,000
        # credit = min(3.9M withholding, 4,004,000) = 3,900,000
        # additional = 4,004,000 - 3,900,000 = 104,000
        assert r.additional_tax_krw > 0
        assert r.foreign_tax_credit_krw > 0

    def test_withholding_fully_covers(self):
        """해외 원천징수가 국내 세율보다 높으면 추가 세금 0."""
        from aftertaxi.core.tax_engine import compute_dividend_tax
        r = compute_dividend_tax(
            annual_dividend_gross_usd=20_000,
            annual_withholding_usd=5_000,  # 25% 원천징수 > 15.4% 국내
            fx_rate=1300,
        )
        assert r.is_comprehensive
        assert r.additional_tax_krw == 0.0  # credit이 domestic_tax를 다 커버

    def test_zero_dividend(self):
        """배당 0이면 모든 값 0."""
        from aftertaxi.core.tax_engine import compute_dividend_tax
        r = compute_dividend_tax(0, 0, 1300)
        assert not r.is_comprehensive
        assert r.additional_tax_krw == 0.0
        assert r.annual_dividend_gross_krw == 0.0

    def test_fx_rate_applied(self):
        """환율이 결과에 반영."""
        from aftertaxi.core.tax_engine import compute_dividend_tax
        r1 = compute_dividend_tax(10_000, 1_500, fx_rate=1300)
        r2 = compute_dividend_tax(10_000, 1_500, fx_rate=1400)
        assert r2.annual_dividend_gross_krw > r1.annual_dividend_gross_krw
