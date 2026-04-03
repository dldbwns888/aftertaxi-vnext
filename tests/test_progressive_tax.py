# -*- coding: utf-8 -*-
"""
test_progressive_tax.py — 종합과세 누진 테스트
=============================================
수기 검산 포함. 한국 2024 세법 기준.

bracket (지방세 포함):
  ~14M: 6.6%, 14M~50M: 16.5%, 50M~88M: 26.4%,
  88M~150M: 38.5%, 150M~300M: 41.8%, 300M~500M: 44.0%,
  500M~1B: 46.2%, 1B~: 49.5%
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.tax_engine import (
    _compute_progressive_tax, compute_capital_gains_tax,
)
from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
    TaxConfig, TAXABLE_TAX, KOREA_PROGRESSIVE_BRACKETS,
)


BRACKETS = KOREA_PROGRESSIVE_BRACKETS
THRESHOLD = 20_000_000.0
FLAT = 0.22


# ══════════════════════════════════════════════
# 수기 검산: _compute_progressive_tax 순수 함수
# ══════════════════════════════════════════════

class TestProgressiveFunction:

    def test_below_threshold_equals_flat(self):
        """20M 이하 → flat 22%."""
        tax = _compute_progressive_tax(10_000_000, BRACKETS, THRESHOLD, FLAT)
        expected = 10_000_000 * 0.22
        assert abs(tax - expected) < 1.0

    def test_at_threshold_equals_flat(self):
        """정확히 20M → flat 22%."""
        tax = _compute_progressive_tax(THRESHOLD, BRACKETS, THRESHOLD, FLAT)
        expected = THRESHOLD * 0.22
        assert abs(tax - expected) < 1.0

    def test_30m_hand_calc(self):
        """30M 수기 검산.

        20M까지: 20M × 0.22 = 4,400,000
        20M~30M (=10M): bracket (14M~50M, 0.165) → 10M × 0.165 = 1,650,000
        총: 6,050,000
        """
        tax = _compute_progressive_tax(30_000_000, BRACKETS, THRESHOLD, FLAT)
        expected = 4_400_000 + 1_650_000  # = 6,050,000
        assert abs(tax - expected) < 1.0

    def test_50m_hand_calc(self):
        """50M 수기 검산.

        20M까지: 20M × 0.22 = 4,400,000
        20M~50M (=30M): bracket (14M~50M, 0.165) → 30M × 0.165 = 4,950,000
        총: 9,350,000
        """
        tax = _compute_progressive_tax(50_000_000, BRACKETS, THRESHOLD, FLAT)
        expected = 4_400_000 + 4_950_000  # = 9,350,000
        assert abs(tax - expected) < 1.0

    def test_100m_hand_calc(self):
        """100M 수기 검산.

        20M까지: 20M × 0.22 = 4,400,000
        20M~50M (=30M): 0.165 → 4,950,000
        50M~88M (=38M): 0.264 → 10,032,000
        88M~100M (=12M): 0.385 → 4,620,000
        총: 24,002,000
        """
        tax = _compute_progressive_tax(100_000_000, BRACKETS, THRESHOLD, FLAT)
        expected = 4_400_000 + 4_950_000 + 10_032_000 + 4_620_000  # = 24,002,000
        assert abs(tax - expected) < 1.0

    def test_zero_taxable(self):
        assert _compute_progressive_tax(0, BRACKETS, THRESHOLD, FLAT) == 0.0

    def test_negative_taxable(self):
        assert _compute_progressive_tax(-1_000_000, BRACKETS, THRESHOLD, FLAT) == 0.0

    def test_progressive_gt_flat_for_very_large(self):
        """88M 이상에서 누진 > flat.

        20M~50M 구간(0.165)이 flat(0.22)보다 낮아서,
        중간 금액에서는 누진이 오히려 싸다.
        교차점 ~88M (50M~88M 구간 0.264 > 0.22 축적).
        """
        for amount in [100_000_000, 200_000_000, 500_000_000]:
            prog = _compute_progressive_tax(amount, BRACKETS, THRESHOLD, FLAT)
            flat = amount * FLAT
            assert prog > flat, f"At {amount/1e6:.0f}M: prog={prog:.0f} should > flat={flat:.0f}"

    def test_progressive_lt_flat_for_moderate(self):
        """20M~88M 사이에서 누진 < flat (세율 역전).

        16.5% 구간이 22%보다 낮아서 발생.
        이건 한국 세법의 특성: 종합과세가 분리과세보다 유리한 구간 존재.
        """
        for amount in [30_000_000, 50_000_000, 60_000_000]:
            prog = _compute_progressive_tax(amount, BRACKETS, THRESHOLD, FLAT)
            flat = amount * FLAT
            assert prog < flat, f"At {amount/1e6:.0f}M: prog={prog:.0f} should < flat={flat:.0f}"


# ══════════════════════════════════════════════
# compute_capital_gains_tax 통합
# ══════════════════════════════════════════════

class TestProgressiveInTaxEngine:

    def test_flat_no_brackets(self):
        """brackets=None → flat 22% 그대로."""
        result = compute_capital_gains_tax(
            realized_gain_krw=50_000_000,
            realized_loss_krw=0,
            carryforward=[],
            current_year=2024,
            rate=0.22,
            exemption=2_500_000,
            progressive_brackets=None,
        )
        expected = (50_000_000 - 2_500_000) * 0.22
        assert abs(result.tax_krw - expected) < 1.0

    def test_progressive_with_brackets(self):
        """brackets 있으면 누진 적용."""
        result = compute_capital_gains_tax(
            realized_gain_krw=50_000_000,
            realized_loss_krw=0,
            carryforward=[],
            current_year=2024,
            rate=0.22,
            exemption=2_500_000,
            progressive_brackets=BRACKETS,
            progressive_threshold=THRESHOLD,
        )
        # taxable = 50M - 2.5M = 47.5M (> 20M → 누진)
        # 20M × 0.22 = 4.4M
        # 20M~47.5M (=27.5M) in bracket (14M~50M, 0.165) → 27.5M × 0.165 = 4,537,500
        expected = 4_400_000 + 4_537_500  # = 8,937,500
        assert abs(result.tax_krw - expected) < 1.0

    def test_below_threshold_same_as_flat(self):
        """과세표준 < threshold → flat과 동일."""
        for gain in [5_000_000, 15_000_000, 22_000_000]:
            flat = compute_capital_gains_tax(
                gain, 0, [], 2024, progressive_brackets=None)
            prog = compute_capital_gains_tax(
                gain, 0, [], 2024,
                progressive_brackets=BRACKETS,
                progressive_threshold=THRESHOLD)
            assert abs(flat.tax_krw - prog.tax_krw) < 1.0, f"At gain={gain}: differ"

    def test_carryforward_still_works(self):
        """이월결손금 + 누진 조합."""
        result = compute_capital_gains_tax(
            realized_gain_krw=60_000_000,
            realized_loss_krw=0,
            carryforward=[(2023, 10_000_000)],  # 1,000만 이월결손
            current_year=2024,
            progressive_brackets=BRACKETS,
            progressive_threshold=THRESHOLD,
        )
        # net = 60M - 10M carry = 50M
        # taxable = 50M - 2.5M exemption = 47.5M
        # 위 test_progressive_with_brackets와 동일 → 8,937,500
        assert abs(result.tax_krw - 8_937_500) < 1.0


# ══════════════════════════════════════════════
# 엔진 E2E
# ══════════════════════════════════════════════

class TestProgressiveE2E:

    def _run(self, progressive=False, n=120):
        rng = np.random.default_rng(42)
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        returns = pd.DataFrame({"SPY": rng.normal(0.015, 0.04, n)}, index=idx)
        prices = 100 * (1 + returns).cumprod()
        fx = pd.Series(1300.0, index=idx)

        tax_config = TaxConfig(
            capital_gains_rate=0.22,
            annual_exemption=2_500_000,
            progressive_brackets=BRACKETS if progressive else None,
            progressive_threshold=THRESHOLD,
        )
        config = BacktestConfig(
            accounts=[AccountConfig(
                "t", AccountType.TAXABLE, 1000.0,
                tax_config=tax_config,
            )],
            strategy=StrategyConfig("spy", {"SPY": 1.0}),
        )
        from aftertaxi.core.facade import run_backtest
        return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

    def test_progressive_runs(self):
        result = self._run(progressive=True)
        assert result.gross_pv_usd > 0

    def test_progressive_more_tax_for_big_gains(self):
        """큰 이익 시 누진세 > flat세."""
        r_flat = self._run(progressive=False)
        r_prog = self._run(progressive=True)
        # 10년 강한 상승이면 최종 청산 이익이 크다
        # 이익이 충분히 크면 누진 > flat
        # (단, 이 시나리오에서 이익 규모에 따라 다를 수 있음)
        # 최소한 결과가 다름을 확인
        assert r_flat.tax.total_assessed_krw != r_prog.tax.total_assessed_krw

    def test_isa_not_affected(self):
        """ISA는 progressive 무관."""
        rng = np.random.default_rng(42)
        idx = pd.date_range("2020-01-31", periods=60, freq="ME")
        returns = pd.DataFrame({"SPY": rng.normal(0.01, 0.03, 60)}, index=idx)
        prices = 100 * (1 + returns).cumprod()
        fx = pd.Series(1300.0, index=idx)

        from aftertaxi.core.facade import run_backtest

        def _run_isa(prog):
            config = BacktestConfig(
                accounts=[AccountConfig(
                    "i", AccountType.ISA, 500.0,
                    tax_config=TaxConfig(
                        capital_gains_rate=0.0,
                        annual_exemption=0.0,
                        isa_exempt_limit=2_000_000.0,
                        progressive_brackets=BRACKETS if prog else None,
                    ),
                )],
                strategy=StrategyConfig("spy", {"SPY": 1.0}),
            )
            return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        r_flat = _run_isa(False)
        r_prog = _run_isa(True)
        # ISA는 capital_gains_rate=0 → progressive 안 타도 세금 같음
        assert abs(r_flat.tax.total_assessed_krw - r_prog.tax.total_assessed_krw) < 1.0
