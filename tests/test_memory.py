# -*- coding: utf-8 -*-
"""test_memory.py — 실험 기록 테스트"""

import pytest
from pathlib import Path
from aftertaxi.apps.memory import ResearchMemory, RunRecord


@pytest.fixture
def memory(tmp_path):
    return ResearchMemory(db_path=tmp_path / "test.db")


class TestMemory:

    def test_record_and_get(self, memory):
        run_id = memory.record('{"strategy":"spy"}', gross_pv_usd=100.0, name="test1")
        assert len(run_id) == 8
        rec = memory.get(run_id)
        assert rec is not None
        assert rec.name == "test1"
        assert rec.gross_pv_usd == 100.0

    def test_list_runs(self, memory):
        memory.record('{"a":1}', name="first")
        memory.record('{"a":2}', name="second")
        memory.record('{"a":3}', name="third")
        runs = memory.list_runs(limit=10)
        assert len(runs) == 3
        # limit 동작
        runs2 = memory.list_runs(limit=2)
        assert len(runs2) == 2

    def test_auto_name(self, memory):
        run_id = memory.record('{}')
        rec = memory.get(run_id)
        assert rec.name.startswith("run-")

    def test_config_hash(self, memory):
        id1 = memory.record('{"same": true}')
        id2 = memory.record('{"same": true}')
        r1 = memory.get(id1)
        r2 = memory.get(id2)
        assert r1.config_hash == r2.config_hash

    def test_delete(self, memory):
        run_id = memory.record('{}')
        assert memory.delete(run_id)
        assert memory.get(run_id) is None

    def test_clear(self, memory):
        memory.record('{}')
        memory.record('{}')
        memory.clear()
        assert len(memory.list_runs()) == 0

    def test_get_nonexistent(self, memory):
        assert memory.get("nonexistent") is None

    def test_tags(self, memory):
        run_id = memory.record('{}', tags="q60s40,progressive")
        rec = memory.get(run_id)
        assert "progressive" in rec.tags

    def test_advisor_summary(self, memory):
        run_id = memory.record('{}', advisor_summary="HIGH_TAX_DRAG: ISA 추가 권장")
        rec = memory.get(run_id)
        assert "ISA" in rec.advisor_summary
