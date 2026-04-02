# -*- coding: utf-8 -*-
"""
loaders/fmp.py — Financial Modeling Prep 데이터 로더
====================================================
close(배당 미반영) + adjClose(배당 반영) + dividends 완전 분리.
무료 tier: 250 req/일, 30년+ 이력.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import json
import pandas as pd
import urllib.request


_BASE = "https://financialmodelingprep.com/stable"


def _fetch_json(url: str):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())


def load_prices_fmp(
    tickers: List[str],
    api_key: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """FMP에서 close(배당 미반영) + adjusted_close(배당 반영) 분리 로드.

    두 개의 엔드포인트를 조합:
      /historical-price-eod/full → close
      /historical-price-eod/dividend-adjusted → adjClose
    """
    frames_close = {}
    frames_adj = {}

    for ticker in tickers:
        # close (배당 미반영)
        url = f"{_BASE}/historical-price-eod/full?symbol={ticker}&apikey={api_key}"
        if start: url += f"&from={start}"
        if end: url += f"&to={end}"
        data = _fetch_json(url)

        if data:
            dates = [d["date"] for d in data]
            closes = [d["close"] for d in data]
            idx = pd.to_datetime(dates)
            frames_close[ticker] = pd.Series(closes, index=idx, name=ticker).sort_index()

        # adjusted close (배당 반영)
        url_adj = f"{_BASE}/historical-price-eod/dividend-adjusted?symbol={ticker}&apikey={api_key}"
        if start: url_adj += f"&from={start}"
        if end: url_adj += f"&to={end}"
        data_adj = _fetch_json(url_adj)

        if data_adj:
            dates_a = [d["date"] for d in data_adj]
            adj_closes = [d["adjClose"] for d in data_adj]
            idx_a = pd.to_datetime(dates_a)
            frames_adj[ticker] = pd.Series(adj_closes, index=idx_a, name=ticker).sort_index()

    close_df = pd.DataFrame(frames_close)
    adj_df = pd.DataFrame(frames_adj)

    # 일별 → 월말
    if len(close_df) > 0:
        close_df = close_df.resample("ME").last().dropna(how="all")
    if len(adj_df) > 0:
        adj_df = adj_df.resample("ME").last().dropna(how="all")

    return {"close": close_df, "adjusted_close": adj_df}


def load_dividends_fmp(
    tickers: List[str],
    api_key: str,
) -> Dict[str, pd.DataFrame]:
    """FMP에서 배당 이력 로드.

    Returns
    -------
    dict: {ticker: DataFrame with columns [date, amount, pay_date, ...]}
    """
    result = {}
    for ticker in tickers:
        url = f"{_BASE}/dividends?symbol={ticker}&apikey={api_key}"
        data = _fetch_json(url)

        if not data:
            result[ticker] = pd.DataFrame()
            continue

        records = []
        for d in data:
            records.append({
                "ex_date": d.get("date", ""),
                "amount": float(d.get("dividend", 0)),
                "adj_amount": float(d.get("adjDividend", 0)),
                "pay_date": d.get("paymentDate", ""),
                "record_date": d.get("recordDate", ""),
                "declaration_date": d.get("declarationDate", ""),
                "frequency": d.get("frequency", ""),
            })

        df = pd.DataFrame(records)
        df["ex_date"] = pd.to_datetime(df["ex_date"])
        df = df.sort_values("ex_date")
        result[ticker] = df

    return result
