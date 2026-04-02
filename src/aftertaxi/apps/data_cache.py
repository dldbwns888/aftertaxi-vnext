# -*- coding: utf-8 -*-
"""
apps/data_cache.py — 데이터 캐시
=================================
yfinance 등 외부 소스의 반복 다운로드 방지.
로컬 SQLite에 캐시. 키: (source, ticker, interval).

사용법:
  from aftertaxi.apps.data_cache import DataCache

  cache = DataCache()  # ~/.aftertaxi/cache.db
  cache.put("SPY", "yfinance", prices_df)
  df = cache.get("SPY", "yfinance")  # 캐시 히트
  df = cache.get("SPY", "yfinance", max_age_hours=24)  # stale 체크

data_provider와 통합:
  data = load_market_data(assets, source="yfinance", cache=True)
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

import pandas as pd


_DEFAULT_DB = Path.home() / ".aftertaxi" / "cache.db"


class DataCache:
    """로컬 SQLite 가격/FX 캐시."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_tables()

    def _init_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS price_cache (
                ticker TEXT NOT NULL,
                source TEXT NOT NULL,
                date TEXT NOT NULL,
                close REAL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (ticker, source, date)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS fx_cache (
                pair TEXT NOT NULL,
                source TEXT NOT NULL,
                date TEXT NOT NULL,
                rate REAL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (pair, source, date)
            )
        """)
        self._conn.commit()

    def put_prices(self, ticker: str, source: str, df: pd.DataFrame) -> int:
        """가격 DataFrame 저장. 컬럼: date index, close(또는 ticker명)."""
        now = time.time()
        rows = []
        for date, row in df.iterrows():
            val = row.iloc[0] if hasattr(row, 'iloc') else row
            rows.append((ticker, source, str(date.date()), float(val), now))

        self._conn.executemany(
            "INSERT OR REPLACE INTO price_cache VALUES (?,?,?,?,?)", rows)
        self._conn.commit()
        return len(rows)

    def get_prices(
        self, ticker: str, source: str,
        max_age_hours: Optional[float] = None,
    ) -> Optional[pd.DataFrame]:
        """캐시에서 가격 조회. None이면 캐시 미스."""
        query = "SELECT date, close, updated_at FROM price_cache WHERE ticker=? AND source=?"
        params = [ticker, source]

        rows = self._conn.execute(query, params).fetchall()
        if not rows:
            return None

        # stale 체크
        if max_age_hours is not None:
            latest_update = max(r[2] for r in rows)
            age_hours = (time.time() - latest_update) / 3600
            if age_hours > max_age_hours:
                return None  # stale

        df = pd.DataFrame(rows, columns=["date", "close", "updated_at"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df[["close"]].rename(columns={"close": ticker})

    def put_fx(self, pair: str, source: str, series: pd.Series) -> int:
        """FX Series 저장."""
        now = time.time()
        rows = [(pair, source, str(d.date()), float(v), now)
                for d, v in series.items() if pd.notna(v)]
        self._conn.executemany(
            "INSERT OR REPLACE INTO fx_cache VALUES (?,?,?,?,?)", rows)
        self._conn.commit()
        return len(rows)

    def get_fx(
        self, pair: str, source: str,
        max_age_hours: Optional[float] = None,
    ) -> Optional[pd.Series]:
        """캐시에서 FX 조회."""
        rows = self._conn.execute(
            "SELECT date, rate, updated_at FROM fx_cache WHERE pair=? AND source=?",
            [pair, source],
        ).fetchall()

        if not rows:
            return None

        if max_age_hours is not None:
            latest_update = max(r[2] for r in rows)
            if (time.time() - latest_update) / 3600 > max_age_hours:
                return None

        df = pd.DataFrame(rows, columns=["date", "rate", "updated_at"])
        df["date"] = pd.to_datetime(df["date"])
        s = df.set_index("date")["rate"].sort_index()
        s.name = pair
        return s

    def clear(self, ticker: Optional[str] = None, source: Optional[str] = None):
        """캐시 삭제."""
        if ticker and source:
            self._conn.execute(
                "DELETE FROM price_cache WHERE ticker=? AND source=?", [ticker, source])
            self._conn.execute(
                "DELETE FROM fx_cache WHERE pair=? AND source=?", [ticker, source])
        elif ticker:
            self._conn.execute("DELETE FROM price_cache WHERE ticker=?", [ticker])
        elif source:
            self._conn.execute("DELETE FROM price_cache WHERE source=?", [source])
            self._conn.execute("DELETE FROM fx_cache WHERE source=?", [source])
        else:
            self._conn.execute("DELETE FROM price_cache")
            self._conn.execute("DELETE FROM fx_cache")
        self._conn.commit()

    def summary(self) -> dict:
        """캐시 현황."""
        n_prices = self._conn.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
        n_fx = self._conn.execute("SELECT COUNT(*) FROM fx_cache").fetchone()[0]
        tickers = [r[0] for r in self._conn.execute(
            "SELECT DISTINCT ticker FROM price_cache").fetchall()]
        return {"n_prices": n_prices, "n_fx": n_fx, "tickers": tickers}

    def close(self):
        self._conn.close()
