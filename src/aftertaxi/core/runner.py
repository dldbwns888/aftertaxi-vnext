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
"""
from __future__ import annotations

import bisect
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import (
    AccountConfig, AccountSummary, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, TaxSummary,
)
from aftertaxi.core.ledger import AccountLedger
from aftertaxi.core.settlement import settle_year_end, settle_final


def run_engine(
    config: BacktestConfig,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    journal=None,
) -> EngineResult:
    """FX-only 백테스트 실행.

    Parameters
    ----------
    config : BacktestConfig
    prices : DataFrame, index=datetime, columns=assets, values=USD price
    fx_rates : Series, index=datetime, values=USDKRW rate
    journal : Optional[EventJournal], 이벤트 로그 (None이면 기록 안 함)
    """
    returns = prices.pct_change().fillna(0.0)
    index = prices.index
    n = config.n_months if config.n_months else len(index) - config.start_index
    start = config.start_index
    fx_lookup = _build_fx_lookup(fx_rates)

    # ── 계좌 생성 ──
    ledgers: Dict[str, AccountLedger] = {}
    for ac in config.accounts:
        ledgers[ac.account_id] = AccountLedger(
            account_id=ac.account_id,
            account_type=ac.account_type.value,
            tax_rate=ac.tax_config.capital_gains_rate if ac.account_type == AccountType.TAXABLE else 0.0,
            annual_exemption=ac.tax_config.annual_exemption if ac.account_type == AccountType.TAXABLE else 0.0,
            isa_exempt_limit=ac.tax_config.isa_exempt_limit if ac.account_type == AccountType.ISA else 0.0,
            isa_excess_rate=ac.tax_config.capital_gains_rate if ac.account_type == AccountType.ISA else 0.0,
            transaction_cost_bps=ac.transaction_cost_bps,
            journal=journal,
        )

    target_weights = config.strategy.weights
    rebal_every = config.strategy.rebalance_every

    # ── 월 루프 ──
    current_year = index[start].year if start < len(index) else None

    for step in range(n):
        i = start + step
        if i >= len(index):
            break

        dt = index[i]
        price_map = {k: v for k, v in prices.iloc[i].to_dict().items() if v == v}
        fx_rate = _get_fx_rate(dt, fx_lookup)

        # 1. 시가 반영
        for ledger in ledgers.values():
            ledger.mark_to_market(price_map)

        # 2. 연도 전환 → 세금 정산 (settlement에 위임)
        if current_year is not None and dt.year != current_year:
            settle_year_end(ledgers, current_year, fx_rate)
            current_year = dt.year

        # 3~4. 입금 + 리밸런싱/매수
        should_rebal = (step % rebal_every == 0)

        for ac in config.accounts:
            ledger = ledgers[ac.account_id]
            ledger.deposit(ac.monthly_contribution)

            if ac.rebalance_mode == RebalanceMode.FULL and should_rebal:
                _execute_full_rebalance(ledger, target_weights, price_map, fx_rate)
            else:
                _execute_contribution_only(ledger, target_weights, price_map, fx_rate)

        # 5. 월말 기록
        for ledger in ledgers.values():
            ledger.record_month()

    # ── 최종 청산 (settlement에 위임) ──
    final_i = min(start + n - 1, len(index) - 1)
    final_dt = index[final_i]
    final_prices = {k: v for k, v in prices.iloc[final_i].to_dict().items() if v == v}
    final_fx = _get_fx_rate(final_dt, fx_lookup)
    final_year = final_dt.year

    settle_final(ledgers, final_year, final_prices, final_fx)

    # ── 결과 집계 ──
    return _aggregate(ledgers, final_fx)


def _build_fx_lookup(fx_rates: pd.Series) -> tuple:
    """환율 Series → (dict, sorted_dates) 사전 구축. O(n) 1회."""
    fx_dict = {ts: float(v) for ts, v in fx_rates.items()}
    sorted_dates = sorted(fx_dict.keys())
    return fx_dict, sorted_dates


def _get_fx_rate(dt: pd.Timestamp, fx_lookup: tuple) -> float:
    """O(1) dict lookup + O(log n) bisect fallback."""
    fx_dict, sorted_dates = fx_lookup
    if dt in fx_dict:
        return fx_dict[dt]
    # bisect: 가장 가까운 이전 날짜
    idx = bisect.bisect_right(sorted_dates, dt) - 1
    if idx >= 0:
        return fx_dict[sorted_dates[idx]]
    return fx_dict[sorted_dates[0]]


def _aggregate(ledgers: Dict[str, AccountLedger], reporting_fx: float) -> EngineResult:
    """전 계좌 통합 결과."""
    account_summaries = []
    total_pv = 0.0
    total_inv = 0.0
    total_assessed = 0.0
    total_unpaid = 0.0
    combined_monthly = None

    for ledger in ledgers.values():
        s = ledger.summary()
        account_summaries.append(AccountSummary(
            account_id=s["account_id"],
            account_type=s["account_type"],
            gross_pv_usd=s["gross_pv_usd"],
            invested_usd=s["invested_usd"],
            tax_assessed_krw=s["tax_assessed_krw"],
            tax_unpaid_krw=s["tax_unpaid_krw"],
            mdd=s["mdd"],
            n_months=s["n_months"],
        ))
        total_pv += s["gross_pv_usd"]
        total_inv += s["invested_usd"]
        total_assessed += s["tax_assessed_krw"]
        total_unpaid += s["tax_unpaid_krw"]

        mv = s["monthly_values"]
        if combined_monthly is None:
            combined_monthly = mv.copy()
        else:
            min_len = min(len(combined_monthly), len(mv))
            combined_monthly = combined_monthly[:min_len] + mv[:min_len]

    if combined_monthly is not None and len(combined_monthly) > 0:
        peak = np.maximum.accumulate(np.where(combined_monthly > 0, combined_monthly, 1.0))
        mdd = float((combined_monthly / peak - 1.0).min())
    else:
        mdd = 0.0

    n_months = max(len(l.monthly_values) for l in ledgers.values()) if ledgers else 0

    gross_krw = total_pv * reporting_fx
    net_krw = gross_krw - total_unpaid

    return EngineResult(
        gross_pv_usd=total_pv,
        invested_usd=total_inv,
        gross_pv_krw=gross_krw,
        net_pv_krw=net_krw,
        reporting_fx_rate=reporting_fx,
        mdd=mdd,
        n_months=n_months,
        n_accounts=len(ledgers),
        tax=TaxSummary(
            total_assessed_krw=total_assessed,
            total_unpaid_krw=total_unpaid,
            total_paid_krw=total_assessed - total_unpaid,
        ),
        accounts=account_summaries,
        monthly_values=combined_monthly if combined_monthly is not None else np.array([]),
    )


# ══════════════════════════════════════════════
# 실행 정책
# ══════════════════════════════════════════════

DUST_PCT = 0.001  # 포트폴리오 대비 0.1% 미만 거래 무시


def _execute_contribution_only(
    ledger: AccountLedger,
    target_weights: Dict[str, float],
    price_map: Dict[str, float],
    fx_rate: float,
) -> None:
    """C/O: 새 돈만 target weights 비례로 매수. 매도 없음."""
    cash = ledger.cash_usd
    if cash <= 1.0:
        return

    tw_sum = sum(target_weights.values())
    if tw_sum <= 0:
        return

    min_alloc = max(1.0, cash * DUST_PCT)
    for asset, tw in target_weights.items():
        alloc = cash * (tw / tw_sum)
        if alloc <= min_alloc:
            continue
        px = price_map.get(asset, 0.0)
        if px <= 0:
            continue
        buy_qty = alloc / px
        if buy_qty > 1e-12:
            ledger.buy(asset, buy_qty, px, fx_rate)


def _execute_full_rebalance(
    ledger: AccountLedger,
    target_weights: Dict[str, float],
    price_map: Dict[str, float],
    fx_rate: float,
) -> None:
    """FULL: 목표비중으로 매도 먼저 → 매수."""
    total_value = ledger.total_value_usd()
    if total_value <= 0:
        return

    # 현재 시가
    current_mv: Dict[str, float] = {}
    for asset, pos in ledger.positions.items():
        if pos.qty > 1e-12:
            px = price_map.get(asset, 0.0)
            current_mv[asset] = pos.qty * px

    # 목표 시가 (weights 정규화 — C/O와 동일하게 100% 투자)
    tw_sum = sum(target_weights.values())
    if tw_sum <= 0:
        return
    desired: Dict[str, float] = {a: total_value * (w / tw_sum) for a, w in target_weights.items()}

    # delta 계산
    all_assets = set(list(current_mv.keys()) + list(desired.keys()))
    deltas = {a: desired.get(a, 0.0) - current_mv.get(a, 0.0) for a in all_assets}

    # 1. 매도 먼저 (현금 확보)
    min_trade = max(1.0, total_value * DUST_PCT)
    for asset, delta in deltas.items():
        if delta < -min_trade:
            px = price_map.get(asset, 0.0)
            if px <= 0:
                continue
            pos = ledger.positions.get(asset)
            if pos is None or pos.qty < 1e-12:
                continue
            sell_qty = min(abs(delta) / px, pos.qty)
            if sell_qty > 1e-12:
                ledger.sell(asset, sell_qty, px, fx_rate)

    # 2. 매수 (available cash 범위 내)
    for asset, delta in deltas.items():
        if delta > min_trade:
            px = price_map.get(asset, 0.0)
            if px <= 0:
                continue
            buy_amount = min(delta, ledger.cash_usd)
            if buy_amount <= min_trade:
                continue
            buy_qty = buy_amount / px
            if buy_qty > 1e-12:
                ledger.buy(asset, buy_qty, px, fx_rate)
