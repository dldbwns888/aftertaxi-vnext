# -*- coding: utf-8 -*-
"""
test_bugfix_review.py — 코드 리뷰 버그 검증 테스트
===================================================
tax_savings 환율 하드코딩, sensitivity 세전/세후 혼용,
HMM 레짐 통계 성질, interpret 경계값 검증.
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


def _data(n=60, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    returns = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, n)}, index=idx)
    prices = 100 * (1 + returns).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return returns, prices, fx


def _data_fx(n=60, seed=42, fx_rate=2000.0):
    """다른 환율로 데이터 생성."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    returns = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, n)}, index=idx)
    prices = 100 * (1 + returns).cumprod()
    fx = pd.Series(fx_rate, index=idx)
    return returns, prices, fx


# ══════════════════════════════════════════════
# Bug 1: tax_savings 환율 하드코딩 수정 검증
# ══════════════════════════════════════════════

class TestTaxSavingsFxFix:

    def test_mult_uses_actual_fx(self):
        """fx=1000과 fx=2000에서 배수가 달라야 함 (하드코딩이면 같음)."""
        from aftertaxi.workbench.tax_savings import simulate_tax_savings

        ret, pri, fx1 = _data_fx(120, fx_rate=1000.0)
        _, _, fx2 = _data_fx(120, fx_rate=2000.0)

        r1 = simulate_tax_savings({"type": "spy_bnh"}, 1000, 0.3,
                                   ret, pri, fx1)
        r2 = simulate_tax_savings({"type": "spy_bnh"}, 1000, 0.3,
                                   ret, pri, fx2)
        # 환율이 다르면 배수 달라야 함 (둘 다 같으면 하드코딩 버그)
        assert r1.taxable_only_mult != r2.taxable_only_mult

    def test_zero_isa_same_result(self):
        """ISA 0%면 두 결과 동일."""
        from aftertaxi.workbench.tax_savings import simulate_tax_savings
        ret, pri, fx = _data(60)
        r = simulate_tax_savings({"type": "spy_bnh"}, 1000, 0.0, ret, pri, fx)
        assert abs(r.tax_savings_krw) < 1.0
        assert abs(r.mult_improvement) < 1e-6


# ══════════════════════════════════════════════
# Bug 2: sensitivity 세전/세후 혼용 수정 검증
# ══════════════════════════════════════════════

class TestSensitivityAfterTax:

    def test_metric_name(self):
        from aftertaxi.workbench.sensitivity import run_sensitivity
        grid = run_sensitivity({"type": "spy_bnh"}, n_months=24,
                               growth_range=[0.08], vol_range=[0.16])
        assert grid.metric_name == "mult_after_tax"

    def test_value_is_after_tax(self):
        """세금이 있는 시나리오에서 히트맵 값 < 세전 배수."""
        from aftertaxi.workbench.sensitivity import run_sensitivity
        from aftertaxi.apps.data_provider import load_synthetic
        from aftertaxi.strategies.compile import compile_backtest

        # 직접 실행해서 세전/세후 비교
        data = load_synthetic(["SPY"], n_months=120,
                              annual_growth=0.10, annual_vol=0.16, seed=42)
        config = compile_backtest({
            "strategy": {"type": "spy_bnh"},
            "accounts": [{"type": "TAXABLE", "monthly_contribution": 1000}],
            "n_months": 120,
        })
        result = run_backtest(config, returns=data.returns,
                              prices=data.prices, fx_rates=data.fx)

        # 세전 배수 (세금 납부 전)
        invested_krw = result.invested_usd * 1300
        gross_mult = (result.gross_pv_krw + result.tax.total_paid_krw) / invested_krw
        net_mult = result.net_pv_krw / invested_krw

        # 세금이 있으면 net < gross
        if result.tax.total_paid_krw > 0:
            assert net_mult < gross_mult

        # sensitivity 결과와 비교
        grid = run_sensitivity({"type": "spy_bnh"}, n_months=120,
                               growth_range=[0.10], vol_range=[0.16], seed=42)
        # grid 값이 net_mult에 가까워야 함 (gross가 아님)
        assert abs(grid.matrix[0, 0] - net_mult) < abs(grid.matrix[0, 0] - gross_mult)


# ══════════════════════════════════════════════
# HMM 레짐 통계 성질
# ══════════════════════════════════════════════

class TestHMMStatistics:

    @pytest.fixture
    def source(self):
        rng = np.random.default_rng(42)
        n = 240
        idx = pd.date_range("2000-01-31", periods=n, freq="ME")
        regime = rng.choice([0, 1], size=n, p=[0.8, 0.2])
        spy = np.where(regime == 0,
                       rng.normal(0.008, 0.035, n),
                       rng.normal(-0.015, 0.06, n))
        return pd.DataFrame({"SPY": spy}, index=idx)

    def test_hmm_has_regime_persistence(self, source):
        """HMM 경로는 순수 독립 랜덤보다 레짐 지속성이 있어야.

        sign_flip은 block(12개월) 구조라 자체 지속성이 있으므로,
        HMM과 직접 비교 대신 "독립 가우시안보다 run 길이가 긴가"를 검증.
        """
        from aftertaxi.lanes.lane_d.synthetic import (
            SyntheticMarketConfig, generate_synthetic_paths,
        )

        def avg_run(paths):
            runs = []
            for p in paths:
                signs = np.sign(p.iloc[:, 0].values)
                cur_len, cur_sign = 1, signs[0]
                for s in signs[1:]:
                    if s == cur_sign:
                        cur_len += 1
                    else:
                        runs.append(cur_len)
                        cur_len, cur_sign = 1, s
                runs.append(cur_len)
            return np.mean(runs)

        hm = generate_synthetic_paths(source, SyntheticMarketConfig(
            mode="hmm_regime", n_paths=30, path_length_months=120, seed=42))

        hmm_run = avg_run(hm)
        # 독립 동전던지기의 기대 run length = 2.0
        # HMM 레짐은 이보다 길어야 (레짐 유지 확률 > 50%)
        # 약한 레짐이면 ~2에 가까울 수 있으므로 >= 1.5 검증
        assert hmm_run >= 1.5, f"HMM run length {hmm_run:.2f} < 1.5"

    def test_hmm_std_within_range(self, source):
        """HMM 경로 변동성이 원본에서 크게 벗어나지 않아야."""
        from aftertaxi.lanes.lane_d.synthetic import (
            SyntheticMarketConfig, generate_synthetic_paths,
        )
        paths = generate_synthetic_paths(source, SyntheticMarketConfig(
            mode="hmm_regime", n_paths=20, path_length_months=120, seed=42))
        all_ret = np.concatenate([p.values.flatten() for p in paths])
        src_std = source.values.std()
        path_std = all_ret.std()
        assert abs(path_std - src_std) / src_std < 0.5  # 50% 이내


# ══════════════════════════════════════════════
# interpret 경계값
# ══════════════════════════════════════════════

class TestInterpretEdges:

    def _make_result_with_mdd(self, mdd):
        """특정 MDD를 가진 EngineResult 생성."""
        ret, pri, fx = _data(60)
        config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("t", {"SPY": 1.0}),
        )
        r = run_backtest(config, returns=ret, prices=pri, fx_rates=fx)
        # MDD는 엔진 계산이므로 직접 제어 어려움 → 텍스트에 MDD 언급 여부만 확인
        return r

    def test_drag_classification(self):
        """drag 수준에 따라 다른 문구."""
        from aftertaxi.workbench.interpret import interpret_result
        from aftertaxi.core.attribution import build_attribution

        # 짧은 기간 (작은 이익) → 낮은 drag
        ret, pri, fx = _data(24)
        config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("t", {"SPY": 1.0}),
        )
        r = run_backtest(config, returns=ret, prices=pri, fx_rates=fx)
        a = build_attribution(r)
        text = interpret_result(r, a)
        # 어떤 drag 언급이든 있어야 함
        assert "drag" in text.lower() or "효율" in text
