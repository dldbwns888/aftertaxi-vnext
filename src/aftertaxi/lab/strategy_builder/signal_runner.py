# -*- coding: utf-8 -*-
"""
lab/strategy_builder/signal_runner.py — 동적 비중 백테스트 실행기
================================================================
코어 엔진(core/runner.py)을 수정하지 않고, 같은 부품(engine_steps)을
재조립해서 월별 비중 변경을 지원한다.

설계 원칙:
  1. core/ 수정 0줄. core의 public API만 소비.
  2. 고정 비중이면 core runner와 숫자 동일 (equivalence test로 보장).
  3. 동적 비중이면 매월 target_weights가 변할 수 있음.
  4. source="strategy_builder" 태그로 core 전략과 분리.

의존 관계:
  lab/strategy_builder/signal_runner.py
    → core/engine_steps.py (public 빌딩 블록)
    → core/settlement.py (settle_final)
    → core/allocation.py (AllocationPlanner)
    → core/contracts.py (dataclasses)
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig,
)
from aftertaxi.core.ledger import AccountLedger
from aftertaxi.core.settlement import settle_final
from aftertaxi.core.allocation import AllocationPlanner

# engine_steps의 public API 직접 사용 (runner private 의존 해소)
from aftertaxi.core.engine_steps import (
    build_fx_lookup,
    get_fx_rate,
    create_ledgers,
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
    DUST_PCT,
)


def run_signal_backtest(
    config: BacktestConfig,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    weight_schedule: List[Dict[str, float]],
    journal=None,
) -> EngineResult:
    """동적 비중 백테스트 실행.

    core/runner.py의 run_engine()과 동일한 로직이나,
    매월 target_weights를 weight_schedule[step]에서 가져온다.

    Parameters
    ----------
    config : 계좌/전략 설정 (strategy.weights는 fallback으로만 사용)
    prices : 월별 가격 DataFrame
    fx_rates : 월별 환율 Series
    weight_schedule : 월별 목표 비중 리스트. len >= n_months 필요.
                      부족하면 마지막 비중 반복.
    journal : Optional[EventJournal]

    Returns
    -------
    EngineResult : core runner와 동일한 typed 결과
    """
    index = prices.index
    n = config.n_months if config.n_months else len(index) - config.start_index
    start = config.start_index
    fx_lookup = build_fx_lookup(fx_rates)

    # ── 계좌 생성 (runner 팩토리 공유) ──
    ledgers = create_ledgers(config, journal=journal)

    planner = AllocationPlanner(config.accounts)
    total_contribution = sum(ac.monthly_contribution for ac in config.accounts)

    # ── 월 루프 (동적 비중) ──
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

        # ── 핵심 차이: 동적 비중 ──
        if step < len(weight_schedule):
            target_weights = weight_schedule[step]
        else:
            # schedule 소진 시 마지막 비중 유지
            target_weights = weight_schedule[-1] if weight_schedule else config.strategy.weights

        _step_deposit_and_rebalance_dynamic(
            ledgers, planner, config.accounts,
            target_weights=target_weights,
            total_contribution=total_contribution,
            step=step, rebal_every=config.strategy.rebalance_every,
            price_map=price_map, fx_rate=fx_rate)

        step_record(ledgers)

    # ── 최종 청산 (runner 헬퍼 공유) ──
    final_i = min(start + n - 1, len(index) - 1)
    final_dt = index[final_i]
    final_prices = {
        k: v for k, v in prices.iloc[final_i].to_dict().items() if v == v
    }
    final_fx = get_fx_rate(final_dt, fx_lookup)

    before = snapshot_tax(ledgers)
    settle_final(ledgers, final_dt.year, final_prices, final_fx,
                 enable_health_insurance=config.enable_health_insurance)
    after = snapshot_tax(ledgers)
    record_tax_delta(annual_tax_history, before, after, final_dt.year)

    return aggregate(ledgers, final_fx, annual_tax_history)


# ══════════════════════════════════════════════
# 동적 비중용 deposit+rebalance (runner의 것을 재조립)
# ══════════════════════════════════════════════

def _step_deposit_and_rebalance_dynamic(
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
    """동적 비중용 deposit+rebalance.

    core runner의 _step_deposit_and_rebalance와 동일하나,
    target_weights가 매월 달라질 수 있다.
    """
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
            execute_full_rebalance(
                ledger, order.target_weights, price_map, fx_rate)
        elif (order.rebalance_mode == RebalanceMode.BAND
              and order.should_rebalance):
            if drift_exceeds_threshold(
                ledger, order.target_weights, price_map,
                order.band_threshold_pct,
            ):
                execute_full_rebalance(
                    ledger, order.target_weights, price_map, fx_rate)
            else:
                execute_contribution_only(
                    ledger, order.target_weights, price_map, fx_rate)
        else:
            execute_contribution_only(
                ledger, order.target_weights, price_map, fx_rate)


# ══════════════════════════════════════════════
# 유틸리티
# ══════════════════════════════════════════════

def make_constant_schedule(
    weights: Dict[str, float],
    n_months: int,
) -> List[Dict[str, float]]:
    """고정 비중 스케줄 생성. equivalence test용."""
    return [dict(weights) for _ in range(n_months)]


def make_switching_schedule(
    growth_weights: Dict[str, float],
    shelter_weights: Dict[str, float],
    signals: List[bool],
) -> List[Dict[str, float]]:
    """신호 기반 전환 스케줄 생성.

    signals[i] = True  → growth_weights
    signals[i] = False → shelter_weights
    """
    return [
        dict(growth_weights) if sig else dict(shelter_weights)
        for sig in signals
    ]
