# -*- coding: utf-8 -*-
"""
test_signal_runner.py — signal_runner equivalence + 동적 비중 테스트
===================================================================
1. 고정 비중 → core runner와 숫자 동일 (equivalence)
2. 동적 비중 → 전환 시 세금 발생, 구조 검증
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.lab.strategy_builder.signal_runner import (
    run_signal_backtest,
    make_constant_schedule,
    make_switching_schedule,
)


# ══════════════════════════════════════════════
# 데이터 fixture
# ══════════════════════════════════════════════

@pytest.fixture(scope="module")
def market_60m():
    """60개월 합성 데이터 (seed=42)."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-31", periods=60, freq="ME")
    ret = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, 60)}, index=idx)
    prices = 100 * (1 + ret).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return ret, prices, fx


@pytest.fixture(scope="module")
def market_2asset():
    """60개월 2자산 합성 데이터."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-31", periods=60, freq="ME")
    spy = rng.normal(0.01, 0.04, 60)
    sgov = rng.normal(0.003, 0.002, 60)
    ret = pd.DataFrame({"SPY": spy, "SGOV": sgov}, index=idx)
    prices = 100 * (1 + ret).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return ret, prices, fx


# ══════════════════════════════════════════════
# Equivalence: 고정 비중이면 core와 동일
# ══════════════════════════════════════════════

class TestEquivalence:
    """signal_runner + 고정 비중 = core runner. 숫자 동일."""

    def test_spy_bnh_co(self, market_60m):
        """SPY 100% C/O: 코어와 동일."""
        ret, prices, fx = market_60m
        config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("spy", {"SPY": 1.0}),
        )
        schedule = make_constant_schedule({"SPY": 1.0}, 60)

        core = run_backtest(config, returns=ret, prices=prices, fx_rates=fx)
        sig = run_signal_backtest(config, prices, fx, weight_schedule=schedule)

        assert abs(core.gross_pv_usd - sig.gross_pv_usd) < 1e-6, \
            f"PV: {core.gross_pv_usd} vs {sig.gross_pv_usd}"
        assert abs(core.invested_usd - sig.invested_usd) < 1e-6
        assert abs(core.tax.total_assessed_krw - sig.tax.total_assessed_krw) < 1e-6
        assert abs(core.net_pv_krw - sig.net_pv_krw) < 1e-6
        assert core.n_months == sig.n_months

    def test_spy_full_rebal(self, market_2asset):
        """2자산 FULL rebalance: 코어와 동일."""
        ret, prices, fx = market_2asset
        config = BacktestConfig(
            accounts=[AccountConfig(
                "t", AccountType.TAXABLE, 1000.0,
                rebalance_mode=RebalanceMode.FULL,
            )],
            strategy=StrategyConfig("6040", {"SPY": 0.6, "SGOV": 0.4}),
        )
        schedule = make_constant_schedule({"SPY": 0.6, "SGOV": 0.4}, 60)

        core = run_backtest(config, returns=ret, prices=prices, fx_rates=fx)
        sig = run_signal_backtest(config, prices, fx, weight_schedule=schedule)

        assert abs(core.gross_pv_usd - sig.gross_pv_usd) < 1e-6
        assert abs(core.tax.total_assessed_krw - sig.tax.total_assessed_krw) < 1e-6
        assert abs(core.net_pv_krw - sig.net_pv_krw) < 1e-6

    def test_golden_baseline_match(self, market_60m):
        """golden baseline과 동일한 결과."""
        ret, prices, fx = market_60m
        config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("spy", {"SPY": 1.0}),
        )
        schedule = make_constant_schedule({"SPY": 1.0}, 60)

        sig = run_signal_backtest(config, prices, fx, weight_schedule=schedule)

        # golden baseline (test_golden_baseline.py 참조)
        GOLDEN_PV = 80818.08926
        GOLDEN_TAX = 6928171.19111
        GOLDEN_NET = 105063516.04120

        assert abs(sig.gross_pv_usd - GOLDEN_PV) < 0.01
        assert abs(sig.tax.total_assessed_krw - GOLDEN_TAX) < 0.01
        assert abs(sig.net_pv_krw - GOLDEN_NET) < 0.01


# ══════════════════════════════════════════════
# 동적 비중: 전환 시 세금 발생
# ══════════════════════════════════════════════

class TestDynamicWeights:
    """동적 비중이 세후 결과에 미치는 영향."""

    def test_switching_generates_tax(self, market_2asset):
        """성장→쉘터 전환 시 매도 발생 → 세금."""
        ret, prices, fx = market_2asset

        # 30개월 성장 + 30개월 쉘터
        signals = [True] * 30 + [False] * 30
        schedule = make_switching_schedule(
            growth_weights={"SPY": 1.0},
            shelter_weights={"SGOV": 1.0},
            signals=signals,
        )

        config = BacktestConfig(
            accounts=[AccountConfig(
                "t", AccountType.TAXABLE, 1000.0,
                rebalance_mode=RebalanceMode.FULL,  # 전환 시 FULL 필요
            )],
            strategy=StrategyConfig("switch", {"SPY": 1.0}),
        )

        result = run_signal_backtest(config, prices, fx, weight_schedule=schedule)

        assert result.n_months == 60
        assert result.gross_pv_usd > 0
        # 30개월 성장 후 전환 → 양도세 발생해야 함
        assert result.tax.total_assessed_krw > 0

    def test_switching_has_intermediate_tax(self, market_2asset):
        """전환 전략은 중간에 세금이 발생한다 (B&H는 최종 청산에서만).

        NOTE: 총 세금은 반드시 전환 > B&H가 아니다.
        250만 공제 분산 효과로 전환이 오히려 세금이 적을 수 있다.
        이것이 DCA 세후 분석의 핵심 논제.
        """
        ret, prices, fx = market_2asset

        # 매 12개월마다 SPY↔SGOV 전환
        signals = [(i // 12) % 2 == 0 for i in range(60)]
        schedule = make_switching_schedule(
            growth_weights={"SPY": 1.0},
            shelter_weights={"SGOV": 1.0},
            signals=signals,
        )
        config_sw = BacktestConfig(
            accounts=[AccountConfig(
                "t", AccountType.TAXABLE, 1000.0,
                rebalance_mode=RebalanceMode.FULL,
            )],
            strategy=StrategyConfig("switch", {"SPY": 1.0}),
        )
        r_sw = run_signal_backtest(config_sw, prices, fx, weight_schedule=schedule)

        # 전환 전략은 중간 연도에 세금이 발생해야 함
        mid_year_taxes = [
            h for h in r_sw.annual_tax_history
            if h["year"] < prices.index[-1].year and h["cgt_krw"] > 0
        ]
        assert len(mid_year_taxes) > 0, "전환 전략인데 중간 세금이 없음"

    def test_constant_schedule_equals_bnh(self, market_60m):
        """고정 스케줄 = B&H와 동일 (make_constant_schedule 검증)."""
        ret, prices, fx = market_60m
        config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("spy", {"SPY": 1.0}),
        )
        schedule = make_constant_schedule({"SPY": 1.0}, 60)

        r_core = run_backtest(config, returns=ret, prices=prices, fx_rates=fx)
        r_sig = run_signal_backtest(config, prices, fx, weight_schedule=schedule)

        assert abs(r_core.gross_pv_usd - r_sig.gross_pv_usd) < 1e-6

    def test_schedule_shorter_than_months(self, market_60m):
        """스케줄이 짧으면 마지막 비중 반복."""
        ret, prices, fx = market_60m
        config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("spy", {"SPY": 1.0}),
        )
        # 30개월 스케줄 → 나머지 30개월은 마지막 비중 유지
        schedule = make_constant_schedule({"SPY": 1.0}, 30)

        result = run_signal_backtest(config, prices, fx, weight_schedule=schedule)
        assert result.n_months == 60  # 전체 기간 실행


# ══════════════════════════════════════════════
# make_switching_schedule 단위 테스트
# ══════════════════════════════════════════════

class TestScheduleUtilities:

    def test_constant_schedule_length(self):
        s = make_constant_schedule({"A": 0.5, "B": 0.5}, 10)
        assert len(s) == 10
        assert all(w == {"A": 0.5, "B": 0.5} for w in s)

    def test_switching_schedule_length(self):
        signals = [True, False, True]
        s = make_switching_schedule({"SPY": 1.0}, {"SGOV": 1.0}, signals)
        assert len(s) == 3
        assert s[0] == {"SPY": 1.0}
        assert s[1] == {"SGOV": 1.0}
        assert s[2] == {"SPY": 1.0}

    def test_switching_all_true(self):
        s = make_switching_schedule({"SPY": 1.0}, {"SGOV": 1.0}, [True] * 5)
        assert all(w == {"SPY": 1.0} for w in s)

    def test_switching_all_false(self):
        s = make_switching_schedule({"SPY": 1.0}, {"SGOV": 1.0}, [False] * 5)
        assert all(w == {"SGOV": 1.0} for w in s)
