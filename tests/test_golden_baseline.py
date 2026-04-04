# -*- coding: utf-8 -*-
"""
tests/test_golden_baseline.py — 골든 기준선 스냅샷
===================================================
Phase 0: 리팩터링 전후에 숫자가 바뀌지 않음을 보장.

seed=42, 60개월, fx=1300 고정 합성 데이터.
service.run_strategy() 경유 — 앱과 동일 경로.

이 테스트가 깨지면 → 엔진/세금/배분 로직이 변경된 것.
의도적 변경이면 골든 값을 업데이트. 비의도적이면 버그.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

# 골든 값 (seed=42, 60mo, fx=1300)
GOLDEN = {
    "taxable_only": {
        "gross_pv_usd": 80818.08926,
        "tax_assessed_krw": 6928171.19111,
        "net_pv_krw": 105063516.04120,
    },
    "isa_taxable": {
        "gross_pv_usd": 126768.03481,
        "tax_assessed_krw": 3189085.59555,
        "net_pv_krw": 164798445.25291,
    },
    "band_rebal": {
        "gross_pv_usd": 80818.08926,
        "tax_assessed_krw": 6928171.19111,
        "net_pv_krw": 105063516.04120,
    },
    "progressive": {
        "gross_pv_usd": 81304.27603,
        "tax_assessed_krw": 6296128.39333,
        "net_pv_krw": 105695558.83898,
    },
}

TOLERANCE = 0.01  # ₩0.01 이내


@pytest.fixture(scope="module")
def market():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-31", periods=60, freq="ME")
    ret = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, 60)}, index=idx)
    pri = 100 * (1 + ret).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return ret, pri, fx


def _run(payload, ret, pri, fx):
    from aftertaxi.apps.service import run_strategy
    return run_strategy(payload, ret, pri, fx, save_to_memory=False, run_baseline=False)


def _assert_golden(name, result):
    g = GOLDEN[name]
    assert abs(result.gross_pv_usd - g["gross_pv_usd"]) < TOLERANCE, \
        f"{name} gross: {result.gross_pv_usd} != {g['gross_pv_usd']}"
    assert abs(result.tax.total_assessed_krw - g["tax_assessed_krw"]) < TOLERANCE, \
        f"{name} tax: {result.tax.total_assessed_krw} != {g['tax_assessed_krw']}"
    assert abs(result.net_pv_krw - g["net_pv_krw"]) < TOLERANCE, \
        f"{name} net: {result.net_pv_krw} != {g['net_pv_krw']}"


class TestGoldenBaseline:
    """리팩터링 안전망. 이 값이 바뀌면 엔진이 변한 것."""

    def test_taxable_only(self, market):
        ret, pri, fx = market
        out = _run({"strategy": {"type": "spy_bnh"},
                     "accounts": [{"type": "TAXABLE", "monthly_contribution": 1000}]},
                    ret, pri, fx)
        _assert_golden("taxable_only", out.result)

    def test_isa_taxable(self, market):
        ret, pri, fx = market
        out = _run({"strategy": {"type": "spy_bnh"},
                     "accounts": [
                         {"type": "ISA", "monthly_contribution": 1000, "priority": 0},
                         {"type": "TAXABLE", "monthly_contribution": 500, "priority": 1}]},
                    ret, pri, fx)
        _assert_golden("isa_taxable", out.result)

    def test_band_rebalance(self, market):
        ret, pri, fx = market
        out = _run({"strategy": {"type": "spy_bnh"},
                     "accounts": [{"type": "TAXABLE", "monthly_contribution": 1000,
                                    "rebalance_mode": "BAND", "band_threshold_pct": 0.05}]},
                    ret, pri, fx)
        _assert_golden("band_rebal", out.result)

    def test_progressive_tax(self, market):
        ret, pri, fx = market
        out = _run({"strategy": {"type": "spy_bnh"},
                     "accounts": [{"type": "TAXABLE", "monthly_contribution": 1000,
                                    "progressive": True}]},
                    ret, pri, fx)
        _assert_golden("progressive", out.result)
