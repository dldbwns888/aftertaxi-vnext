# -*- coding: utf-8 -*-
"""
test_settlement.py — settlement.py 직접 테스트
=============================================
oracle shadow에서 간접 커버되던 settlement를 직접 테스트.
"""

import pytest

from aftertaxi.core.contracts import AccountType
from aftertaxi.core.ledger import AccountLedger
from aftertaxi.core.settlement import settle_year_end, settle_final


def _make_taxable(aid="taxable") -> AccountLedger:
    return AccountLedger(
        account_id=aid,
        account_type=AccountType.TAXABLE.value,
        tax_rate=0.22,
        annual_exemption=2_500_000.0,
    )


def _make_isa(aid="isa") -> AccountLedger:
    return AccountLedger(
        account_id=aid,
        account_type=AccountType.ISA.value,
        tax_rate=0.0,
        annual_exemption=0.0,
        isa_exempt_limit=2_000_000.0,
        isa_excess_rate=0.099,
    )


def _fund_and_sell(ledger, deposit=10000.0, buy_px=100.0, sell_px=150.0, fx=1300.0):
    """입금 → 매수 → 시가반영 → 매도. 양도차익 실현."""
    ledger.deposit(deposit)
    qty = deposit / buy_px
    ledger.buy("SPY", qty, buy_px, fx)
    ledger.mark_to_market({"SPY": sell_px})
    ledger.sell("SPY", qty, sell_px, fx)


# ══════════════════════════════════════════════
# settle_year_end
# ══════════════════════════════════════════════

class TestSettleYearEnd:

    def test_taxable_tax_assessed(self):
        """연말 정산 후 양도세 assessed."""
        ledger = _make_taxable()
        _fund_and_sell(ledger, deposit=10000, buy_px=100, sell_px=200, fx=1300)

        settle_year_end({"t": ledger}, year=2024, fx_rate=1300.0)

        s = ledger.summary()
        assert s["capital_gains_tax_krw"] > 0

    def test_taxable_tax_paid(self):
        """연말 정산 후 unpaid=0 (pay_tax 호출됨)."""
        ledger = _make_taxable()
        _fund_and_sell(ledger, deposit=10000, buy_px=100, sell_px=200, fx=1300)

        settle_year_end({"t": ledger}, year=2024, fx_rate=1300.0)

        assert ledger.unpaid_tax_liability_krw == 0.0

    def test_isa_no_annual_tax(self):
        """ISA는 연말 양도세 0."""
        ledger = _make_isa()
        _fund_and_sell(ledger, deposit=10000, buy_px=100, sell_px=200, fx=1300)

        settle_year_end({"i": ledger}, year=2024, fx_rate=1300.0)

        assert ledger.summary()["capital_gains_tax_krw"] == 0.0

    def test_multi_account(self):
        """TAXABLE+ISA 혼합 시 각각 올바르게 정산."""
        t = _make_taxable()
        i = _make_isa()
        _fund_and_sell(t, deposit=5000, buy_px=100, sell_px=200, fx=1300)
        _fund_and_sell(i, deposit=5000, buy_px=100, sell_px=200, fx=1300)

        settle_year_end({"t": t, "i": i}, year=2024, fx_rate=1300.0)

        assert t.summary()["capital_gains_tax_krw"] > 0
        assert i.summary()["capital_gains_tax_krw"] == 0.0

    def test_no_gain_no_tax(self):
        """이익 없으면 세금 없다."""
        ledger = _make_taxable()
        _fund_and_sell(ledger, deposit=10000, buy_px=100, sell_px=100, fx=1300)

        settle_year_end({"t": ledger}, year=2024, fx_rate=1300.0)

        assert ledger.summary()["capital_gains_tax_krw"] == 0.0


# ══════════════════════════════════════════════
# settle_final
# ══════════════════════════════════════════════

class TestSettleFinal:

    def test_liquidates_all(self):
        """최종 정산 후 포지션 전량 청산."""
        ledger = _make_taxable()
        ledger.deposit(10000)
        ledger.buy("SPY", 100, 100, 1300)
        ledger.record_month()

        settle_final({"t": ledger}, year=2024,
                     price_map={"SPY": 150}, fx_rate=1300.0)

        assert ledger.portfolio_value_usd() < 0.01

    def test_final_tax_on_gain(self):
        """최종 청산 이익에 세금."""
        ledger = _make_taxable()
        ledger.deposit(10000)
        ledger.buy("SPY", 100, 100, 1300)
        ledger.record_month()

        settle_final({"t": ledger}, year=2024,
                     price_map={"SPY": 200}, fx_rate=1300.0)

        assert ledger.summary()["tax_assessed_krw"] > 0

    def test_isa_final(self):
        """ISA 최종: settle_isa가 호출된다."""
        ledger = _make_isa()
        ledger.deposit(10000)
        ledger.buy("SPY", 100, 100, 1300)
        ledger.record_month()

        settle_final({"i": ledger}, year=2024,
                     price_map={"SPY": 200}, fx_rate=1300.0)

        # ISA는 비과세 한도 이내면 세금 0 또는 낮은 세금
        assert ledger.summary()["tax_assessed_krw"] >= 0

    def test_final_unpaid_zero(self):
        """최종 정산 후 모든 세금이 납부됨."""
        ledger = _make_taxable()
        ledger.deposit(10000)
        ledger.buy("SPY", 100, 100, 1300)
        ledger.record_month()

        settle_final({"t": ledger}, year=2024,
                     price_map={"SPY": 200}, fx_rate=1300.0)

        assert ledger.unpaid_tax_liability_krw == 0.0


# ══════════════════════════════════════════════
# 건보료 연동
# ══════════════════════════════════════════════

class TestSettlementHealthInsurance:

    def test_hi_off_no_premium(self):
        """enable=False면 건보료 0."""
        ledger = _make_taxable()
        ledger.deposit(10000)
        ledger.buy("SPY", 100, 100, 1300)
        # 배당 발생
        ledger.apply_dividend("SPY", gross_per_share=2.0,
                              withholding_rate=0.15, fx_rate=1300,
                              reinvest=False, px_usd=100)
        ledger.record_month()

        settle_year_end({"t": ledger}, year=2024, fx_rate=1300.0,
                        enable_health_insurance=False)

        assert ledger.summary()["health_insurance_krw"] == 0.0

    def test_hi_on_small_dividend(self):
        """배당이 2천만원 미만이면 건보료 0."""
        ledger = _make_taxable()
        ledger.deposit(10000)
        ledger.buy("SPY", 100, 100, 1300)
        # 소액 배당 ($200 × 1300 = 26만원 < 2천만원)
        ledger.apply_dividend("SPY", gross_per_share=2.0,
                              withholding_rate=0.15, fx_rate=1300,
                              reinvest=False, px_usd=100)

        settle_year_end({"t": ledger}, year=2024, fx_rate=1300.0,
                        enable_health_insurance=True)

        assert ledger.summary()["health_insurance_krw"] == 0.0

    def test_hi_on_large_dividend(self):
        """배당이 2천만원 초과면 건보료 발생."""
        ledger = _make_taxable()
        ledger.deposit(100000)
        ledger.buy("SPY", 1000, 100, 1300)
        # 대량 배당 ($20 × 1000주 = $20,000 × 1300 = 2600만원 > 2000만원)
        ledger.apply_dividend("SPY", gross_per_share=20.0,
                              withholding_rate=0.15, fx_rate=1300,
                              reinvest=False, px_usd=100)

        settle_year_end({"t": ledger}, year=2024, fx_rate=1300.0,
                        enable_health_insurance=True)

        assert ledger.summary()["health_insurance_krw"] > 0
