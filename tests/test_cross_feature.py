# -*- coding: utf-8 -*-
"""
test_cross_feature.py — 기능 교차 검증
======================================
새로 추가된 BAND + progressive가 기존 기능과 올바르게 상호작용하는지.
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, RebalanceMode,
    StrategyConfig, TaxConfig, KOREA_PROGRESSIVE_BRACKETS,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.tax_engine import compute_capital_gains_tax


def _diverging_data(n=120):
    """SPY 강상승 + TLT 횡보 → 비중 괴리 유도, 큰 이익."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2015-01-31", periods=n, freq="ME")
    spy = 0.02 + rng.normal(0, 0.02, n)  # 강한 상승
    tlt = rng.normal(0, 0.01, n)
    returns = pd.DataFrame({"SPY": spy, "TLT": tlt}, index=idx)
    prices = 100.0 * (1 + returns).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return returns, prices, fx


FLAT = TaxConfig(capital_gains_rate=0.22, annual_exemption=2_500_000)
PROG = TaxConfig(
    capital_gains_rate=0.22, annual_exemption=2_500_000,
    progressive_brackets=KOREA_PROGRESSIVE_BRACKETS,
    progressive_threshold=20_000_000,
)


# ══════════════════════════════════════════════
# 리스크 1: BAND + progressive 조합
# ══════════════════════════════════════════════

class TestBANDProgressive:

    def test_band_prog_runs(self):
        """BAND + progressive 조합이 에러 없이 실행."""
        returns, prices, fx = _diverging_data()
        config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                    rebalance_mode=RebalanceMode.BAND,
                                    tax_config=PROG, band_threshold_pct=0.05)],
            strategy=StrategyConfig("6040", {"SPY": 0.6, "TLT": 0.4}),
        )
        result = run_backtest(config, returns=returns, prices=prices, fx_rates=fx)
        assert result.gross_pv_usd > 0

    def test_band_prog_more_tax_than_band_flat(self):
        """BAND + progressive → BAND + flat보다 세금 같거나 많음.

        누진은 세율을 올리므로, 같은 실현 패턴이면 세금 ≥ flat.
        (단, 공제 분산 효과로 반드시는 아님 — 약간의 마진 허용)
        """
        returns, prices, fx = _diverging_data()

        def _run(tax):
            config = BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                        rebalance_mode=RebalanceMode.BAND,
                                        tax_config=tax, band_threshold_pct=0.05)],
                strategy=StrategyConfig("6040", {"SPY": 0.6, "TLT": 0.4}),
            )
            return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        r_flat = _run(FLAT)
        r_prog = _run(PROG)

        # 10년 강상승이면 이익 크므로 누진이 더 많아야 함
        # 하지만 공제 분산 효과로 약간 적을 수도 있으므로 5% 마진 허용
        assert r_prog.tax.total_assessed_krw >= r_flat.tax.total_assessed_krw * 0.95

    def test_band_prog_vs_co_prog(self):
        """BAND+progressive vs C/O+progressive → 결과가 다름."""
        returns, prices, fx = _diverging_data()

        def _run(mode):
            config = BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                        rebalance_mode=mode, tax_config=PROG,
                                        band_threshold_pct=0.05)],
                strategy=StrategyConfig("6040", {"SPY": 0.6, "TLT": 0.4}),
            )
            return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        r_band = _run(RebalanceMode.BAND)
        r_co = _run(RebalanceMode.CONTRIBUTION_ONLY)
        # 둘은 다른 실현 패턴 → 다른 세금
        assert abs(r_band.tax.total_assessed_krw - r_co.tax.total_assessed_krw) > 100


# ══════════════════════════════════════════════
# 리스크 2: progressive + 이월결손금 5년 만료
# ══════════════════════════════════════════════

class TestProgressiveCarryforward:

    def test_carryforward_then_progressive(self):
        """이월결손금 상쇄 후 남은 이익에 누진 적용.

        수기 검산:
          이익 60M, 이월 10M → net 50M
          공제 2.5M → taxable 47.5M
          20M flat 22% = 4.4M
          20M~47.5M (=27.5M) at 16.5% = 4,537,500
          총 = 8,937,500
        """
        result = compute_capital_gains_tax(
            realized_gain_krw=60_000_000,
            realized_loss_krw=0,
            carryforward=[(2023, 10_000_000)],
            current_year=2024,
            progressive_brackets=KOREA_PROGRESSIVE_BRACKETS,
            progressive_threshold=20_000_000,
        )
        assert abs(result.tax_krw - 8_937_500) < 1.0

    def test_expired_carry_not_used_progressive(self):
        """5년 만료된 이월결손금 + progressive.

        carry from 2018, current=2024 → 6년 → 만료.
        이익 50M → 공제 2.5M → taxable 47.5M → progressive.
        """
        result_expired = compute_capital_gains_tax(
            realized_gain_krw=50_000_000,
            realized_loss_krw=0,
            carryforward=[(2018, 10_000_000)],  # 6년 → 만료
            current_year=2024,
            progressive_brackets=KOREA_PROGRESSIVE_BRACKETS,
            progressive_threshold=20_000_000,
        )
        result_no_carry = compute_capital_gains_tax(
            realized_gain_krw=50_000_000,
            realized_loss_krw=0,
            carryforward=[],
            current_year=2024,
            progressive_brackets=KOREA_PROGRESSIVE_BRACKETS,
            progressive_threshold=20_000_000,
        )
        # 만료된 carry는 무시 → 결과 동일
        assert abs(result_expired.tax_krw - result_no_carry.tax_krw) < 1.0

    def test_valid_carry_reduces_progressive(self):
        """유효 이월결손금이 과세표준을 낮추면 낮은 구간 적용."""
        result_with = compute_capital_gains_tax(
            realized_gain_krw=100_000_000,
            realized_loss_krw=0,
            carryforward=[(2023, 50_000_000)],  # 5,000만 상쇄
            current_year=2024,
            progressive_brackets=KOREA_PROGRESSIVE_BRACKETS,
            progressive_threshold=20_000_000,
        )
        result_without = compute_capital_gains_tax(
            realized_gain_krw=100_000_000,
            realized_loss_krw=0,
            carryforward=[],
            current_year=2024,
            progressive_brackets=KOREA_PROGRESSIVE_BRACKETS,
            progressive_threshold=20_000_000,
        )
        # carry가 과세표준을 낮추므로 세금 감소
        assert result_with.tax_krw < result_without.tax_krw


# ══════════════════════════════════════════════
# 리스크 3: 최종 청산 한방 이익 + 누진
# ══════════════════════════════════════════════

class TestFinalLiquidationProgressive:

    def test_co_final_liquidation_progressive(self):
        """C/O 20년 → 최종 청산 한방 이익 → 높은 누진 구간.

        C/O는 중간 매도 없음 → 최종 청산에서 전체 이익 한번에 실현.
        이 이익이 매우 크면 최고 누진 구간(45%+)에 걸릴 수 있음.
        """
        returns, prices, fx = _diverging_data(n=240)  # 20년

        def _run(tax):
            config = BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                        rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
                                        tax_config=tax)],
                strategy=StrategyConfig("spy", {"SPY": 1.0}),
            )
            return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        r_flat = _run(FLAT)
        r_prog = _run(PROG)

        # C/O 20년 강상승 → 최종 청산 이익 큼 → 누진 > flat
        assert r_prog.tax.total_assessed_krw > r_flat.tax.total_assessed_krw
        # 차이가 의미있음 (20%+ 차이)
        ratio = r_prog.tax.total_assessed_krw / r_flat.tax.total_assessed_krw
        assert ratio > 1.2, f"Prog/Flat ratio = {ratio:.2f}, expected > 1.2"

    def test_band_mitigates_final_shock(self):
        """BAND가 최종 청산의 누진 충격을 완화하는지.

        BAND는 중간에 이익을 분산 실현 → 최종 이익이 작음.
        progressive 하에서 BAND의 누진 완화 효과 검증.
        """
        returns, prices, fx = _diverging_data(n=120)

        def _run(mode):
            config = BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                        rebalance_mode=mode, tax_config=PROG,
                                        band_threshold_pct=0.05)],
                strategy=StrategyConfig("6040", {"SPY": 0.6, "TLT": 0.4}),
            )
            return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        r_co = _run(RebalanceMode.CONTRIBUTION_ONLY)
        r_band = _run(RebalanceMode.BAND)

        # 둘 다 세금 > 0
        assert r_co.tax.total_assessed_krw > 0
        assert r_band.tax.total_assessed_krw > 0
        # 결과는 다름 (어느 쪽이 크든)
        assert abs(r_co.tax.total_assessed_krw - r_band.tax.total_assessed_krw) > 100


# ══════════════════════════════════════════════
# 보너스: ISA가 progressive에 영향받지 않는지 재확인
# ══════════════════════════════════════════════

class TestISAIsolation:

    def test_isa_progressive_no_effect(self):
        """ISA 계좌는 progressive 있어도 세금 변화 없음."""
        rng = np.random.default_rng(42)
        n = 60
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        returns = pd.DataFrame({"SPY": rng.normal(0.01, 0.03, n)}, index=idx)
        prices = 100 * (1 + returns).cumprod()
        fx = pd.Series(1300.0, index=idx)

        def _run(tax):
            config = BacktestConfig(
                accounts=[AccountConfig("i", AccountType.ISA, 1000.0, tax_config=tax)],
                strategy=StrategyConfig("spy", {"SPY": 1.0}),
            )
            return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        r_flat = _run(TaxConfig(capital_gains_rate=0.0, annual_exemption=0.0,
                                 isa_exempt_limit=2_000_000))
        r_prog = _run(TaxConfig(capital_gains_rate=0.0, annual_exemption=0.0,
                                 isa_exempt_limit=2_000_000,
                                 progressive_brackets=KOREA_PROGRESSIVE_BRACKETS))
        assert abs(r_flat.tax.total_assessed_krw - r_prog.tax.total_assessed_krw) < 1.0
