# -*- coding: utf-8 -*-
"""
loaders/eodhd.py — EODHD 데이터 로더
======================================
close(배당 미반영) / adjusted_close(배당 반영) 분리.
배당: ex-date, pay-date, record-date, per-share value.
무료: 1년 이력. 유료: 30년+.
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
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())


def load_prices_eodhd(
    tickers: List[str], api_token: str,
    start: str = "2006-01-01", end: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / f"prices_{'_'.join(sorted(tickers))}_{start}.parquet"
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        close_cols = [f"{t}_close" for t in tickers if f"{t}_close" in df.columns]
        adj_cols = [f"{t}_adj" for t in tickers if f"{t}_adj" in df.columns]
        if close_cols and adj_cols:
            close_df = df[close_cols].rename(columns={f"{t}_close": t for t in tickers})
            adj_df = df[adj_cols].rename(columns={f"{t}_adj": t for t in tickers})
            if end: close_df, adj_df = close_df.loc[:end], adj_df.loc[:end]
            return {"close": close_df, "adjusted_close": adj_df}

    frames_close, frames_adj = {}, {}
    for ticker in tickers:
        url = f"https://eodhd.com/api/eod/{ticker}.US?from={start}&period=m&api_token={api_token}&fmt=json"
        if end: url += f"&to={end}"
        data = _fetch_json(url)
        if not data: continue
        idx = pd.to_datetime([d["date"] for d in data])
        frames_close[ticker] = pd.Series([d["close"] for d in data], index=idx)
        frames_adj[ticker] = pd.Series([d["adjusted_close"] for d in data], index=idx)

    close_df, adj_df = pd.DataFrame(frames_close), pd.DataFrame(frames_adj)
    close_df.index = close_df.index + pd.offsets.MonthEnd(0)
    adj_df.index = adj_df.index + pd.offsets.MonthEnd(0)

    cache_dir.mkdir(parents=True, exist_ok=True)
    pd.concat([
        close_df.rename(columns={t: f"{t}_close" for t in tickers}),
        adj_df.rename(columns={t: f"{t}_adj" for t in tickers}),
    ], axis=1).to_parquet(cache_file)
    return {"close": close_df, "adjusted_close": adj_df}


@dataclass
class DividendRecord:
    ex_date: str
    pay_date: str
    record_date: str
    declaration_date: str
    value: float
    unadjusted_value: float
    period: str
    currency: str


def load_dividends_eodhd(
    tickers: List[str], api_token: str,
    start: str = "2006-01-01", end: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> Dict[str, List[DividendRecord]]:
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    result = {}
    for ticker in tickers:
        cache_file = cache_dir / f"div_{ticker}_{start}.json"
        if cache_file.exists():
            with open(cache_file) as f: raw = json.load(f)
        else:
            url = f"https://eodhd.com/api/div/{ticker}.US?from={start}&api_token={api_token}&fmt=json"
            if end: url += f"&to={end}"
            raw = _fetch_json(url)
            cache_dir.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w") as f: json.dump(raw, f)
        result[ticker] = [DividendRecord(
            ex_date=d.get("date",""), pay_date=d.get("paymentDate",""),
            record_date=d.get("recordDate",""), declaration_date=d.get("declarationDate",""),
            value=float(d.get("value",0)), unadjusted_value=float(d.get("unadjustedValue",0)),
            period=d.get("period",""), currency=d.get("currency","USD"),
        ) for d in raw]
    return result


def dividends_to_monthly(div_records, date_field="pay_date"):
    frames = {}
    for ticker, records in div_records.items():
        dates, values = [], []
        for r in records:
            dt_str = getattr(r, date_field, r.ex_date)
            if dt_str:
                dates.append(pd.Timestamp(dt_str))
                values.append(r.value)
        if dates:
            s = pd.Series(values, index=pd.DatetimeIndex(dates))
            s.index = s.index + pd.offsets.MonthEnd(0)
            frames[ticker] = s.groupby(s.index).sum()
    return pd.DataFrame(frames).fillna(0.0) if frames else pd.DataFrame()


def load_fx_eodhd(api_token, start="2006-01-01", end=None, pair="USDKRW", cache_dir=None):
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / f"fx_{pair}_{start}.parquet"
    if cache_file.exists():
        s = pd.read_parquet(cache_file).iloc[:, 0]
        return s.loc[:end] if end else s
    url = f"https://eodhd.com/api/eod/{pair}.FOREX?from={start}&period=m&api_token={api_token}&fmt=json"
    if end: url += f"&to={end}"
    data = _fetch_json(url)
    s = pd.Series([d["close"] for d in data], index=pd.to_datetime([d["date"] for d in data]), name=pair)
    s.index = s.index + pd.offsets.MonthEnd(0)
    cache_dir.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(cache_file)
    return s.loc[:end] if end else s
