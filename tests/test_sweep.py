# -*- coding: utf-8 -*-
"""test_sweep.py — 파라미터 스윕 테스트"""

import numpy as np
import pandas as pd
import pytest
from aftertaxi.workbench.sweep import run_sweep, SweepConfig, _generate_combos


class TestSweep:

    @pytest.fixture
    def market(self):
        rng = np.random.default_rng(42)
        idx = pd.date_range("2020-01-31", periods=24, freq="ME")
        ret = pd.DataFrame({
            "SPY": rng.normal(0.008, 0.04, 24),
            "SSO": rng.normal(0.012, 0.06, 24),
        }, index=idx)
        pri = 100 * (1 + ret).cumprod()
        fx = pd.Series(1300.0, index=idx)
        return ret, pri, fx

    def test_generate_combos(self):
        combos = _generate_combos({"a": [1, 2], "b": [10, 20]})
        assert len(combos) == 4

    def test_weight_sweep(self, market):
        ret, pri, fx = market
        config = SweepConfig(
            base_payload={
                "strategy": {"type": "custom", "weights": {"SPY": 0.6, "SSO": 0.4}},
                "accounts": [{"type": "TAXABLE", "monthly_contribution": 1000}],
                "n_months": 24,
            },
            param_grid={
                "strategy.weights.SPY": [0.4, 0.6, 0.8],
                "strategy.weights.SSO": [0.6, 0.4, 0.2],
            },
        )
        result = run_sweep(config, ret, pri, fx)
        assert len(result.rows) == 9  # 3 × 3
        assert result.best
        assert result.best["mult_after_tax"] >= result.worst["mult_after_tax"]

    def test_to_dataframe(self, market):
        ret, pri, fx = market
        config = SweepConfig(
            base_payload={
                "strategy": {"type": "spy_bnh"},
                "accounts": [{"type": "TAXABLE"}],
                "n_months": 24,
            },
            param_grid={"accounts.0.monthly_contribution": [500, 1000, 2000]},
        )
        result = run_sweep(config, ret, pri, fx)
        df = result.to_dataframe()
        assert len(df) == 3
        assert "mult_after_tax" in df.columns
