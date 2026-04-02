# -*- coding: utf-8 -*-
"""
loaders/eodhd.py — EODHD 데이터 로더
======================================
EODHD API에서 가격, 배당, FX를 분리 로드.

EODHD의 장점 (aftertaxi 관점):
  - close = split-adjusted, 배당 미반영 (EXPLICIT_DIVIDENDS에 이상적)
  - adjusted_close = split + 배당 반영
  - 배당: ex-date, pay-date, record-date, per-share value 전부 분리
  - FX: USDKRW.FOREX 직접 지원
  - 공식 API (scraping 아님)

제한:
  - 무료: 1년 이력, 20 req/일
  - 유료($19.99/월~): 30년+ 이력
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import json
import pandas as pd
import urllib.request


_DEFAULT_CACHE_DIR = Path.home() / ".aftertaxi" / "cache" / "eodhd"


def _fetch_json(url: str) -> list:
    """URL에서 JSON 로드."""
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())


# ══════════════════════════════════════════════
# 가격 로더
# ══════════════════════════════════════════════

def load_prices_eodhd(
    tickers: List[str],
    api_token: str,
    start: str = "2006-01-01",
    end: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    """EODHD에서 월별 가격 로드.

    Returns
    -------
    dict with:
      "close": DataFrame (split-adjusted, 배당 미반영)
      "adjusted_close": DataFrame (split+배당 반영)
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / f"prices_{'_'.join(sorted(tickers))}_{start}.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        close_cols = [f"{t}_close" for t in tickers if f"{t}_close" in df.columns]
        adj_cols = [f"{t}_adj" for t in tickers if f"{t}_adj" in df.columns]
        if close_cols and adj_cols:
            close_df = df[close_cols].rename(columns={f"{t}_close": t for t in tickers})
            adj_df = df[adj_cols].rename(columns={f"{t}_adj": t for t in tickers})
            if end:
                close_df = close_df.loc[:end]
                adj_df = adj_df.loc[:end]
            return {"close": close_df, "adjusted_close": adj_df}

    frames_close = {}
    frames_adj = {}

    for ticker in tickers:
        symbol = f"{ticker}.US"
        url = (
            f"https://eodhd.com/api/eod/{symbol}"
            f"?from={start}&period=m&api_token={api_token}&fmt=json"
        )
        if end:
            url += f"&to={end}"

        data = _fetch_json(url)
        if not data:
            continue

        dates = [d["date"] for d in data]
        closes = [d["close"] for d in data]
        adj_closes = [d["adjusted_close"] for d in data]

        idx = pd.to_datetime(dates)
        frames_close[ticker] = pd.Series(closes, index=idx, name=ticker)
        frames_adj[ticker] = pd.Series(adj_closes, index=idx, name=ticker)

    close_df = pd.DataFrame(frames_close)
    adj_df = pd.DataFrame(frames_adj)

    # 월말 정렬
    close_df.index = close_df.index + pd.offsets.MonthEnd(0)
    adj_df.index = adj_df.index + pd.offsets.MonthEnd(0)

    # 캐시
    cache_dir.mkdir(parents=True, exist_ok=True)
    combined = pd.concat([
        close_df.rename(columns={t: f"{t}_close" for t in tickers}),
        adj_df.rename(columns={t: f"{t}_adj" for t in tickers}),
    ], axis=1)
    combined.to_parquet(cache_file)

    return {"close": close_df, "adjusted_close": adj_df}


# ══════════════════════════════════════════════
# 배당 로더
# ══════════════════════════════════════════════

@dataclass
class DividendRecord:
    """단일 배당 이벤트 (EODHD)."""
    ex_date: str
    pay_date: str
    record_date: str
    declaration_date: str
    value: float           # split-adjusted per share
    unadjusted_value: float
    period: str            # "Quarterly", "Monthly", etc.
    currency: str


def load_dividends_eodhd(
    tickers: List[str],
    api_token: str,
    start: str = "2006-01-01",
    end: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> Dict[str, List[DividendRecord]]:
    """EODHD에서 배당 이력 로드.

    Returns
    -------
    dict: {ticker: [DividendRecord, ...]}
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR

    result = {}
    for ticker in tickers:
        cache_file = cache_dir / f"div_{ticker}_{start}.json"

        if cache_file.exists():
            with open(cache_file) as f:
                raw = json.load(f)
        else:
            symbol = f"{ticker}.US"
            url = (
                f"https://eodhd.com/api/div/{symbol}"
                f"?from={start}&api_token={api_token}&fmt=json"
            )
            if end:
                url += f"&to={end}"
            raw = _fetch_json(url)

            cache_dir.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w") as f:
                json.dump(raw, f)

        records = []
        for d in raw:
            records.append(DividendRecord(
                ex_date=d.get("date", ""),
                pay_date=d.get("paymentDate", ""),
                record_date=d.get("recordDate", ""),
                declaration_date=d.get("declarationDate", ""),
                value=float(d.get("value", 0)),
                unadjusted_value=float(d.get("unadjustedValue", 0)),
                period=d.get("period", ""),
                currency=d.get("currency", "USD"),
            ))
        result[ticker] = records

    return result


def dividends_to_monthly(
    div_records: Dict[str, List[DividendRecord]],
    date_field: str = "pay_date",
) -> pd.DataFrame:
    """DividendRecord → 월별 배당 DataFrame.

    Parameters
    ----------
    date_field : "pay_date" | "ex_date" — 어느 날짜를 권위로 쓸지
    """
    frames = {}
    for ticker, records in div_records.items():
        dates = []
        values = []
        for r in records:
            dt_str = getattr(r, date_field, r.ex_date)
            if dt_str:
                dates.append(pd.Timestamp(dt_str))
                values.append(r.value)
        if dates:
            s = pd.Series(values, index=pd.DatetimeIndex(dates), name=ticker)
            s.index = s.index + pd.offsets.MonthEnd(0)
            frames[ticker] = s.groupby(s.index).sum()

    if frames:
        return pd.DataFrame(frames).fillna(0.0)
    return pd.DataFrame()


# ══════════════════════════════════════════════
# FX 로더
# ══════════════════════════════════════════════

def load_fx_eodhd(
    api_token: str,
    start: str = "2006-01-01",
    end: Optional[str] = None,
    pair: str = "USDKRW",
    cache_dir: Optional[Path] = None,
) -> pd.Series:
    """EODHD에서 월별 FX 환율 로드."""
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / f"fx_{pair}_{start}.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        s = df.iloc[:, 0]
        if end:
            s = s.loc[:end]
        return s

    symbol = f"{pair}.FOREX"
    url = (
        f"https://eodhd.com/api/eod/{symbol}"
        f"?from={start}&period=m&api_token={api_token}&fmt=json"
    )
    if end:
        url += f"&to={end}"

    data = _fetch_json(url)
    dates = [d["date"] for d in data]
    closes = [d["close"] for d in data]

    s = pd.Series(closes, index=pd.to_datetime(dates), name=pair)
    s.index = s.index + pd.offsets.MonthEnd(0)

    cache_dir.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(cache_file)

    if end:
        s = s.loc[:end]
    return s
