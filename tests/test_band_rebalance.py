# -*- coding: utf-8 -*-
"""
test_band_rebalance.py — BAND 리밸런스 테스트
=============================================
new capability: 비중 괴리 threshold 기반 조건부 FULL rebalance.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest


def _make_diverging_data(n=60):
    """SPY 꾸준히 상승, TLT 횡보 → 비중 괴리 유도."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    spy = 0.02 + rng.normal(0, 0.02, n)  # 강한 상승
    tlt = rng.normal(0, 0.01, n)          # 횡보
    returns = pd.DataFrame({"SPY": spy, "TLT": tlt}, index=idx)
    prices = 100.0 * (1 + returns).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return returns, prices, fx


def _run_with_mode(mode, threshold=0.05, n=60, **kwargs):
    returns, prices, fx = _make_diverging_data(n)
    config = BacktestConfig(
        accounts=[AccountConfig(
            "t", AccountType.TAXABLE, 1000.0,
            rebalance_mode=mode,
            band_threshold_pct=threshold,
            **kwargs,
        )],
        strategy=StrategyConfig("6040", {"SPY": 0.6, "TLT": 0.4}),
    )
    return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)


class TestBandBasic:

    def test_band_runs(self):
        """BAND 모드가 에러 없이 실행된다."""
        result = _run_with_mode(RebalanceMode.BAND)
        assert result.gross_pv_usd > 0
        assert result.n_months == 60

    def test_band_zero_threshold_equals_full(self):
        """threshold=0 → 매달 FULL (모든 괴리가 0 초과)."""
        r_band = _run_with_mode(RebalanceMode.BAND, threshold=0.0)
        r_full = _run_with_mode(RebalanceMode.FULL)
        # 세금 패턴이 같아야 함 (둘 다 매달 FULL)
        assert abs(r_band.tax.total_assessed_krw - r_full.tax.total_assessed_krw) < 1.0

    def test_band_huge_threshold_equals_co(self):
        """threshold=1.0 → 절대 FULL 안 함 (C/O와 동일)."""
        r_band = _run_with_mode(RebalanceMode.BAND, threshold=1.0)
        r_co = _run_with_mode(RebalanceMode.CONTRIBUTION_ONLY)
        assert abs(r_band.tax.total_assessed_krw - r_co.tax.total_assessed_krw) < 1.0

    def test_band_between_full_and_co(self):
        """적절한 threshold면 세금이 FULL/C/O와 다름.

        참고: BAND가 C/O보다 세금이 적을 수 있음.
        C/O는 최종 청산 시 큰 이익을 한번에 실현 (공제 1회).
        BAND는 중간 매도로 공제를 여러 해 분산 → 총 세금 감소 가능.
        """
        r_full = _run_with_mode(RebalanceMode.FULL)
        r_co = _run_with_mode(RebalanceMode.CONTRIBUTION_ONLY)
        r_band = _run_with_mode(RebalanceMode.BAND, threshold=0.10)

        # BAND는 FULL/C/O 중 최소보다 크거나 같고, 최대보다 작거나 같아야 함
        lo = min(r_full.tax.total_assessed_krw, r_co.tax.total_assessed_krw)
        hi = max(r_full.tax.total_assessed_krw, r_co.tax.total_assessed_krw)
        assert r_band.tax.total_assessed_krw >= lo - 1.0
        assert r_band.tax.total_assessed_krw <= hi + 1.0


class TestBandSemantics:

    def test_small_threshold_more_rebalancing(self):
        """작은 threshold → 더 많은 FULL 트리거.

        세금은 반드시 tight > loose가 아님:
        중간 매도 → 공제 분산 → 총 세금 감소 가능.
        대신 결과가 다름을 검증.
        """
        r_tight = _run_with_mode(RebalanceMode.BAND, threshold=0.03)
        r_loose = _run_with_mode(RebalanceMode.BAND, threshold=0.15)
        # 두 결과가 다름 (같은 threshold가 아닌 한)
        assert abs(r_tight.tax.total_assessed_krw - r_loose.tax.total_assessed_krw) > 1.0

    def test_single_asset_no_drift(self):
        """단일 자산이면 괴리 없음 → FULL 트리거 안 됨 → C/O와 동일."""
        idx = pd.date_range("2020-01-31", periods=24, freq="ME")
        rng = np.random.default_rng(42)
        returns = pd.DataFrame({"SPY": rng.normal(0.01, 0.03, 24)}, index=idx)
        prices = 100.0 * (1 + returns).cumprod()
        fx = pd.Series(1300.0, index=idx)

        def _run(mode):
            config = BacktestConfig(
                accounts=[AccountConfig(
                    "t", AccountType.TAXABLE, 1000.0,
                    rebalance_mode=mode,
                    band_threshold_pct=0.05,
                )],
                strategy=StrategyConfig("spy", {"SPY": 1.0}),
            )
            return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        r_band = _run(RebalanceMode.BAND)
        r_co = _run(RebalanceMode.CONTRIBUTION_ONLY)
        # 단일 자산 → 비중 항상 100% → 괴리 0 → BAND = C/O
        assert abs(r_band.tax.total_assessed_krw - r_co.tax.total_assessed_krw) < 1.0


class TestBandCompile:

    def test_compile_band(self):
        """JSON에서 BAND 설정."""
        from aftertaxi.strategies.compile import compile_backtest
        config = compile_backtest({
            "strategy": {"type": "spy_bnh"},
            "accounts": [{
                "type": "TAXABLE",
                "rebalance_mode": "BAND",
                "band_threshold_pct": 0.08,
            }],
        })
        assert config.accounts[0].rebalance_mode == RebalanceMode.BAND
        assert config.accounts[0].band_threshold_pct == 0.08

    def test_compile_band_default_threshold(self):
        from aftertaxi.strategies.compile import compile_backtest
        config = compile_backtest({
            "strategy": {"type": "spy_bnh"},
            "accounts": [{"type": "TAXABLE", "rebalance_mode": "BAND"}],
        })
        assert config.accounts[0].band_threshold_pct == 0.05


class TestBandEdgeCases:

    def test_empty_portfolio_no_crash(self):
        """포지션 없을 때 drift 체크 안전."""
        from aftertaxi.core.runner import _drift_exceeds_threshold
        from aftertaxi.core.ledger import AccountLedger
        ledger = AccountLedger("test", "TAXABLE")
        assert not _drift_exceeds_threshold(
            ledger, {"SPY": 0.6, "TLT": 0.4}, {"SPY": 100, "TLT": 50}, 0.05)

    def test_three_months(self):
        """짧은 기간에서도 동작."""
        result = _run_with_mode(RebalanceMode.BAND, threshold=0.05, n=3)
        assert result.n_months == 3
