# -*- coding: utf-8 -*-
"""
test_workbench_adapter.py — 엔진 → 워크벤치 직렬화 테스트
==========================================================
실제 facade 실행 결과를 workbench payload로 변환하고
shape/값 일관성을 검증.
"""

import json
import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    RebalanceMode, StrategyConfig,
)
from aftertaxi.core.dividend import DividendSchedule
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.attribution import build_attribution
from aftertaxi.core.workbench_adapter import to_workbench_payload, to_workbench_json


def _make_data(n=36):
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    spy = [100 * (1.01 ** i) for i in range(n)]
    qqq = [100 * (1.015 ** i) for i in range(n)]
    prices = pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)
    fx = pd.Series(1300.0, index=idx)
    returns = prices.pct_change().fillna(0.0)
    return returns, prices, fx


class TestToWorkbenchPayload:

    def test_payload_shape(self):
        """payload가 workbench가 기대하는 shape."""
        returns, prices, fx = _make_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        payload = to_workbench_payload(result, "SPY 100%", "베이스라인")

        # top-level keys
        assert "name" in payload
        assert "description" in payload
        assert "result" in payload
        assert "attribution" in payload

        # result keys
        r = payload["result"]
        for key in ["gross_pv_usd", "invested_usd", "net_pv_krw", "gross_pv_krw",
                     "reporting_fx_rate", "mdd", "n_months", "mult_pre_tax", "mult_after_tax"]:
            assert key in r, f"missing result.{key}"

        # attribution keys
        a = payload["attribution"]
        for key in ["total_transaction_cost_usd", "total_tax_assessed_krw",
                     "total_capital_gains_tax_krw", "total_dividend_tax_krw",
                     "total_health_insurance_krw", "total_dividend_gross_usd",
                     "total_dividend_withholding_usd", "total_dividend_net_usd",
                     "cost_drag_pct", "tax_drag_pct", "withholding_drag_pct"]:
            assert key in a, f"missing attribution.{key}"

    def test_values_match_engine(self):
        """payload 값이 EngineResult와 일치."""
        returns, prices, fx = _make_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        payload = to_workbench_payload(result, "test")

        assert abs(payload["result"]["gross_pv_usd"] - result.gross_pv_usd) < 0.01
        assert abs(payload["result"]["net_pv_krw"] - result.net_pv_krw) < 0.01
        assert abs(payload["result"]["mult_pre_tax"] - result.mult_pre_tax) < 1e-6

    def test_json_serializable(self):
        """payload가 JSON 직렬화 가능."""
        returns, prices, fx = _make_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        payload = to_workbench_payload(result, "test")
        json_str = json.dumps(payload)  # 에러 없이 직렬화
        parsed = json.loads(json_str)
        assert parsed["name"] == "test"

    def test_auto_attribution(self):
        """attribution=None이면 자동 계산."""
        returns, prices, fx = _make_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    transaction_cost_bps=50)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        payload = to_workbench_payload(result, "test")
        assert payload["attribution"]["total_transaction_cost_usd"] > 0


class TestMultiStrategyComparison:

    def test_two_strategies_different(self):
        """2개 전략의 payload가 다른 값."""
        returns, prices, fx = _make_data()

        r1 = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("spy100", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        r2 = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("qqq100", {"QQQ": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        p1 = to_workbench_payload(r1, "SPY 100%")
        p2 = to_workbench_payload(r2, "QQQ 100%")

        assert p1["result"]["gross_pv_usd"] != p2["result"]["gross_pv_usd"]

    def test_to_json_multi(self):
        """여러 전략 → JSON 문자열."""
        returns, prices, fx = _make_data()

        payloads = []
        for name, weights in [("SPY", {"SPY": 1.0}), ("QQQ", {"QQQ": 1.0})]:
            result = run_backtest(
                BacktestConfig(
                    accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                    strategy=StrategyConfig(name, weights),
                ),
                returns=returns, prices=prices, fx_rates=fx,
            )
            payloads.append(to_workbench_payload(result, name))

        json_str = to_workbench_json(payloads)
        parsed = json.loads(json_str)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "SPY"
        assert parsed[1]["name"] == "QQQ"

    def test_with_dividends_and_fees(self):
        """배당 + 거래비용 포함 전략도 직렬화."""
        returns, prices, fx = _make_data()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    transaction_cost_bps=50)],
                strategy=StrategyConfig("div+fee", {"SPY": 0.6, "QQQ": 0.4}),
                dividend_schedule=DividendSchedule({"SPY": 0.015, "QQQ": 0.005}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        payload = to_workbench_payload(result, "60/40 + div + fee", "배당+수수료 포함")
        assert payload["attribution"]["total_transaction_cost_usd"] > 0
        assert payload["attribution"]["total_dividend_gross_usd"] > 0

        # JSON으로도 가능
        json_str = json.dumps(payload)
        assert len(json_str) > 100
