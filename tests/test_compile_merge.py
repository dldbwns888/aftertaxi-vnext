# -*- coding: utf-8 -*-
"""test_compile_merge.py — compile merge 규칙 검증 (PR B)"""

import pytest
from aftertaxi.strategies.compile import compile_account, _merge_tax_config
from aftertaxi.core.contracts import TaxConfig, TAXABLE_TAX, KOREA_PROGRESSIVE_BRACKETS


class TestMergeTaxConfig:

    def test_no_override(self):
        """override 없으면 preset 그대로."""
        result = _merge_tax_config(TAXABLE_TAX, {})
        assert result.capital_gains_rate == 0.22
        assert result.progressive_brackets is None

    def test_progressive_shortcut(self):
        """progressive: true → KOREA_PROGRESSIVE_BRACKETS 주입."""
        result = _merge_tax_config(TAXABLE_TAX, {"progressive": True})
        assert result.progressive_brackets == KOREA_PROGRESSIVE_BRACKETS
        assert result.capital_gains_rate == 0.22  # 나머지 유지

    def test_partial_override(self):
        """일부만 override하면 나머지는 preset 유지."""
        result = _merge_tax_config(TAXABLE_TAX, {"annual_exemption": 5_000_000})
        assert result.annual_exemption == 5_000_000
        assert result.capital_gains_rate == 0.22  # 유지

    def test_unknown_field_raises(self):
        """오타/잘못된 필드명 → 예외."""
        with pytest.raises(ValueError, match="Unknown"):
            _merge_tax_config(TAXABLE_TAX, {"progerssive": True})  # 오타

    def test_full_override(self):
        """전부 override 가능."""
        result = _merge_tax_config(TAXABLE_TAX, {
            "capital_gains_rate": 0.30,
            "annual_exemption": 0,
            "progressive": True,
            "progressive_threshold": 30_000_000,
        })
        assert result.capital_gains_rate == 0.30
        assert result.annual_exemption == 0
        assert result.progressive_brackets == KOREA_PROGRESSIVE_BRACKETS
        assert result.progressive_threshold == 30_000_000


class TestCompileAccountMerge:

    def test_preset_only(self):
        """type만 주면 preset 기본값."""
        cfg = compile_account({"type": "TAXABLE"})
        assert cfg.tax_config.capital_gains_rate == 0.22
        assert cfg.tax_config.progressive_brackets is None

    def test_progressive_via_top_level(self):
        """하위 호환: top-level progressive: true."""
        cfg = compile_account({"type": "TAXABLE", "progressive": True})
        assert cfg.tax_config.progressive_brackets is not None

    def test_progressive_via_tax_dict(self):
        """새 방식: tax dict으로 progressive."""
        cfg = compile_account({
            "type": "TAXABLE",
            "tax": {"progressive": True},
        })
        assert cfg.tax_config.progressive_brackets is not None

    def test_tax_override_custom_rate(self):
        """세율 커스텀."""
        cfg = compile_account({
            "type": "TAXABLE",
            "tax": {"capital_gains_rate": 0.30},
        })
        assert cfg.tax_config.capital_gains_rate == 0.30

    def test_isa_preset_untouched(self):
        """ISA는 preset 그대로 (rate=0)."""
        cfg = compile_account({"type": "ISA"})
        assert cfg.tax_config.capital_gains_rate == 0.0

    def test_progressive_regression(self):
        """과거 버그 재발 방지: progressive가 compile 통과 시 사라지면 안 됨."""
        cfg = compile_account({
            "type": "TAXABLE",
            "monthly_contribution": 1000,
            "progressive": True,
        })
        assert cfg.tax_config.progressive_brackets == KOREA_PROGRESSIVE_BRACKETS
        assert cfg.tax_config.progressive_threshold == 20_000_000
