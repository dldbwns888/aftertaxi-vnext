# -*- coding: utf-8 -*-
"""test_export.py — Excel/CSV 내보내기 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.workbench.export import to_csv, to_csv_multi, to_excel, to_excel_multi


@pytest.fixture(scope="module")
def sample_result():
    idx = pd.date_range("2020-01-31", periods=24, freq="ME")
    prices = pd.DataFrame({"SPY": [100 + i for i in range(24)]}, index=idx)
    fx = pd.Series(1300.0, index=idx)
    returns = prices.pct_change().fillna(0.0)
    return run_backtest(
        BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("test", {"SPY": 1.0}),
        ),
        returns=returns, prices=prices, fx_rates=fx,
    )


class TestCSV:

    def test_to_csv(self, sample_result):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = to_csv(sample_result, f.name, "SPY")
        df = pd.read_csv(path)
        assert "pv_usd" in df.columns
        assert len(df) == sample_result.n_months

    def test_to_csv_multi(self, sample_result):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = to_csv_multi([sample_result, sample_result], ["A", "B"], f.name)
        df = pd.read_csv(path)
        assert "A" in df.columns
        assert "B" in df.columns


class TestExcel:

    def test_to_excel(self, sample_result):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = to_excel(sample_result, f.name, "SPY")
        xl = pd.ExcelFile(path)
        assert "요약" in xl.sheet_names
        assert "월별PV" in xl.sheet_names
        assert "계좌별" in xl.sheet_names
        summary = xl.parse("요약")
        assert summary["전략"].iloc[0] == "SPY"

    def test_to_excel_multi(self, sample_result):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = to_excel_multi(
                [sample_result, sample_result], ["Q60S40", "SPY"], f.name,
            )
        xl = pd.ExcelFile(path)
        assert "비교" in xl.sheet_names
        compare = xl.parse("비교")
        assert len(compare) == 2
        assert "Q60S40" in compare["전략"].values
