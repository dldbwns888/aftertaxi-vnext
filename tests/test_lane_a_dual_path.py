# -*- coding: utf-8 -*-
"""
test_lane_a_dual_path.py — adjusted vs explicit dividend 이중 계산 방지
=======================================================================
배당 엔진의 가장 위험한 버그: 가격에 이미 배당이 포함된 상태에서
배당 이벤트를 또 넣으면 배당이 2번 반영된다.

이 테스트는 두 경로가 명확히 분리되어 있는지 검증한다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    RebalanceMode, StrategyConfig,
)
from aftertaxi.core.dividend import DividendSchedule
from aftertaxi.core.facade import run_backtest
from aftertaxi.lanes.lane_a.data_contract import (
    PriceMode, LaneAData, build_dividend_schedule_from_history,
)


# ══════════════════════════════════════════════
# 합성 데이터 생성 (통제된 환경)
# ══════════════════════════════════════════════

def _make_adjusted_data(n=24, div_yield=0.02, price_return=0.01):
    """배당이 가격에 반영된 데이터.
    총 수익률 = 가격 상승 + 배당 재투자.
    """
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    total_return = price_return + div_yield / 12
    prices_adj = [100.0]
    for _ in range(1, n):
        prices_adj.append(prices_adj[-1] * (1 + total_return))
    prices = pd.DataFrame({"SPY": prices_adj}, index=idx)
    fx = pd.Series(1300.0, index=idx)
    returns = prices.pct_change().fillna(0.0)
    return returns, prices, fx


def _make_unadjusted_data(n=24, div_yield=0.02, price_return=0.01):
    """배당이 가격에 미반영된 데이터.
    가격은 순수 가격 변동만. 배당은 별도 schedule로.
    """
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    # 가격: 순수 가격 변동만 (배당 제외)
    prices_unadj = [100.0]
    for _ in range(1, n):
        prices_unadj.append(prices_unadj[-1] * (1 + price_return))
    prices = pd.DataFrame({"SPY": prices_unadj}, index=idx)
    fx = pd.Series(1300.0, index=idx)
    returns = prices.pct_change().fillna(0.0)

    # 배당: 별도 schedule
    div_schedule = DividendSchedule(
        annual_yields={"SPY": div_yield},
        frequency=4,
        withholding_rate=0.15,
        reinvest=True,
    )

    return returns, prices, fx, div_schedule


# ══════════════════════════════════════════════
# 이중 계산 방지 테스트
# ══════════════════════════════════════════════

class TestNoDoubleCounting:

    def test_adjusted_without_dividend_schedule(self):
        """ADJUSTED 경로: dividend_schedule 없이 실행 → 정상."""
        returns, prices, fx = _make_adjusted_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("adj", {"SPY": 1.0}),
                # dividend_schedule 없음 → 배당이 가격에만 반영
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.gross_pv_usd > result.invested_usd  # 수익 양수

    def test_adjusted_with_dividend_would_double_count(self):
        """ADJUSTED 가격 + explicit dividend → 이중 계산으로 PV 과대.
        이건 '해서는 안 되는 조합'의 증거."""
        returns, prices, fx = _make_adjusted_data()
        _, _, _, div_schedule = _make_unadjusted_data()

        r_adj_only = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("adj", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        r_double = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("adj+div", {"SPY": 1.0}),
                dividend_schedule=div_schedule,  # 위험! 이중 계산!
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # 이중 계산이므로 PV가 더 높음 (이건 버그를 보여주는 테스트)
        assert r_double.gross_pv_usd > r_adj_only.gross_pv_usd

    def test_unadjusted_with_dividend_correct(self):
        """UNADJUSTED 가격 + explicit dividend → 올바른 조합."""
        returns, prices, fx, div_schedule = _make_unadjusted_data()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("unadj+div", {"SPY": 1.0}),
                dividend_schedule=div_schedule,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        assert result.gross_pv_usd > result.invested_usd

    def test_unadjusted_without_dividend_lower(self):
        """UNADJUSTED 가격만 (배당 없음) → UNADJUSTED+배당보다 PV 낮음."""
        returns, prices, fx, div_schedule = _make_unadjusted_data()

        r_no_div = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("unadj", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        r_with_div = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("unadj+div", {"SPY": 1.0}),
                dividend_schedule=div_schedule,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # 배당 재투자 효과로 PV 차이
        assert r_with_div.gross_pv_usd > r_no_div.gross_pv_usd

    def test_adjusted_vs_unadjusted_plus_div_similar(self):
        """ADJUSTED와 UNADJUSTED+dividend의 총 수익이 유사.
        (완전 동일하지는 않음 — 원천징수/재투자 타이밍 차이)"""
        returns_adj, prices_adj, fx = _make_adjusted_data(36)
        returns_unadj, prices_unadj, fx2, div_sched = _make_unadjusted_data(36)

        r_adj = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("adj", {"SPY": 1.0}),
            ),
            returns=returns_adj, prices=prices_adj, fx_rates=fx,
        )

        r_unadj = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("unadj+div", {"SPY": 1.0}),
                dividend_schedule=div_sched,
            ),
            returns=returns_unadj, prices=prices_unadj, fx_rates=fx2,
        )

        # 총 수익이 비슷해야 (원천징수 15% 차이 + 재투자 타이밍 차이 허용)
        ratio = r_unadj.mult_pre_tax / r_adj.mult_pre_tax
        assert 0.85 < ratio < 1.05, f"비율 {ratio:.3f}이 너무 벌어짐"


# ══════════════════════════════════════════════
# LaneAData 계약 테스트
# ══════════════════════════════════════════════

class TestLaneADataContract:

    def test_adjusted_validates_without_schedule(self):
        """ADJUSTED + no schedule → valid."""
        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        data = LaneAData(
            prices=pd.DataFrame({"SPY": [100]*12}, index=idx),
            fx_rates=pd.Series(1300.0, index=idx),
            returns=pd.DataFrame({"SPY": [0.0]*12}, index=idx),
            price_mode=PriceMode.ADJUSTED,
            start_date=idx[0], end_date=idx[-1], n_months=12,
        )
        data.validate()  # 에러 없어야

    def test_adjusted_with_schedule_raises(self):
        """ADJUSTED + dividend_schedule → 이중 계산 경고."""
        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        data = LaneAData(
            prices=pd.DataFrame({"SPY": [100]*12}, index=idx),
            fx_rates=pd.Series(1300.0, index=idx),
            returns=pd.DataFrame({"SPY": [0.0]*12}, index=idx),
            price_mode=PriceMode.ADJUSTED,
            start_date=idx[0], end_date=idx[-1], n_months=12,
            dividend_schedule=DividendSchedule({"SPY": 0.02}),
        )
        with pytest.raises(ValueError, match="이중 계산"):
            data.validate()

    def test_explicit_without_schedule_raises(self):
        """EXPLICIT_DIVIDENDS + no schedule → 에러."""
        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        data = LaneAData(
            prices=pd.DataFrame({"SPY": [100]*12}, index=idx),
            fx_rates=pd.Series(1300.0, index=idx),
            returns=pd.DataFrame({"SPY": [0.0]*12}, index=idx),
            price_mode=PriceMode.EXPLICIT_DIVIDENDS,
            start_date=idx[0], end_date=idx[-1], n_months=12,
        )
        with pytest.raises(ValueError, match="dividend_schedule이 필요"):
            data.validate()

    def test_explicit_with_schedule_valid(self):
        """EXPLICIT_DIVIDENDS + schedule → valid."""
        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        data = LaneAData(
            prices=pd.DataFrame({"SPY": [100]*12}, index=idx),
            fx_rates=pd.Series(1300.0, index=idx),
            returns=pd.DataFrame({"SPY": [0.0]*12}, index=idx),
            price_mode=PriceMode.EXPLICIT_DIVIDENDS,
            start_date=idx[0], end_date=idx[-1], n_months=12,
            dividend_schedule=DividendSchedule({"SPY": 0.02}),
        )
        data.validate()  # 에러 없어야


# ══════════════════════════════════════════════
# build_dividend_schedule_from_history
# ══════════════════════════════════════════════

class TestBuildDividendSchedule:

    def test_builds_from_history(self):
        """배당 이력에서 schedule 생성."""
        idx = pd.date_range("2020-01-15", periods=8, freq="QE")  # 분기별
        divs = pd.DataFrame({"SPY": [1.0]*8}, index=idx)
        prices = pd.DataFrame(
            {"SPY": [400]*24},
            index=pd.date_range("2020-01-31", periods=24, freq="ME"),
        )

        sched = build_dividend_schedule_from_history(divs, prices)
        assert "SPY" in sched.annual_yields
        assert sched.annual_yields["SPY"] > 0
        assert sched.frequency == 4

    def test_zero_dividend(self):
        """배당 0이면 yield 0."""
        idx = pd.date_range("2020-01-31", periods=4, freq="QE")
        divs = pd.DataFrame({"SPY": [0.0]*4}, index=idx)
        prices = pd.DataFrame(
            {"SPY": [400]*12},
            index=pd.date_range("2020-01-31", periods=12, freq="ME"),
        )

        sched = build_dividend_schedule_from_history(divs, prices)
        assert sched.annual_yields["SPY"] == 0.0
