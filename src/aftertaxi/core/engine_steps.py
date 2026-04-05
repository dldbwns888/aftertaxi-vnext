# -*- coding: utf-8 -*-
"""
engine_steps.py — 백테스트 엔진 빌딩 블록
==========================================
runner.py와 signal_runner.py가 공유하는 재사용 가능한 부품.

이전에 runner.py의 private 함수였으나,
signal_runner 등 다른 실행기가 의존하므로 public 모듈로 승격.

이 모듈의 함수는 public API — 시그니처 변경 시 signal_runner 영향 고려.
runner 내부 전용 로직은 runner.py에 남겨둔다.
"""
from __future__ import annotations

import bisect
import warnings
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import (
    AccountConfig, AccountSummary, AccountType, BacktestConfig,
    EngineResult, PersonSummary, RebalanceMode, TaxSummary,
)
from aftertaxi.core.ledger import AccountLedger, TaxSnapshot
from aftertaxi.core.settlement import settle_year_end
from aftertaxi.core.constants import QTY_EPSILON, AMOUNT_EPSILON_USD, DUST_PCT


# ══════════════════════════════════════════════
# 팩토리 / 인프라
# ══════════════════════════════════════════════

def create_ledgers(
    config: BacktestConfig,
    journal=None,
) -> Dict[str, AccountLedger]:
    """AccountConfig 리스트 → AccountLedger dict. 팩토리 함수.

    runner와 signal_runner가 공유. 계좌 생성 로직의 단일 소스.
    """
    ledgers: Dict[str, AccountLedger] = {}
    for ac in config.accounts:
        is_taxable = ac.account_type == AccountType.TAXABLE
        ledgers[ac.account_id] = AccountLedger(
            account_id=ac.account_id,
            account_type=ac.account_type.value,
            tax_rate=ac.tax_config.capital_gains_rate if is_taxable else 0.0,
            annual_exemption=ac.tax_config.annual_exemption if is_taxable else 0.0,
            isa_exempt_limit=ac.tax_config.isa_exempt_limit if ac.account_type == AccountType.ISA else 0.0,
            isa_excess_rate=ac.tax_config.capital_gains_rate if ac.account_type == AccountType.ISA else 0.0,
            transaction_cost_bps=ac.transaction_cost_bps,
            journal=journal,
            progressive_brackets=ac.tax_config.progressive_brackets if is_taxable else None,
            progressive_threshold=ac.tax_config.progressive_threshold if is_taxable else 20_000_000.0,
        )
    return ledgers


def build_fx_lookup(fx_rates: pd.Series) -> tuple:
    """환율 Series → (dict, sorted_dates) 사전 구축. O(n) 1회."""
    fx_dict = {ts: float(v) for ts, v in fx_rates.items()}
    sorted_dates = sorted(fx_dict.keys())
    return fx_dict, sorted_dates


def get_fx_rate(dt: pd.Timestamp, fx_lookup: tuple) -> float:
    """O(1) dict lookup + O(log n) bisect fallback."""
    fx_dict, sorted_dates = fx_lookup
    if dt in fx_dict:
        return fx_dict[dt]
    idx = bisect.bisect_right(sorted_dates, dt) - 1
    if idx >= 0:
        return fx_dict[sorted_dates[idx]]
    return fx_dict[sorted_dates[0]]


# ══════════════════════════════════════════════
# 세금 스냅샷 헬퍼
# ══════════════════════════════════════════════

def snapshot_tax(ledgers: Dict[str, AccountLedger]) -> TaxSnapshot:
    """전 계좌 세금 누적액 스냅샷. 정산 전후 비교용."""
    return TaxSnapshot(
        cgt_krw=sum(l.tax_snapshot().cgt_krw for l in ledgers.values()),
        dividend_tax_krw=sum(l.tax_snapshot().dividend_tax_krw for l in ledgers.values()),
        health_insurance_krw=sum(l.tax_snapshot().health_insurance_krw for l in ledgers.values()),
    )


def record_tax_delta(
    annual_tax_history: list,
    before: TaxSnapshot,
    after: TaxSnapshot,
    year: int,
) -> None:
    """정산 전후 차이를 annual_tax_history에 기록.

    같은 연도 entry가 이미 있으면 합산, 없으면 추가.
    """
    delta = after.diff(before, year)
    if delta.total_krw <= 0:
        return
    existing = [h for h in annual_tax_history if h["year"] == year]
    if existing:
        existing[0].cgt_krw += delta.cgt_krw
        existing[0].dividend_tax_krw += delta.dividend_tax_krw
        existing[0].health_insurance_krw += delta.health_insurance_krw
        existing[0].total_krw += delta.total_krw
    else:
        annual_tax_history.append(delta)


# ══════════════════════════════════════════════
# Step 함수 (월 루프 구성 요소)
# ══════════════════════════════════════════════

def step_mark_to_market(
    ledgers: Dict[str, AccountLedger],
    price_map: Dict[str, float],
) -> None:
    """1. 시가 반영."""
    for ledger in ledgers.values():
        ledger.mark_to_market(price_map)


def step_year_boundary(
    ledgers: Dict[str, AccountLedger],
    current_year: int,
    dt: pd.Timestamp,
    fx_rate: float,
    enable_health_insurance: bool,
) -> tuple:
    """2. 연도 전환 → 세금 정산. Returns: (갱신된 year, tax_snapshot or None)."""
    if current_year is not None and dt.year != current_year:
        before = snapshot_tax(ledgers)
        settle_year_end(ledgers, current_year, fx_rate,
                       enable_health_insurance=enable_health_insurance)
        after = snapshot_tax(ledgers)
        year_tax = after.diff(before, current_year)

        for ledger in ledgers.values():
            ledger.annual_contribution_usd = 0.0
            ledger.annual_contribution_krw = 0.0
        return dt.year, year_tax
    return current_year, None


def step_dividends(
    ledgers: Dict[str, AccountLedger],
    div_schedule,
    step: int,
    price_map: Dict[str, float],
    fx_rate: float,
) -> None:
    """2.5. 배당 처리."""
    if div_schedule is None or not div_schedule.is_dividend_month(step):
        return
    for ledger in ledgers.values():
        for asset in list(ledger.positions.keys()):
            event = div_schedule.create_event(asset, price_map.get(asset, 0))
            if event is not None:
                ledger.apply_dividend(
                    asset=event.asset,
                    gross_per_share=event.gross_per_share_usd,
                    withholding_rate=event.withholding_rate,
                    fx_rate=fx_rate,
                    reinvest=event.reinvest,
                    px_usd=price_map.get(asset, 0),
                )


def step_record(ledgers: Dict[str, AccountLedger]) -> None:
    """5. 월말 기록."""
    for ledger in ledgers.values():
        ledger.record_month()


# ══════════════════════════════════════════════
# 실행 정책 (리밸런싱)
# ══════════════════════════════════════════════

def drift_exceeds_threshold(
    ledger: AccountLedger,
    target_weights: Dict[str, float],
    price_map: Dict[str, float],
    threshold_pct: float,
) -> bool:
    """현재 비중이 목표에서 threshold 이상 벗어났는지 확인.

    BAND 모드에서 FULL 리밸 트리거 판단용.
    하나라도 초과 → True (전체 FULL 리밸).
    """
    total_value = ledger.total_value_usd()
    if total_value <= 0:
        return False

    for asset, target_w in target_weights.items():
        pos = ledger.positions.get(asset)
        px = price_map.get(asset, 0.0)
        actual_value = pos.qty * px if pos and px > 0 else 0.0
        actual_w = actual_value / total_value
        if abs(actual_w - target_w) > threshold_pct:
            return True

    return False


def execute_contribution_only(
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
        if buy_qty > QTY_EPSILON:
            ledger.buy(asset, buy_qty, px, fx_rate)


def execute_full_rebalance(
    ledger: AccountLedger,
    target_weights: Dict[str, float],
    price_map: Dict[str, float],
    fx_rate: float,
) -> None:
    """FULL: 목표비중으로 매도 먼저 → 매수."""
    total_value = ledger.total_value_usd()
    if total_value <= 0:
        return

    current_mv: Dict[str, float] = {}
    for asset, pos in ledger.positions.items():
        if pos.qty > QTY_EPSILON:
            px = price_map.get(asset, 0.0)
            current_mv[asset] = pos.qty * px

    tw_sum = sum(target_weights.values())
    if tw_sum <= 0:
        return
    desired: Dict[str, float] = {a: total_value * (w / tw_sum) for a, w in target_weights.items()}

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
            if pos is None or pos.qty < QTY_EPSILON:
                continue
            sell_qty = min(abs(delta) / px, pos.qty)
            if sell_qty > QTY_EPSILON:
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
            if buy_qty > QTY_EPSILON:
                ledger.buy(asset, buy_qty, px, fx_rate)


# ══════════════════════════════════════════════
# 결과 집계
# ══════════════════════════════════════════════

def aggregate(ledgers: Dict[str, AccountLedger], reporting_fx: float,
              annual_tax_history: list = None) -> EngineResult:
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
            account_id=s.account_id,
            account_type=s.account_type,
            gross_pv_usd=s.gross_pv_usd,
            invested_usd=s.invested_usd,
            tax_assessed_krw=s.tax_assessed_krw,
            tax_unpaid_krw=s.tax_unpaid_krw,
            mdd=s.mdd,
            n_months=s.n_months,
            transaction_cost_usd=s.transaction_cost_usd,
            dividend_gross_usd=s.dividend_gross_usd,
            dividend_withholding_usd=s.dividend_withholding_usd,
            capital_gains_tax_krw=s.capital_gains_tax_krw,
            dividend_tax_krw=s.dividend_tax_krw,
            health_insurance_krw=s.health_insurance_krw,
        ))
        total_pv += s.gross_pv_usd
        total_inv += s.invested_usd
        total_assessed += s.tax_assessed_krw
        total_unpaid += s.tax_unpaid_krw

        mv = s.monthly_values
        if combined_monthly is None:
            combined_monthly = mv.copy()
        else:
            if len(combined_monthly) != len(mv):
                warnings.warn(
                    f"계좌 간 monthly_values 길이 불일치: "
                    f"{len(combined_monthly)} vs {len(mv)}. "
                    f"짧은 쪽에 맞춰 잘림 — MDD 계산에 영향 가능.",
                    UserWarning, stacklevel=2,
                )
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

    person = PersonSummary(
        health_insurance_krw=sum(a.health_insurance_krw for a in account_summaries),
    )

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
        person=person,
        monthly_values=combined_monthly if combined_monthly is not None else np.array([]),
        annual_tax_history=annual_tax_history or [],
    )
