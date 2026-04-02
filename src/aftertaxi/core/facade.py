# -*- coding: utf-8 -*-
"""
facade.py — 공개 API 단일 진입점
==================================
PR 1: 기존 aftertaxi engine_v2를 감싸서 새 typed contract으로 변환.
PR 2: 내부를 새 runner로 교체. 이 파일의 시그니처는 안 바뀜.

사용법:
    from aftertaxi.core.facade import run_backtest
    result = run_backtest(config, returns=returns, prices=prices, fx_store=fx_store)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import (
    AccountConfig, AccountSummary, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig, TaxSummary,
)


def run_backtest(
    config: BacktestConfig,
    *,
    returns: pd.DataFrame,
    prices: Optional[pd.DataFrame] = None,
    fx_store=None,
) -> EngineResult:
    """단일 진입점. config + 데이터 → typed EngineResult.

    PR 1: 내부에서 기존 PortfolioRunnerV2를 호출.
    PR 2 이후: 새 runner로 교체. 이 시그니처는 유지.
    """
    legacy_accounts, legacy_strategy, runner_kwargs = _translate_config(
        config, returns, prices, fx_store,
    )
    legacy_result = _run_legacy_engine(
        returns, legacy_accounts, legacy_strategy, runner_kwargs, config,
    )
    return _translate_result(legacy_result, fx_store is not None)


# ══════════════════════════════════════════════
# Translation: new config → legacy inputs
# ══════════════════════════════════════════════

def _translate_config(config, returns, prices, fx_store):
    """BacktestConfig → 기존 엔진 입력 변환."""
    # 지연 import: 기존 엔진이 설치 안 돼도 contracts는 사용 가능
    from engine_v2.account_spec import (
        AccountSpec, AccountType as LegacyAccountType,
        TaxRule, ContributionRule, RebalanceRule,
        RebalanceMode as LegacyRebalMode,
        TAXABLE_TAX, ISA_TAX,
    )
    from engine_v2.fx_rules import FxRateStore
    from strategy_registry import StrategySpec

    # 계좌 변환
    legacy_accounts = []
    for ac in config.accounts:
        if ac.account_type == AccountType.TAXABLE:
            tax_rule = TAXABLE_TAX
            acct_type = LegacyAccountType.TAXABLE
        else:
            tax_rule = TaxRule(
                capital_gains_rate=0.0,
                annual_exemption=0.0,
                dividend_withholding=0.0,
                isa_exempt_limit=ac.tax_config.isa_exempt_limit,
                isa_excess_rate=ac.tax_config.capital_gains_rate,
            )
            acct_type = LegacyAccountType.ISA

        rebal_mode = {
            RebalanceMode.CONTRIBUTION_ONLY: LegacyRebalMode.CONTRIBUTION_ONLY,
            RebalanceMode.FULL: LegacyRebalMode.FULL,
            RebalanceMode.BUDGET: LegacyRebalMode.BUDGET,
        }[ac.rebalance_mode]

        spec = AccountSpec(
            account_id=ac.account_id,
            account_type=acct_type,
            tax_rule=tax_rule,
            contribution_rule=ContributionRule(
                monthly_amount=ac.monthly_contribution,
                priority=len(legacy_accounts),
                annual_cap=ac.annual_cap,
            ),
            rebalance_rule=RebalanceRule(
                mode=rebal_mode,
                lot_method=ac.lot_method,
            ),
            allowed_assets=ac.allowed_assets,
        )
        legacy_accounts.append(spec)

    # 전략 변환
    n = len(returns) if config.n_months is None else config.n_months
    idx = returns.index[config.start_index: config.start_index + n]
    weights_df = pd.DataFrame(
        {a: [w] * len(idx) for a, w in config.strategy.weights.items()},
        index=idx,
    )
    every = config.strategy.rebalance_every
    mask = pd.Series(
        [(i % every == 0) for i in range(len(idx))],
        index=idx,
    )
    mask.iloc[0] = True
    legacy_strategy = StrategySpec(
        name=config.strategy.name,
        weights=weights_df,
        rebalance_mask=mask,
        metadata={},
    )

    runner_kwargs = {}
    if fx_store is not None:
        runner_kwargs["fx_store"] = fx_store
    if prices is not None:
        runner_kwargs["prices"] = prices

    return legacy_accounts, legacy_strategy, runner_kwargs


# ══════════════════════════════════════════════
# Legacy engine call
# ══════════════════════════════════════════════

def _run_legacy_engine(returns, accounts, strategy, runner_kwargs, config):
    """기존 PortfolioRunnerV2 호출."""
    from engine_v2.portfolio_runner import PortfolioRunnerV2

    runner = PortfolioRunnerV2(
        returns=returns,
        accounts=accounts,
        **runner_kwargs,
    )
    return runner.run(
        strategy,
        start_i=config.start_index,
        n_months=config.n_months,
    )


# ══════════════════════════════════════════════
# Translation: legacy result → typed EngineResult
# ══════════════════════════════════════════════

def _translate_result(legacy: dict, fx_enabled: bool) -> EngineResult:
    """기존 결과 dict → typed EngineResult."""
    # 계좌별 요약
    account_summaries = []
    for s in legacy["accounts"]:
        account_summaries.append(AccountSummary(
            account_id=s["account_id"],
            account_type=s["account_type"],
            gross_pv_usd=s["pv"],
            invested_usd=s["invested"],
            tax_assessed_krw=s.get("tax_assessed_krw", s.get("tax_paid", 0)),
            tax_unpaid_krw=s.get("unpaid_tax_liability_krw", 0),
            mdd=s["mdd"],
            n_months=s["n_months"],
        ))

    # 세금 요약 — FX에서 deprecated 'tax' 키 접근 방지
    if "tax_assessed_krw" in legacy:
        assessed = legacy["tax_assessed_krw"]
    else:
        assessed = legacy.get("tax", 0)  # legacy 모드 fallback
    unpaid = legacy.get("unpaid_tax_krw", 0)
    tax_summary = TaxSummary(
        total_assessed_krw=assessed,
        total_unpaid_krw=unpaid,
        total_paid_krw=assessed - unpaid,
    )

    # monthly_values
    mv = legacy.get("monthly_values")
    if mv is not None and not isinstance(mv, np.ndarray):
        mv = np.array(mv, dtype=float)
    if mv is None:
        mv = np.array([], dtype=float)

    return EngineResult(
        gross_pv_usd=legacy["pv"],
        invested_usd=legacy["inv"],
        gross_pv_krw=legacy.get("gross_pv_krw", legacy["pv"]),
        net_pv_krw=legacy.get("net_pv_krw", legacy["pv"]),
        reporting_fx_rate=legacy.get("reporting_fx_rate", 1.0),
        mdd=legacy["mdd"],
        n_months=legacy["n_months"],
        n_accounts=legacy["n_accounts"],
        tax=tax_summary,
        accounts=account_summaries,
        monthly_values=mv,
    )
