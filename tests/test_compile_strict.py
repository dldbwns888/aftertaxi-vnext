# -*- coding: utf-8 -*-
"""test_compile_strict.py — strict compile mode 테스트"""

import pytest
from aftertaxi.strategies.compile import compile_backtest


class TestStrictMode:
    """strict=True는 누락 필드 시 에러."""

    def test_missing_monthly_raises(self):
        """monthly_contribution 누락 → ValueError."""
        with pytest.raises(ValueError, match="monthly_contribution 누락"):
            compile_backtest(
                {"strategy": {"type": "spy_bnh"}, "accounts": [{"type": "TAXABLE"}]},
                strict=True,
            )

    def test_empty_accounts_raises(self):
        """accounts 비어있으면 → ValueError."""
        with pytest.raises(ValueError, match="accounts 목록이 비어"):
            compile_backtest(
                {"strategy": {"type": "spy_bnh"}, "accounts": []},
                strict=True,
            )

    def test_explicit_monthly_passes(self):
        """monthly 명시하면 strict에서도 통과."""
        cfg = compile_backtest(
            {"strategy": {"type": "spy_bnh"},
             "accounts": [{"type": "TAXABLE", "monthly_contribution": 500}]},
            strict=True,
        )
        assert cfg.accounts[0].monthly_contribution == 500

    def test_lenient_default_works(self):
        """strict=False는 기존 동작 유지."""
        cfg = compile_backtest(
            {"strategy": {"type": "spy_bnh"}, "accounts": [{"type": "TAXABLE"}]},
            strict=False,
        )
        assert cfg.accounts[0].monthly_contribution == 1000  # 기본값
