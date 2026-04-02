# -*- coding: utf-8 -*-
"""
core/allocation.py — 자금 배분층
================================
aftertaxi allocator.py에서 이식. vnext contracts에 맞게 재포장.

역할:
  1. 새 납입금을 어느 계좌에 먼저 넣을지 (priority)
  2. 전체 목표 비중 → 계좌별 목표 비중 분배 (allowed_assets 반영)
  3. 계좌별 annual_cap 확인
  4. 리밸런싱 주기 판정

설계 원칙:
  - allocator는 ledger를 직접 수정하지 않는다
  - "의도"만 반환하고, 실행은 runner가 한다
  - AccountConfig만 보고, ledger 상태는 ytd_contributions로 전달받는다
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional

from aftertaxi.core.contracts import AccountConfig, RebalanceMode


@dataclass
class AccountOrder:
    """계좌 1개에 대한 주문 의도.

    allocator가 생성하고, runner가 소비한다.
    """
    account_id: str
    deposit: float                         # 이번 달 입금액
    target_weights: Dict[str, float]       # 목표 비중 (이 계좌에 해당하는 자산만)
    rebalance_mode: RebalanceMode          # C/O or FULL
    should_rebalance: bool                 # 이번 달 리밸런싱 여부


class AllocationPlanner:
    """전략 비중 + 계좌 목록 → 계좌별 주문 의도.

    납입금은 priority 순으로 배분 (annual_cap 고려).
    목표 비중은 계좌의 allowed_assets로 필터링 후 재정규화.
    """

    def __init__(self, accounts: List[AccountConfig]):
        self.accounts = sorted(accounts, key=lambda a: a.priority)

    def plan(
        self,
        target_weights: Dict[str, float],
        total_contribution: float,
        month_index: int,
        rebalance_every: int = 1,
        ytd_contributions: Optional[Dict[str, float]] = None,
    ) -> List[AccountOrder]:
        """월간 배분 계획 생성.

        Parameters
        ----------
        target_weights : 전체 포트폴리오 목표 비중 (자산→비중)
        total_contribution : 이번 달 총 납입금
        month_index : 0-based 월 인덱스
        rebalance_every : 리밸런싱 주기 (월)
        ytd_contributions : 계좌별 연초 이후 누적 납입금
        """
        if ytd_contributions is None:
            ytd_contributions = {a.account_id: 0.0 for a in self.accounts}

        orders = []
        remaining = total_contribution

        for acct in self.accounts:
            # 1. 납입금 배분 (priority 순)
            monthly = min(acct.monthly_contribution, remaining)

            # annual_cap 확인
            if acct.annual_cap is not None:
                ytd = ytd_contributions.get(acct.account_id, 0.0)
                room = max(0.0, acct.annual_cap - ytd)
                monthly = min(monthly, room)

            remaining -= monthly

            # 2. 목표 비중: allowed_assets 필터 + 재정규화
            if acct.allowed_assets is not None:
                filtered = {
                    a: w for a, w in target_weights.items()
                    if a in acct.allowed_assets
                }
            else:
                filtered = dict(target_weights)

            w_sum = sum(filtered.values())
            if w_sum > 0:
                filtered = {a: w / w_sum for a, w in filtered.items()}

            # 3. 리밸런싱 여부
            should_rebal = (month_index % rebalance_every == 0)

            orders.append(AccountOrder(
                account_id=acct.account_id,
                deposit=monthly,
                target_weights=filtered,
                rebalance_mode=acct.rebalance_mode,
                should_rebalance=should_rebal,
            ))

        # 미배정 잔액 경고
        if remaining > 1.0:
            warnings.warn(
                f"AllocationPlanner: ${remaining:,.0f} 미배정 "
                f"(총 ${total_contribution:,.0f} 중). "
                f"annual_cap 또는 monthly_amount 제약.",
                stacklevel=2,
            )

        return orders
