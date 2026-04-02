# -*- coding: utf-8 -*-
"""
loaders/market_db.py — 멀티소스 통합 데이터베이스
=================================================
모든 소스의 가격/배당/FX를 SQLite에 정규화 저장.
엔진은 DB만 보고, 소스를 몰라도 됨.

사용법:
  db = MarketDB()
  db.ingest_alphavantage(["SPY", "QQQ"], api_key)
  db.ingest_fred(api_key)

  prices = db.get_prices("SPY")                    # 기본 소스
  prices = db.get_prices("SPY", source="eodhd")    # 특정 소스
  db.compare_sources("SPY")                        # 교차 검증
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


_DEFAULT_DB_PATH = Path.home() / ".aftertaxi" / "market.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    close REAL,
    adjusted_close REAL,
    PRIMARY KEY (date, ticker, source)
);

CREATE TABLE IF NOT EXISTS dividends (
    ex_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    amount REAL NOT NULL,
    pay_date TEXT,
    record_date TEXT,
    declaration_date TEXT,
    currency TEXT DEFAULT 'USD',
    PRIMARY KEY (ex_date, ticker, source)
);

CREATE TABLE IF NOT EXISTS fx_rates (
    date TEXT NOT NULL,
    pair TEXT NOT NULL,
    source TEXT NOT NULL,
    rate REAL NOT NULL,
    PRIMARY KEY (date, pair, source)
);

CREATE TABLE IF NOT EXISTS load_log (
    source TEXT NOT NULL,
    ticker TEXT NOT NULL,
    data_type TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    n_rows INTEGER,
    PRIMARY KEY (source, ticker, data_type)
);
"""


class MarketDB:
    """멀티소스 시장 데이터 SQLite DB."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.executescript(_SCHEMA)

    def close(self):
        self.conn.close()

    # ══════════════════════════════════════════════
    # Ingest: 소스 → DB
    # ══════════════════════════════════════════════

    def ingest_alphavantage(self, tickers: List[str], api_key: str) -> int:
        """Alpha Vantage → DB. Returns: inserted rows."""
        from aftertaxi.loaders.alphavantage import load_prices_alphavantage
        import tempfile
        from pathlib import Path as P

        tmp = P(tempfile.mkdtemp())
        av = load_prices_alphavantage(tickers, api_key, cache_dir=tmp)

        n = 0
        for ticker in tickers:
            if ticker not in av["close"].columns:
                continue
            for dt in av["close"].index:
                date_str = dt.strftime("%Y-%m-%d")
                c = float(av["close"][ticker].loc[dt])
                a = float(av["adjusted_close"][ticker].loc[dt])
                d = float(av["dividends"][ticker].loc[dt])

                self.conn.execute(
                    "INSERT OR REPLACE INTO prices (date, ticker, source, close, adjusted_close) "
                    "VALUES (?, ?, 'alphavantage', ?, ?)",
                    (date_str, ticker, c, a),
                )
                if d > 0:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO dividends (ex_date, ticker, source, amount) "
                        "VALUES (?, ?, 'alphavantage', ?)",
                        (date_str, ticker, d),
                    )
                n += 1

            self._log("alphavantage", ticker, "prices", n,
                      av["close"].index[0], av["close"].index[-1])

        self.conn.commit()
        return n

    def ingest_fred(self, api_key: str, start: str = "2000-01-01") -> int:
        """FRED USDKRW → DB."""
        from aftertaxi.loaders.fred import load_fx_fred
        import tempfile
        from pathlib import Path as P

        fx = load_fx_fred(api_key, start=start, cache_dir=P(tempfile.mkdtemp()))
        n = 0
        for dt, rate in fx.items():
            self.conn.execute(
                "INSERT OR REPLACE INTO fx_rates (date, pair, source, rate) "
                "VALUES (?, 'USDKRW', 'fred', ?)",
                (dt.strftime("%Y-%m-%d"), float(rate)),
            )
            n += 1

        self._log("fred", "USDKRW", "fx", n, fx.index[0], fx.index[-1])
        self.conn.commit()
        return n

    def ingest_eodhd(self, tickers: List[str], api_token: str,
                      start: str = "2006-01-01", end: Optional[str] = None) -> int:
        """EODHD → DB."""
        from aftertaxi.loaders.eodhd import load_prices_eodhd, load_dividends_eodhd
        import tempfile
        from pathlib import Path as P

        tmp = P(tempfile.mkdtemp())
        prices = load_prices_eodhd(tickers, api_token, start=start, end=end, cache_dir=tmp)
        divs = load_dividends_eodhd(tickers, api_token, start=start, end=end, cache_dir=tmp)

        n = 0
        for ticker in tickers:
            if ticker in prices["close"].columns:
                for dt in prices["close"].index:
                    date_str = dt.strftime("%Y-%m-%d")
                    c = float(prices["close"][ticker].loc[dt])
                    a = float(prices["adjusted_close"][ticker].loc[dt])
                    self.conn.execute(
                        "INSERT OR REPLACE INTO prices (date, ticker, source, close, adjusted_close) "
                        "VALUES (?, ?, 'eodhd', ?, ?)",
                        (date_str, ticker, c, a),
                    )
                    n += 1

            for rec in divs.get(ticker, []):
                if rec.value > 0:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO dividends "
                        "(ex_date, ticker, source, amount, pay_date, record_date, declaration_date) "
                        "VALUES (?, ?, 'eodhd', ?, ?, ?, ?)",
                        (rec.ex_date, ticker, rec.value,
                         rec.pay_date, rec.record_date, rec.declaration_date),
                    )

        self.conn.commit()
        return n

    def ingest_yfinance(self, tickers: List[str], start: str = "2006-01-01") -> int:
        """yfinance → DB."""
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("yfinance 필요: pip install yfinance")

        n = 0
        for ticker in tickers:
            raw = yf.download(ticker, start=start, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                close = raw["Close"][ticker]
            else:
                close = raw["Close"]
            monthly = close.resample("ME").last().dropna()

            for dt, price in monthly.items():
                self.conn.execute(
                    "INSERT OR REPLACE INTO prices (date, ticker, source, close) "
                    "VALUES (?, ?, 'yfinance', ?)",
                    (dt.strftime("%Y-%m-%d"), ticker, float(price)),
                )
                n += 1

            # 배당
            tk = yf.Ticker(ticker)
            divs = tk.dividends
            if divs is not None and len(divs) > 0:
                if divs.index.tz is not None:
                    divs.index = divs.index.tz_localize(None)
                for dt, val in divs.items():
                    if val > 0:
                        self.conn.execute(
                            "INSERT OR REPLACE INTO dividends (ex_date, ticker, source, amount) "
                            "VALUES (?, ?, 'yfinance', ?)",
                            (dt.strftime("%Y-%m-%d"), ticker, float(val)),
                        )

            self._log("yfinance", ticker, "prices", n, monthly.index[0], monthly.index[-1])

        self.conn.commit()
        return n

    # ══════════════════════════════════════════════
    # Query: DB → Engine
    # ══════════════════════════════════════════════

    def get_prices(self, ticker: str, source: Optional[str] = None,
                   start: Optional[str] = None, end: Optional[str] = None,
                   ) -> pd.DataFrame:
        """가격 조회. source=None이면 우선순위: alphavantage > eodhd > yfinance."""
        if source is None:
            for s in ["alphavantage", "eodhd", "yfinance"]:
                df = self.get_prices(ticker, source=s, start=start, end=end)
                if len(df) > 0:
                    return df
            return pd.DataFrame()

        query = "SELECT date, close, adjusted_close FROM prices WHERE ticker=? AND source=?"
        params = [ticker, source]
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY date"

        df = pd.read_sql_query(query, self.conn, params=params, parse_dates=["date"])
        if len(df) > 0:
            df = df.set_index("date")
            df.index = df.index + pd.offsets.MonthEnd(0)
        return df

    def get_dividends(self, ticker: str, source: Optional[str] = None,
                      start: Optional[str] = None, end: Optional[str] = None,
                      ) -> pd.DataFrame:
        """배당 조회."""
        query = "SELECT ex_date, amount, pay_date, source FROM dividends WHERE ticker=?"
        params = [ticker]
        if source:
            query += " AND source=?"
            params.append(source)
        if start:
            query += " AND ex_date >= ?"
            params.append(start)
        if end:
            query += " AND ex_date <= ?"
            params.append(end)
        query += " ORDER BY ex_date"

        return pd.read_sql_query(query, self.conn, params=params, parse_dates=["ex_date"])

    def get_fx(self, pair: str = "USDKRW", source: Optional[str] = None,
               start: Optional[str] = None, end: Optional[str] = None,
               ) -> pd.Series:
        """FX 환율 조회."""
        source = source or "fred"
        query = "SELECT date, rate FROM fx_rates WHERE pair=? AND source=?"
        params = [pair, source]
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY date"

        df = pd.read_sql_query(query, self.conn, params=params, parse_dates=["date"])
        if len(df) == 0:
            return pd.Series(dtype=float)
        s = df.set_index("date")["rate"]
        s.index = s.index + pd.offsets.MonthEnd(0)
        s.name = pair
        return s

    def sources_for(self, ticker: str) -> List[str]:
        """해당 티커를 가진 소스 목록."""
        cur = self.conn.execute(
            "SELECT DISTINCT source FROM prices WHERE ticker=?", (ticker,))
        return [row[0] for row in cur.fetchall()]

    def compare_sources(self, ticker: str, start: Optional[str] = None,
                        end: Optional[str] = None) -> pd.DataFrame:
        """소스별 가격 교차 비교."""
        sources = self.sources_for(ticker)
        frames = {}
        for s in sources:
            df = self.get_prices(ticker, source=s, start=start, end=end)
            if len(df) > 0 and "close" in df.columns:
                frames[s] = df["close"]
        if frames:
            return pd.DataFrame(frames)
        return pd.DataFrame()

    def summary(self) -> Dict:
        """DB 요약 통계."""
        cur = self.conn.execute("SELECT source, ticker, COUNT(*) FROM prices GROUP BY source, ticker")
        prices = {}
        for source, ticker, count in cur.fetchall():
            prices.setdefault(source, {})[ticker] = count

        cur = self.conn.execute("SELECT source, COUNT(*) FROM fx_rates GROUP BY source")
        fx = {row[0]: row[1] for row in cur.fetchall()}

        cur = self.conn.execute("SELECT source, ticker, COUNT(*) FROM dividends GROUP BY source, ticker")
        divs = {}
        for source, ticker, count in cur.fetchall():
            divs.setdefault(source, {})[ticker] = count

        return {"prices": prices, "dividends": divs, "fx_rates": fx}

    # ══════════════════════════════════════════════
    # Internal
    # ══════════════════════════════════════════════

    def _log(self, source, ticker, data_type, n_rows, start_dt=None, end_dt=None):
        start_str = start_dt.strftime("%Y-%m-%d") if hasattr(start_dt, 'strftime') else str(start_dt)
        end_str = end_dt.strftime("%Y-%m-%d") if hasattr(end_dt, 'strftime') else str(end_dt)
        self.conn.execute(
            "INSERT OR REPLACE INTO load_log (source, ticker, data_type, loaded_at, start_date, end_date, n_rows) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source, ticker, data_type, datetime.now().isoformat(), start_str, end_str, n_rows),
        )
