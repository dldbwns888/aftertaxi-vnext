# -*- coding: utf-8 -*-
"""
event_journal.py — 이벤트 로그
================================
엔진의 모든 상태 변경을 기록. attribution/디버깅/GUI 추적용.

설계 원칙:
  - opt-in: journal=None이면 기록 안 함 (성능 영향 0)
  - append-only: 기록된 이벤트는 수정/삭제 불가
  - 불변식 위반 감지는 여기서 안 함 (settlement/tax_engine 책임)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass(frozen=True)
class EventRecord:
    """단일 이벤트."""
    event_type: str         # buy / sell / deposit / tax_assessed / tax_paid /
                            # dividend / isa_settlement / rebalance / liquidate
    account_id: str
    amount_usd: float = 0.0
    amount_krw: float = 0.0
    fx_rate: float = 0.0
    asset: str = ""
    reason: str = ""        # 왜 이 이벤트가 발생했는지
    metadata: Dict[str, Any] = field(default_factory=dict)
    # metadata 예시:
    #   buy:  {"qty": 10.5, "px": 450.0, "fee_usd": 0.47}
    #   sell: {"qty": 5.2, "px": 460.0, "fee_usd": 0.24, "realized_krw": 12000}
    #   tax_assessed: {"tax_krw": 550000, "taxable_base": 2500000}


class EventJournal:
    """Append-only 이벤트 로그.

    사용법:
        journal = EventJournal()  # 또는 None으로 비활성화
        journal.record("buy", "taxable", amount_usd=1000, ...)
    """

    def __init__(self):
        self._events: List[EventRecord] = []

    def record(self, event_type: str, account_id: str, **kwargs) -> None:
        self._events.append(EventRecord(
            event_type=event_type,
            account_id=account_id,
            **kwargs,
        ))

    @property
    def events(self) -> List[EventRecord]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def filter_by_type(self, event_type: str) -> List[EventRecord]:
        return [e for e in self._events if e.event_type == event_type]

    def filter_by_account(self, account_id: str) -> List[EventRecord]:
        return [e for e in self._events if e.account_id == account_id]

    def total_by_type(self, event_type: str, field: str = "amount_usd") -> float:
        return sum(getattr(e, field, 0.0) for e in self._events if e.event_type == event_type)

    def total_fees(self) -> float:
        """전체 거래비용 합산."""
        total = 0.0
        for e in self._events:
            if e.event_type in ("buy", "sell"):
                total += e.metadata.get("fee_usd", 0.0)
        return total
