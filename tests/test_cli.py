# -*- coding: utf-8 -*-
"""test_cli.py — CLI runner 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json
import tempfile
import pytest

from aftertaxi.apps.cli import main


class TestCLI:

    def _write_config(self, payload):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(payload, f)
        f.close()
        return f.name

    def test_basic_run(self, capsys):
        path = self._write_config({"strategy": {"type": "spy_bnh"}})
        result = main([path, "--months", "24"])
        assert result.n_months == 24
        out = capsys.readouterr().out
        assert "세후 DCA 백테스트 결과" in out

    def test_json_output(self, capsys):
        path = self._write_config({"strategy": {"type": "q60s40"}})
        main([path, "--months", "12", "--json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "Q60S40_CO"

    def test_multi_account(self, capsys):
        path = self._write_config({
            "strategy": {"type": "spy_bnh"},
            "accounts": [
                {"type": "ISA", "monthly_contribution": 500},
                {"type": "TAXABLE", "monthly_contribution": 500},
            ],
        })
        result = main([path, "--months", "24"])
        assert result.n_accounts == 2
        out = capsys.readouterr().out
        assert "계좌별" in out

    def test_custom_params(self, capsys):
        path = self._write_config({"strategy": {"type": "spy_bnh"}})
        result = main([path, "--months", "60", "--fx", "1400", "--growth", "0.10"])
        assert result.n_months == 60
        assert result.reporting_fx_rate == 1400.0

    def test_seed_reproducible(self):
        path = self._write_config({"strategy": {"type": "spy_bnh"}})
        r1 = main([path, "--months", "24", "--seed", "99"])
        r2 = main([path, "--months", "24", "--seed", "99"])
        assert r1.gross_pv_usd == r2.gross_pv_usd

    def test_lane_d(self, capsys):
        path = self._write_config({"strategy": {"type": "spy_bnh"}})
        result = main([path, "--months", "24", "--lane-d", "--lane-d-paths", "3", "--lane-d-years", "5"])
        out = capsys.readouterr().out
        assert "Lane D" in out
        assert "생존률" in out
