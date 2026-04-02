# -*- coding: utf-8 -*-
"""
test_validation.py — 검증 레이어 테스트
========================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.validation import validate, ValidationReport, Grade
from aftertaxi.validation.basic import run_basic_checks
from aftertaxi.validation.statistical import (
    check_dsr, check_psr, check_bootstrap_sharpe, check_permutation, check_cusum,
    run_statistical_checks,
)
from aftertaxi.validation.reports import CheckResult


def _make_engine_result():
    idx = pd.date_range("2020-01-31", periods=60, freq="ME")
    prices_list = [100 * (1.01 ** i) for i in range(60)]
    prices = pd.DataFrame({"SPY": prices_list}, index=idx)
    fx = pd.Series(1300.0, index=idx)
    returns = prices.pct_change().fillna(0.0)
    return run_backtest(
        BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("test", {"SPY": 1.0}),
        ),
        returns=returns, prices=prices, fx_rates=fx,
    )


def _make_excess_returns(n=120, mean=0.005, std=0.04, seed=42):
    rng = np.random.default_rng(seed)
    return rng.normal(mean, std, n)


# ══════════════════════════════════════════════
# Basic checks
# ══════════════════════════════════════════════

class TestBasicChecks:

    def test_basic_all_pass(self):
        result = _make_engine_result()
        checks = run_basic_checks(result)
        assert len(checks) == 5
        assert all(c.grade == Grade.PASS for c in checks)

    def test_returns_check_result(self):
        result = _make_engine_result()
        checks = run_basic_checks(result)
        for c in checks:
            assert isinstance(c, CheckResult)
            assert c.name != ""


# ══════════════════════════════════════════════
# DSR
# ══════════════════════════════════════════════

class TestDSR:

    def test_strong_signal(self):
        er = _make_excess_returns(180, mean=0.012, std=0.025)
        r = check_dsr(er, n_trials=1)
        assert r.name == "dsr"
        assert r.value < 0.10  # p < 10% (DSR은 보수적)

    def test_weak_signal(self):
        er = _make_excess_returns(60, mean=0.001, std=0.05)
        r = check_dsr(er, n_trials=50)  # 50번 시도
        assert r.grade in (Grade.WARN, Grade.FAIL)

    def test_short_data(self):
        er = np.array([0.01, 0.02, -0.01])
        r = check_dsr(er)
        assert r.grade == Grade.WARN


# ══════════════════════════════════════════════
# PSR
# ══════════════════════════════════════════════

class TestPSR:

    def test_strong_positive(self):
        er = _make_excess_returns(120, mean=0.01, std=0.03)
        r = check_psr(er, benchmark_sharpe=0.0)
        assert r.grade == Grade.PASS
        assert r.value > 0.95

    def test_vs_high_benchmark(self):
        er = _make_excess_returns(60, mean=0.005, std=0.04)
        r = check_psr(er, benchmark_sharpe=1.0)
        assert r.value < 0.95  # 벤치 1.0을 이기기 어려움


# ══════════════════════════════════════════════
# Bootstrap
# ══════════════════════════════════════════════

class TestBootstrap:

    def test_positive_ci(self):
        er = _make_excess_returns(120, mean=0.01, std=0.03)
        r = check_bootstrap_sharpe(er)
        assert r.grade == Grade.PASS
        assert r.value > 0  # ci_lo > 0

    def test_noisy_signal(self):
        er = _make_excess_returns(36, mean=0.001, std=0.06)
        r = check_bootstrap_sharpe(er)
        # 짧고 노이즈 많으면 CI가 0을 포함할 수 있음
        assert r.name == "bootstrap_sharpe"

    def test_reproducible(self):
        er = _make_excess_returns(120)
        r1 = check_bootstrap_sharpe(er)
        r2 = check_bootstrap_sharpe(er)
        assert r1.value == r2.value  # seed 고정


# ══════════════════════════════════════════════
# Permutation
# ══════════════════════════════════════════════

class TestPermutation:

    def test_clearly_better(self):
        strat = _make_excess_returns(120, mean=0.01, std=0.03)
        bench = _make_excess_returns(120, mean=0.0, std=0.03, seed=99)
        r = check_permutation(strat, bench)
        assert r.grade == Grade.PASS
        assert r.value < 0.05

    def test_same_distribution(self):
        er = _make_excess_returns(120, mean=0.005, std=0.04)
        r = check_permutation(er, er)  # 같은 시리즈
        assert r.value > 0.05  # 유의하지 않아야


# ══════════════════════════════════════════════
# CUSUM
# ══════════════════════════════════════════════

class TestCUSUM:

    def test_stable(self):
        er = _make_excess_returns(120, mean=0.005, std=0.04)
        r = check_cusum(er)
        assert r.name == "cusum"

    def test_structural_break(self):
        """전반/후반 수익률이 크게 다르면 감지."""
        rng = np.random.default_rng(42)
        before = rng.normal(0.02, 0.02, 60)
        after = rng.normal(-0.01, 0.02, 60)
        er = np.concatenate([before, after])
        r = check_cusum(er)
        assert r.grade == Grade.WARN


# ══════════════════════════════════════════════
# 통합 validate()
# ══════════════════════════════════════════════

class TestUnifiedValidate:

    def test_basic_only(self):
        result = _make_engine_result()
        report = validate(result=result, strategy_name="test")
        assert isinstance(report, ValidationReport)
        assert report.n_pass >= 5
        assert report.overall_grade == Grade.PASS

    def test_statistical_only(self):
        er = _make_excess_returns(120, mean=0.01, std=0.03)
        report = validate(excess_returns=er, strategy_name="stat_test")
        assert len(report.checks) >= 4  # DSR, PSR, Bootstrap, CUSUM

    def test_both(self):
        result = _make_engine_result()
        er = _make_excess_returns(60)
        report = validate(result=result, excess_returns=er, strategy_name="full")
        assert len(report.checks) >= 9  # 5 basic + 4 statistical

    def test_summary_text(self):
        result = _make_engine_result()
        er = _make_excess_returns(60)
        report = validate(result=result, excess_returns=er, strategy_name="Q60S40")
        text = report.summary_text()
        assert "Q60S40" in text
        assert "pass" in text.lower() or "PASS" in text


# ══════════════════════════════════════════════
# Stability: Rolling Sharpe
# ══════════════════════════════════════════════

from aftertaxi.validation.stability import (
    check_rolling_sharpe, check_walk_forward, check_is_oos_decay,
    run_stability_checks,
)


class TestRollingSharpe:

    def test_stable_positive(self):
        er = _make_excess_returns(180, mean=0.008, std=0.03)
        r = check_rolling_sharpe(er)
        assert r.name == "rolling_sharpe"
        assert r.grade in (Grade.PASS, Grade.WARN)

    def test_short_data(self):
        er = _make_excess_returns(30)
        r = check_rolling_sharpe(er, window=60)
        assert r.grade == Grade.WARN


# ══════════════════════════════════════════════
# Stability: Walk-Forward
# ══════════════════════════════════════════════

class TestWalkForward:

    def test_consistent_strategy(self):
        er = _make_excess_returns(180, mean=0.008, std=0.03)
        r = check_walk_forward(er)
        assert r.name == "walk_forward"
        # CV가 합리적이어야
        assert r.value < 5.0

    def test_short_data(self):
        er = _make_excess_returns(30)
        r = check_walk_forward(er, n_splits=5)
        assert r.grade == Grade.WARN


# ══════════════════════════════════════════════
# Stability: IS-OOS Decay
# ══════════════════════════════════════════════

class TestISOOSDecay:

    def test_mild_decay(self):
        er = _make_excess_returns(120, mean=0.008, std=0.03)
        r = check_is_oos_decay(er, split_index=80)
        assert r.name == "is_oos_decay"

    def test_insufficient_split(self):
        er = _make_excess_returns(30)
        r = check_is_oos_decay(er, split_index=5)
        assert r.grade == Grade.WARN


# ══════════════════════════════════════════════
# Suite Runner
# ══════════════════════════════════════════════

from aftertaxi.validation.run import run_validation_suite


class TestSuiteRunner:

    def test_full_suite(self):
        result = _make_engine_result()
        er = _make_excess_returns(120, mean=0.008, std=0.03)
        bench = _make_excess_returns(120, mean=0.0, std=0.04, seed=99)

        report = run_validation_suite(
            result=result,
            excess_returns=er,
            bench_returns=bench,
            strategy_name="full_test",
            is_oos_split=80,
        )

        assert isinstance(report, ValidationReport)
        assert report.strategy_name == "full_test"
        # basic 5 + statistical 3(dsr,psr,cusum) + heavy 2(bootstrap,perm)
        # + stability 3(rolling,wf,isoos)
        assert len(report.checks) >= 12

    def test_suite_parallel(self):
        er = _make_excess_returns(120, mean=0.008, std=0.03)
        bench = _make_excess_returns(120, mean=0.0, std=0.04, seed=99)

        r_seq = run_validation_suite(excess_returns=er, bench_returns=bench, n_jobs=1)
        r_par = run_validation_suite(excess_returns=er, bench_returns=bench, n_jobs=2)

        # 같은 결과
        assert r_seq.n_pass == r_par.n_pass
        assert r_seq.n_fail == r_par.n_fail

    def test_suite_summary(self):
        er = _make_excess_returns(120)
        report = run_validation_suite(excess_returns=er, strategy_name="Q60S40")
        text = report.summary_text()
        assert "Q60S40" in text
        assert "pass" in text.lower() or "warn" in text.lower() or "fail" in text.lower()
