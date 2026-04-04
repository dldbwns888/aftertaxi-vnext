# -*- coding: utf-8 -*-
"""test_sensitivity_and_watch.py — 민감도 + CLI 추가 테스트"""

import numpy as np
import pytest

from aftertaxi.workbench.sensitivity import run_sensitivity, SensitivityGrid


class TestSensitivity:

    def test_basic(self):
        grid = run_sensitivity(
            strategy_payload={"type": "spy_bnh"},
            growth_range=[0.0, 0.08],
            vol_range=[0.10, 0.20],
            n_months=60,
        )
        assert isinstance(grid, SensitivityGrid)
        assert grid.matrix.shape == (2, 2)

    def test_higher_growth_better(self):
        """성장률 높을수록 배수 높아야."""
        grid = run_sensitivity(
            strategy_payload={"type": "spy_bnh"},
            growth_range=[0.0, 0.12],
            vol_range=[0.16],
            n_months=60,
        )
        assert grid.matrix[0, 1] > grid.matrix[0, 0]

    def test_to_dataframe(self):
        grid = run_sensitivity(
            strategy_payload={"type": "spy_bnh"},
            growth_range=[0.04, 0.08],
            vol_range=[0.16, 0.30],
            n_months=24,
        )
        df = grid.to_dataframe()
        assert df.shape == (2, 2)
        assert "4%" in df.index[0] or "16%" in df.index[0]

    def test_summary_text(self):
        grid = run_sensitivity(
            strategy_payload={"type": "spy_bnh"},
            growth_range=[0.0, 0.08],
            vol_range=[0.10, 0.20],
            n_months=24,
        )
        text = grid.summary_text()
        assert "최고" in text
        assert "최저" in text

    def test_default_ranges(self):
        """기본 5×5 그리드."""
        grid = run_sensitivity(
            strategy_payload={"type": "spy_bnh"},
            n_months=24,
        )
        assert grid.matrix.shape == (5, 5)


class TestCLISensitivity:

    def test_sensitivity_flag(self, capsys, tmp_path):
        import json
        from aftertaxi.apps.cli import main

        config = tmp_path / "test.json"
        config.write_text(json.dumps({"strategy": {"type": "spy_bnh"}}))

        main([str(config), "--months", "24", "--sensitivity"])
        out = capsys.readouterr().out
        assert "민감도" in out or "최고" in out
