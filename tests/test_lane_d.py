# -*- coding: utf-8 -*-
"""
test_lane_d.py — Lane D haircut model 테스트
=============================================
코어 무관 검증. EngineResult를 읽기만 한다.
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.lanes.lane_d.haircut import (
    apply_haircut, ExecutionHaircutConfig, ExecutionHaircutResult,
)


@pytest.fixture(scope="module")
def sample_result():
    """60개월 SPY B&H 합성 데이터 결과."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-31", periods=60, freq="ME")
    r = rng.normal(0.008, 0.04, 60)
    returns = pd.DataFrame({"SPY": r}, index=idx)
    prices = pd.DataFrame({"SPY": 100 * np.cumprod(1 + r)}, index=idx)
    fx = pd.Series(1300.0, index=idx)

    return run_backtest(
        BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("SPY_BnH", {"SPY": 1.0}),
        ),
        returns=returns, prices=prices, fx_rates=fx,
    )


class TestZeroHaircut:

    def test_zero_config_no_change(self, sample_result):
        """모든 파라미터 0 → haircut 없음."""
        config = ExecutionHaircutConfig(
            slippage_bps=0, fx_spread_krw=0,
            rebalance_delay_days=0, dividend_reinvest_delay_days=0,
            tax_cash_drag_months=0,
        )
        hr = apply_haircut(sample_result, config)
        assert abs(hr.haircut_factor - 1.0) < 1e-10
        assert abs(hr.haircut_mult_after_tax - hr.base_mult_after_tax) < 1e-10
        assert hr.total_annual_drag_pct == 0.0


class TestMonotonicity:

    def test_slippage_reduces(self, sample_result):
        """슬리피지 → 결과 감소."""
        hr0 = apply_haircut(sample_result, ExecutionHaircutConfig(
            slippage_bps=0, fx_spread_krw=0, rebalance_delay_days=0,
            dividend_reinvest_delay_days=0, tax_cash_drag_months=0,
        ))
        hr5 = apply_haircut(sample_result, ExecutionHaircutConfig(
            slippage_bps=10, annual_turnover=0.30,
            fx_spread_krw=0, rebalance_delay_days=0,
            dividend_reinvest_delay_days=0, tax_cash_drag_months=0,
        ))
        assert hr5.haircut_mult_after_tax < hr0.haircut_mult_after_tax

    def test_fx_spread_reduces(self, sample_result):
        """FX 스프레드 → 결과 감소."""
        hr0 = apply_haircut(sample_result, ExecutionHaircutConfig(
            slippage_bps=0, fx_spread_krw=0, rebalance_delay_days=0,
            dividend_reinvest_delay_days=0, tax_cash_drag_months=0,
        ))
        hr30 = apply_haircut(sample_result, ExecutionHaircutConfig(
            slippage_bps=0, fx_spread_krw=30,
            rebalance_delay_days=0, dividend_reinvest_delay_days=0,
            tax_cash_drag_months=0,
        ))
        assert hr30.haircut_mult_after_tax < hr0.haircut_mult_after_tax

    def test_more_drag_worse(self, sample_result):
        """모든 drag 켜면 원본보다 낮음."""
        hr = apply_haircut(sample_result, ExecutionHaircutConfig(
            slippage_bps=10, annual_turnover=0.30,
            fx_spread_krw=30, rebalance_delay_days=3,
            dividend_reinvest_delay_days=10, tax_cash_drag_months=5,
        ))
        assert hr.haircut_mult_after_tax < hr.base_mult_after_tax
        assert hr.haircut_factor < 1.0


class TestEdgeCases:

    def test_zero_pv(self):
        """PV=0인 결과도 안전."""
        from tests.helpers import make_engine_result
        r = make_engine_result(gross_pv_usd=0, invested_usd=0)
        hr = apply_haircut(r)
        assert hr.haircut_factor >= 0

    def test_short_period(self, sample_result):
        """짧은 기간에도 동작."""
        idx = pd.date_range("2024-01-31", periods=3, freq="ME")
        returns = pd.DataFrame({"SPY": [0.01, -0.02, 0.03]}, index=idx)
        prices = pd.DataFrame({"SPY": [101, 99, 102]}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        r = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        hr = apply_haircut(r)
        assert hr.n_years == 0.25
        assert hr.haircut_factor > 0


class TestResultStructure:

    def test_typed_result(self, sample_result):
        hr = apply_haircut(sample_result)
        assert isinstance(hr, ExecutionHaircutResult)
        assert hasattr(hr, "slippage_drag_pct")
        assert hasattr(hr, "fx_drag_pct")
        assert hasattr(hr, "delay_drag_pct")
        assert hasattr(hr, "dividend_delay_drag_pct")
        assert hasattr(hr, "tax_cash_drag_pct")

    def test_drags_non_negative(self, sample_result):
        hr = apply_haircut(sample_result)
        assert hr.slippage_drag_pct >= 0
        assert hr.fx_drag_pct >= 0
        assert hr.delay_drag_pct >= 0
        assert hr.dividend_delay_drag_pct >= 0
        assert hr.tax_cash_drag_pct >= 0

    def test_summary_text(self, sample_result):
        hr = apply_haircut(sample_result)
        text = hr.summary_text()
        assert "Lane D" in text
        assert "Haircut" in text
        assert "슬리피지" in text
        assert "총 연율 drag" in text

    def test_decomposition_sums(self, sample_result):
        """항목별 drag 합 = total."""
        hr = apply_haircut(sample_result)
        components = (hr.slippage_drag_pct + hr.fx_drag_pct + hr.delay_drag_pct +
                      hr.dividend_delay_drag_pct + hr.tax_cash_drag_pct)
        assert abs(components - hr.total_annual_drag_pct) < 1e-10


class TestDefaultParams:

    def test_default_config_reasonable(self, sample_result):
        """기본 파라미터로 연 0.1~2% drag 범위."""
        hr = apply_haircut(sample_result)
        assert 0.05 < hr.total_annual_drag_pct < 3.0

    def test_default_haircut_not_extreme(self, sample_result):
        """기본 haircut이 5~20년에서 배수를 50% 이상 깎지 않음."""
        hr = apply_haircut(sample_result)
        assert hr.haircut_factor > 0.5
