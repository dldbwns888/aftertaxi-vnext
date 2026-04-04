# -*- coding: utf-8 -*-
"""
apps/memory.py — 실험 기록 (Research Memory)
============================================
실행 기록이 쌓여야 연구가 된다.

MVP 필드: run_id, timestamp, config_hash, result_summary, name
나머지는 쓰면서 붙인다.

사용법:
  memory = ResearchMemory()
  run_id = memory.record(config_json, result_summary)
  runs = memory.list_runs(limit=10)
  run = memory.get(run_id)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


_DEFAULT_DB = Path.home() / ".aftertaxi" / "memory.db"


@dataclass
class RunRecord:
    """실행 기록 한 건."""
    run_id: str
    timestamp: str
    name: str
    config_hash: str
    config_json: str
    # 결과 요약
    gross_pv_usd: float = 0.0
    net_pv_krw: float = 0.0
    tax_assessed_krw: float = 0.0
    mdd: float = 0.0
    n_months: int = 0
    # 메타
    tags: str = ""              # 쉼표 구분
    advisor_summary: str = ""
    data_fingerprint: str = ""  # sha256[:12] — 같은 데이터면 같은 값
    data_source: str = ""       # "synthetic" | "yfinance" | ...


class ResearchMemory:
    """SQLite 기반 실험 기록."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    config_hash TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    gross_pv_usd REAL DEFAULT 0,
                    net_pv_krw REAL DEFAULT 0,
                    tax_assessed_krw REAL DEFAULT 0,
                    mdd REAL DEFAULT 0,
                    n_months INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '',
                    advisor_summary TEXT DEFAULT '',
                    data_fingerprint TEXT DEFAULT '',
                    data_source TEXT DEFAULT ''
                )
            """)
            # 기존 DB 마이그레이션
            try:
                conn.execute("ALTER TABLE runs ADD COLUMN data_fingerprint TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # 이미 있음
            try:
                conn.execute("ALTER TABLE runs ADD COLUMN data_source TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

    def record(
        self,
        config_json: str,
        gross_pv_usd: float = 0.0,
        net_pv_krw: float = 0.0,
        tax_assessed_krw: float = 0.0,
        mdd: float = 0.0,
        n_months: int = 0,
        name: str = "",
        tags: str = "",
        advisor_summary: str = "",
        data_fingerprint: str = "",
        data_source: str = "",
    ) -> str:
        """실행 기록. Returns: run_id."""
        run_id = uuid.uuid4().hex[:8]
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        config_hash = hashlib.sha256(config_json.encode()).hexdigest()[:12]

        if not name:
            name = f"run-{run_id}"

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, ts, name, config_hash, config_json,
                 gross_pv_usd, net_pv_krw, tax_assessed_krw, mdd, n_months,
                 tags, advisor_summary, data_fingerprint, data_source),
            )
        return run_id

    def list_runs(self, limit: int = 20) -> List[RunRecord]:
        """최근 실행 목록."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [RunRecord(**dict(r)) for r in rows]

    def get(self, run_id: str) -> Optional[RunRecord]:
        """run_id로 조회."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return RunRecord(**dict(row)) if row else None

    def delete(self, run_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return cursor.rowcount > 0

    def clear(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM runs")
