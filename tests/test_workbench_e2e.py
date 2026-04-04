# -*- coding: utf-8 -*-
"""
test_workbench_e2e.py — 워크벤치 실연결 테스트
==============================================
compile → engine → workbench payload 전체 파이프라인.
"""

import json
import numpy as np
import pandas as pd
import pytest

from aftertaxi.workbench import run_workbench, run_workbench_json


@pytest.fixture(scope="module")
def market_data():
    idx = pd.date_range("2020-01-31", periods=60, freq="ME")
    spy = [100 * (1.008 ** i) for i in range(60)]
    qqq = [200 * (1.01 ** i) for i in range(60)]
    prices = pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)
    fx = pd.Series(1300.0, index=idx)
    returns = prices.pct_change().fillna(0.0)
    return returns, prices, fx


class TestRunWorkbench:

    def test_single_strategy(self, market_data):
        returns, prices, fx = market_data
        results = run_workbench(
            [{"strategy": {"type": "spy_bnh"}}],
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert len(results) == 1
        assert results[0]["name"] == "SPY_BnH"
        assert results[0]["result"]["gross_pv_usd"] > 0
        assert "attribution" in results[0]
        assert "person" in results[0]

    def test_multi_strategy_comparison(self, market_data):
        returns, prices, fx = market_data
        results = run_workbench(
            [
                {"strategy": {"type": "spy_bnh"}, "description": "벤치마크"},
                {"strategy": {"weights": {"SPY": 0.6, "QQQ": 0.4}}, "description": "6040"},
            ],
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert len(results) == 2
        assert results[0]["name"] == "SPY_BnH"
        assert results[1]["name"] == "custom"
        # 두 전략의 PV가 다름
        assert results[0]["result"]["gross_pv_usd"] != results[1]["result"]["gross_pv_usd"]

    def test_multi_account(self, market_data):
        returns, prices, fx = market_data
        results = run_workbench(
            [{
                "strategy": {"type": "spy_bnh"},
                "accounts": [
                    {"type": "ISA", "monthly_contribution": 500},
                    {"type": "TAXABLE", "monthly_contribution": 500},
                ],
            }],
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert len(results) == 1
        assert results[0]["result"]["n_months"] == 60

    def test_with_validation(self, market_data):
        returns, prices, fx = market_data
        results = run_workbench(
            [{"strategy": {"type": "spy_bnh"}}],
            returns=returns, prices=prices, fx_rates=fx,
            include_validation=True,
        )
        assert "validation" in results[0]
        v = results[0]["validation"]
        assert v["overall_grade"] in ("PASS", "WARN", "FAIL")
        assert v["n_pass"] >= 0
        assert len(v["checks"]) > 0

    def test_person_scope(self, market_data):
        returns, prices, fx = market_data
        results = run_workbench(
            [{"strategy": {"type": "spy_bnh"}}],
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert results[0]["person"]["health_insurance_krw"] >= 0


class TestRunWorkbenchJson:

    def test_valid_json(self, market_data):
        returns, prices, fx = market_data
        json_str = run_workbench_json(
            [{"strategy": {"type": "spy_bnh"}}],
            returns=returns, prices=prices, fx_rates=fx,
        )
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert "result" in parsed[0]

    def test_multi_strategy_json(self, market_data):
        returns, prices, fx = market_data
        json_str = run_workbench_json(
            [
                {"strategy": {"type": "spy_bnh"}},
                {"strategy": {"type": "q60s40"}},
            ],
            returns=returns, prices=prices, fx_rates=fx,
        )
        parsed = json.loads(json_str)
        assert len(parsed) == 2
