# -*- coding: utf-8 -*-
"""test_deposit_ownership.py — deposit 단일 소유권 검증 (PR A)"""

import pytest
from aftertaxi.core.ledger import AccountLedger


class TestDepositOwnership:

    def test_deposit_updates_usd_and_krw(self):
        """deposit 한 번에 USD + KRW 둘 다 갱신."""
        ledger = AccountLedger("t", "TAXABLE")
        ledger.deposit(100.0, 1300.0)

        assert ledger.cash_usd == 100.0
        assert ledger.annual_contribution_usd == 100.0
        assert ledger.annual_contribution_krw == 130_000.0

    def test_deposit_accumulates(self):
        """deposit 누적 — 서로 다른 환율."""
        ledger = AccountLedger("t", "TAXABLE")
        ledger.deposit(100.0, 1300.0)
        ledger.deposit(50.0, 1400.0)

        assert ledger.annual_contribution_usd == 150.0
        assert ledger.annual_contribution_krw == 130_000.0 + 70_000.0  # 200,000

    def test_deposit_zero_amount(self):
        """0원 입금 → 상태 안 바뀜."""
        ledger = AccountLedger("t", "TAXABLE")
        ledger.deposit(0.0, 1300.0)

        assert ledger.cash_usd == 0.0
        assert ledger.annual_contribution_usd == 0.0
        assert ledger.annual_contribution_krw == 0.0

    def test_deposit_invalid_fx_raises(self):
        """fx_rate <= 0이면 예외."""
        ledger = AccountLedger("t", "TAXABLE")
        with pytest.raises(ValueError, match="fx_rate"):
            ledger.deposit(100.0, 0.0)
        with pytest.raises(ValueError, match="fx_rate"):
            ledger.deposit(100.0, -1300.0)

    def test_no_external_krw_update_needed(self):
        """deposit 후 외부에서 annual_contribution_krw를 건드릴 필요 없음.

        이 테스트의 존재 이유: runner에서 deposit 다음 줄에
        별도 KRW 갱신이 있었던 버그를 재발 방지.
        """
        ledger = AccountLedger("t", "TAXABLE")
        ledger.deposit(1000.0, 1300.0)

        # deposit 한 번으로 KRW가 정확히 계산됨
        expected_krw = 1000.0 * 1300.0
        assert ledger.annual_contribution_krw == expected_krw
        # 외부에서 추가 갱신 불필요
