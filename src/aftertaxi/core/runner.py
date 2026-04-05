# -*- coding: utf-8 -*-
"""
runner.py — 최소 FX-only 백테스트 실행기
==========================================
PR 2: C/O 단일 경로. 월 루프 + 세금 정산 + 최종 청산.

실행 순서 (매월):
  1. mark_to_market
  2. 연도 전환이면 prev_year settle + pay_tax
  3. deposit
  4. C/O buy (target weights 비례 배분)
  5. record_month

최종:
  1. liquidate
  2. settle (마지막 연도)
  3. ISA settle (해당 시)
  4. pay_tax

빌딩 블록은 core/engine_steps.py에 정의.
이 모듈은 고정 비중 실행기(run_engine)만 제공.
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from aftertaxi.core.contracts import (
    BacktestConfig, EngineResult, RebalanceMode,
)
from aftertaxi.core.ledger import AccountLedger
from aftertaxi.core.settlement import settle_final
from aftertaxi.core.allocation import AllocationPlanner

# ── 빌딩 블록 import (engine_steps가 single source of truth) ──
from aftertaxi.core.engine_steps import (
    DUST_PCT,
    create_ledgers,
    build_fx_lookup,
    get_fx_rate,
    snapshot_tax,
    record_tax_delta,
    step_mark_to_market,
    step_year_boundary,
    step_dividends,
    step_record,
    execute_contribution_only,
    execute_full_rebalance,
    drift_exceeds_threshold,
    aggregate,
)


def run_engine(
    config: BacktestConfig,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    journal=None,
) -> EngineResult:
    """FX-only 백테스트 실행.

    월 루프는 5개 step 함수로 분해:
      step_mark_to_market → step_year_boundary → step_dividends
      → _step_deposit_and_rebalance → step_record
    순서 변경 금지. 의미론 변경 금지. 구조 추출만.
    """
    index = prices.index
    n = config.n_months if config.n_months else len(index) - config.start_index
    start = config.start_index
    fx_lookup = build_fx_lookup(fx_rates)

    # ── 계좌 생성 ──
    ledgers = create_ledgers(config, journal=journal)

    planner = AllocationPlanner(config.accounts)
    total_contribution = sum(ac.monthly_contribution for ac in config.accounts)

    # ── 월 루프 ──
    current_year = index[start].year if start < len(index) else None
    annual_tax_history = []

    for step in range(n):
        i = start + step
        if i >= len(index):
            break

        dt = index[i]
        price_map = {k: v for k, v in prices.iloc[i].to_dict().items() if v == v}
        fx_rate = get_fx_rate(dt, fx_lookup)

        step_mark_to_market(ledgers, price_map)

        current_year, year_tax = step_year_boundary(
            ledgers, current_year, dt, fx_rate, config.enable_health_insurance)
        if year_tax is not None:
            annual_tax_history.append(year_tax)

        step_dividends(ledgers, config.dividend_schedule, step, price_map, fx_rate)

        _step_deposit_and_rebalance(
            ledgers, planner, config.accounts,
            target_weights=config.strategy.weights,
            total_contribution=total_contribution,
            step=step, rebal_every=config.strategy.rebalance_every,
            price_map=price_map, fx_rate=fx_rate)

        step_record(ledgers)

    # ── 최종 청산 ──
    final_i = min(start + n - 1, len(index) - 1)
    final_dt = index[final_i]
    final_prices = {k: v for k, v in prices.iloc[final_i].to_dict().items() if v == v}
    final_fx = get_fx_rate(final_dt, fx_lookup)

    before = snapshot_tax(ledgers)
    settle_final(ledgers, final_dt.year, final_prices, final_fx,
                 enable_health_insurance=config.enable_health_insurance)
    after = snapshot_tax(ledgers)
    record_tax_delta(annual_tax_history, before, after, final_dt.year)

    return aggregate(ledgers, final_fx, annual_tax_history)


# ══════════════════════════════════════════════
# Runner-specific step (고정 비중 전용)
# ══════════════════════════════════════════════

def _step_deposit_and_rebalance(
    ledgers: Dict[str, AccountLedger],
    planner: AllocationPlanner,
    accounts: list,
    target_weights: Dict[str, float],
    total_contribution: float,
    step: int,
    rebal_every: int,
    price_map: Dict[str, float],
    fx_rate: float,
) -> None:
    """3~4. 입금 + 리밸런싱/매수."""
    ytd = {ac.account_id: ledgers[ac.account_id].annual_contribution_krw
           for ac in accounts}
    orders = planner.plan(
        target_weights=target_weights,
        total_contribution=total_contribution,
        month_index=step,
        rebalance_every=rebal_every,
        ytd_contributions=ytd,
        fx_rate=fx_rate,
    )

    for order in orders:
        ledger = ledgers[order.account_id]

        if order.deposit > 0:
            ledger.deposit(order.deposit, fx_rate)

        if order.rebalance_mode == RebalanceMode.FULL and order.should_rebalance:
            execute_full_rebalance(ledger, order.target_weights, price_map, fx_rate)
        elif order.rebalance_mode == RebalanceMode.BAND and order.should_rebalance:
            if drift_exceeds_threshold(ledger, order.target_weights, price_map,
                                       order.band_threshold_pct):
                execute_full_rebalance(ledger, order.target_weights, price_map, fx_rate)
            else:
                execute_contribution_only(ledger, order.target_weights, price_map, fx_rate)
        else:
            execute_contribution_only(ledger, order.target_weights, price_map, fx_rate)
