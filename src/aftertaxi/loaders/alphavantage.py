# -*- coding: utf-8 -*-
"""
loaders/alphavantage.py — Alpha Vantage 데이터 로더
====================================================
TIME_SERIES_MONTHLY_ADJUSTED 하나로 close, adjusted_close, dividend 분리.

장점:
  - 무료 26년+ 이력 (1999~)
  - close(배당 미반영) + adjusted_close(배당 반영) + dividend amount 분리
  - 공식 API
  - 25 req/일 (캐시하면 충분)
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import json
import pandas as pd
import urllib.request


_DEFAULT_CACHE_DIR = Path.home() / ".aftertaxi" / "cache" / "alphavantage"


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())


def load_prices_alphavantage(
    tickers: List[str],
    api_key: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    """Alpha Vantage MONTHLY_ADJUSTED에서 가격+배당 분리 로드.

    Returns
    -------
    dict with:
      "close": DataFrame (배당 미반영)
      "adjusted_close": DataFrame (배당+split 반영)
      "dividends": DataFrame (월별 배당 per share)
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / f"av_monthly_{'_'.join(sorted(tickers))}.parquet"

    if cache_file.exists():
        combined = pd.read_parquet(cache_file)
        result = _split_combined(combined, tickers)
        return _filter_dates(result, start, end)

    all_frames = {}
    for i, ticker in enumerate(tickers):
        if i > 0:
            import time
            time.sleep(1.5)  # Alpha Vantage: 1 req/sec free tier
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=TIME_SERIES_MONTHLY_ADJUSTED"
            f"&symbol={ticker}&apikey={api_key}"
        )
        data = _fetch_json(url)

        ts = data.get("Monthly Adjusted Time Series", {})
        if not ts:
            note = data.get("Note", data.get("Information", ""))
            if "rate limit" in note.lower() or "api call" in note.lower():
                import time
                time.sleep(15)  # rate limit → 15초 대기 후 재시도
                data = _fetch_json(url)
                ts = data.get("Monthly Adjusted Time Series", {})
                if not ts:
                    raise RuntimeError(f"Alpha Vantage rate limit: {note}")
            else:
                continue

        records = []
        for date_str, values in ts.items():
            records.append({
                "date": date_str,
                f"{ticker}_close": float(values["4. close"]),
                f"{ticker}_adj": float(values["5. adjusted close"]),
                f"{ticker}_div": float(values["7. dividend amount"]),
                f"{ticker}_volume": int(values["6. volume"]),
            })

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        all_frames[ticker] = df

    if not all_frames:
        return {"close": pd.DataFrame(), "adjusted_close": pd.DataFrame(), "dividends": pd.DataFrame()}

    # 합치기
    combined = pd.concat(all_frames.values(), axis=1)
    combined.index = combined.index + pd.offsets.MonthEnd(0)

    # 캐시
    cache_dir.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(cache_file)

    result = _split_combined(combined, tickers)
    return _filter_dates(result, start, end)


def _split_combined(combined: pd.DataFrame, tickers: List[str]) -> Dict[str, pd.DataFrame]:
    """combined DataFrame을 close/adj/div로 분리."""
    close_cols = {f"{t}_close": t for t in tickers if f"{t}_close" in combined.columns}
    adj_cols = {f"{t}_adj": t for t in tickers if f"{t}_adj" in combined.columns}
    div_cols = {f"{t}_div": t for t in tickers if f"{t}_div" in combined.columns}

    return {
        "close": combined[list(close_cols.keys())].rename(columns=close_cols),
        "adjusted_close": combined[list(adj_cols.keys())].rename(columns=adj_cols),
        "dividends": combined[list(div_cols.keys())].rename(columns=div_cols),
    }


def _filter_dates(result: Dict[str, pd.DataFrame], start, end):
    """날짜 필터."""
    for key in result:
        if start:
            result[key] = result[key].loc[start:]
        if end:
            result[key] = result[key].loc[:end]
    return result
