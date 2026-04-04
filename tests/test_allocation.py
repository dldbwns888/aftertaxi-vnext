# -*- coding: utf-8 -*-
"""
test_allocation.py — AllocationPlanner 단위 테스트
===================================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import warnings
import pytest

from aftertaxi.core.contracts import AccountConfig, AccountType, RebalanceMode
from aftertaxi.core.allocation import AllocationPlanner, AccountOrder


class TestAllocationPlanner:

    def test_single_account(self):
        """단일 계좌 → 전액 배분."""
        accts = [AccountConfig("t", AccountType.TAXABLE, 1000.0)]
        planner = AllocationPlanner(accts)
        orders = planner.plan({"SPY": 0.6, "QQQ": 0.4}, 1000.0, 0)
        assert len(orders) == 1
        assert orders[0].deposit == 1000.0
        assert abs(orders[0].target_weights["SPY"] - 0.6) < 1e-6

    def test_priority_ordering(self):
        """priority 낮은 계좌에 먼저 배분."""
        accts = [
            AccountConfig("isa", AccountType.ISA, 500.0, priority=0),
            AccountConfig("tax", AccountType.TAXABLE, 500.0, priority=1),
        ]
        planner = AllocationPlanner(accts)
        orders = planner.plan({"SPY": 1.0}, 800.0, 0)

        # ISA(priority=0)가 먼저 → $500
        # TAXABLE(priority=1) → 나머지 $300
        assert orders[0].account_id == "isa"
        assert orders[0].deposit == 500.0
        assert orders[1].account_id == "tax"
        assert orders[1].deposit == 300.0

    def test_annual_cap(self):
        """annual_cap(KRW) 초과분은 다음 계좌로.

        ISA cap = ₩2,600,000. ytd = ₩1,950,000. room = ₩650,000.
        fx=1300이면 room_usd = $500.
        """
        accts = [
            AccountConfig("isa", AccountType.ISA, 1000.0,
                          annual_cap=2_600_000.0, priority=0),  # KRW
            AccountConfig("tax", AccountType.TAXABLE, 1000.0, priority=1),
        ]
        planner = AllocationPlanner(accts)
        orders = planner.plan(
            {"SPY": 1.0}, 2000.0, 0,
            ytd_contributions={"isa": 1_950_000.0, "tax": 0.0},  # KRW
            fx_rate=1300.0,
        )
        assert abs(orders[0].deposit - 500.0) < 1.0   # ISA: room ₩650K / 1300 = $500
        assert abs(orders[1].deposit - 1000.0) < 1.0   # TAXABLE: 나머지

    def test_allowed_assets_filter(self):
        """allowed_assets가 있으면 해당 자산만."""
        accts = [AccountConfig("t", AccountType.TAXABLE, 1000.0,
                               allowed_assets={"SPY"})]
        planner = AllocationPlanner(accts)
        orders = planner.plan({"SPY": 0.5, "QQQ": 0.5}, 1000.0, 0)

        # QQQ 제외, SPY만 → 재정규화되어 1.0
        assert "QQQ" not in orders[0].target_weights
        assert abs(orders[0].target_weights["SPY"] - 1.0) < 1e-6

    def test_renormalization(self):
        """필터 후 비중 합이 1.0으로 재정규화."""
        accts = [AccountConfig("t", AccountType.TAXABLE, 1000.0,
                               allowed_assets={"SPY", "VOO"})]
        planner = AllocationPlanner(accts)
        orders = planner.plan({"SPY": 0.3, "VOO": 0.3, "QQQ": 0.4}, 1000.0, 0)

        w = orders[0].target_weights
        assert abs(sum(w.values()) - 1.0) < 1e-6
        assert "QQQ" not in w

    def test_unallocated_warning(self):
        """cap에 막혀 배분 못 한 돈이 있으면 경고."""
        # monthly=500, cap=500 → 1회 납입 후 cap 소진
        # total=2000 → 500만 배정, 1500 미배정
        accts = [AccountConfig("isa", AccountType.ISA, 500.0,
                               annual_cap=500.0)]
        planner = AllocationPlanner(accts)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # ytd=500이면 이미 cap 소진 → monthly 전액 미배정
            orders = planner.plan({"SPY": 1.0}, 2000.0, 0,
                                  ytd_contributions={"isa": 500.0})
            assert len(w) == 1
            assert "미배정" in str(w[0].message)

    def test_rebalance_flag(self):
        """리밸런싱 주기에 맞게 should_rebalance."""
        accts = [AccountConfig("t", AccountType.TAXABLE, 1000.0,
                               rebalance_mode=RebalanceMode.FULL)]
        planner = AllocationPlanner(accts)

        o0 = planner.plan({"SPY": 1.0}, 1000.0, 0, rebalance_every=3)
        assert o0[0].should_rebalance is True  # step 0

        o1 = planner.plan({"SPY": 1.0}, 1000.0, 1, rebalance_every=3)
        assert o1[0].should_rebalance is False  # step 1

        o3 = planner.plan({"SPY": 1.0}, 1000.0, 3, rebalance_every=3)
        assert o3[0].should_rebalance is True  # step 3

    def test_returns_account_order(self):
        """반환 타입이 AccountOrder."""
        accts = [AccountConfig("t", AccountType.TAXABLE, 1000.0)]
        planner = AllocationPlanner(accts)
        orders = planner.plan({"SPY": 1.0}, 1000.0, 0)
        assert isinstance(orders[0], AccountOrder)
        assert orders[0].rebalance_mode == RebalanceMode.CONTRIBUTION_ONLY
