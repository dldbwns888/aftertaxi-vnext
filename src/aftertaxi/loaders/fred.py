# -*- coding: utf-8 -*-
"""
loaders/fred.py — FRED FX 환율 로더
====================================
FRED API에서 DEXKOUS (USDKRW) 월별 환율 로드.
무료, 30년+, 공식 API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import json
import pandas as pd
import urllib.request


_DEFAULT_CACHE_DIR = Path.home() / ".aftertaxi" / "cache" / "fred"


def load_fx_fred(
    api_key: str,
    start: str = "2000-01-01",
    end: Optional[str] = None,
    series_id: str = "DEXKOUS",
    cache_dir: Optional[Path] = None,
) -> pd.Series:
    """FRED에서 월별 USDKRW 환율 로드.

    Parameters
    ----------
    api_key : FRED API key
    start : 시작일
    end : 종료일
    series_id : FRED series (DEXKOUS = USD/KRW)

    Returns
    -------
    Series: index=DatetimeIndex(month-end), values=KRW per USD
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / f"fred_{series_id}_{start}.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        s = df.iloc[:, 0]
        if end:
            s = s.loc[:end]
        return s

    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}"
        f"&api_key={api_key}"
        f"&file_type=json"
        f"&observation_start={start}"
        f"&frequency=m"
    )
    if end:
        url += f"&observation_end={end}"

    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())

    observations = data.get("observations", [])
    dates = []
    values = []
    for obs in observations:
        val = obs["value"]
        if val == "." or val == "":
            continue
        dates.append(obs["date"])
        values.append(float(val))

    s = pd.Series(values, index=pd.to_datetime(dates), name=series_id)
    s.index = s.index + pd.offsets.MonthEnd(0)

    # 캐시
    cache_dir.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(cache_file)

    if end:
        s = s.loc[:end]
    return s
