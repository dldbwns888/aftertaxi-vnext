# -*- coding: utf-8 -*-
"""
apps/data_fingerprint.py — 데이터 출처 추적
============================================
"이 결과는 어떤 데이터 위에서 나왔는가?"

핵심: 결과를 신뢰하려면 입력 데이터를 추적할 수 있어야 한다.

사용법:
  from aftertaxi.apps.data_fingerprint import DataProvenance, compute_fingerprint

  fp = compute_fingerprint(returns, fx_rates)
  provenance = DataProvenance(
      fingerprint=fp,
      source="yfinance",
      assets=["SPY", "QQQ"],
      date_range="2010-01~2025-01",
      n_months=180,
      notes="Close=split-adjusted, 배당 미반영",
  )
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


def compute_fingerprint(returns: pd.DataFrame, fx_rates: pd.Series) -> str:
    """데이터 해시. 같은 데이터면 같은 fingerprint."""
    h = hashlib.sha256()
    h.update(returns.values.tobytes())
    h.update(fx_rates.values.tobytes())
    h.update(str(returns.index[0]).encode())
    h.update(str(returns.index[-1]).encode())
    h.update(",".join(sorted(returns.columns)).encode())
    return h.hexdigest()[:12]


@dataclass(frozen=True)
class DataProvenance:
    """데이터 출처 메타데이터. 결과와 함께 저장."""
    fingerprint: str                    # sha256[:12]
    source: str                         # "synthetic" | "yfinance" | "yfinance_fx"
    assets: List[str] = field(default_factory=list)
    date_range: str = ""                # "2010-01~2025-01"
    n_months: int = 0
    notes: str = ""                     # "Close=split-adjusted, 배당 미반영"

    def stamp(self) -> str:
        """결과에 찍을 한 줄 도장."""
        return (f"[{self.source}] {','.join(self.assets)} "
                f"{self.date_range} ({self.n_months}mo) "
                f"fp:{self.fingerprint}")

    @staticmethod
    def from_market_data(market, returns, fx_rates) -> "DataProvenance":
        """MarketData + raw data → DataProvenance."""
        fp = compute_fingerprint(returns, fx_rates)
        source_notes = {
            "synthetic": "합성 데이터. 실제 시장과 다를 수 있음.",
            "yfinance": "yfinance Close (split-adjusted, 배당 미반영).",
            "yfinance_fx": "yfinance Close + 실제 USDKRW 환율.",
        }
        return DataProvenance(
            fingerprint=fp,
            source=getattr(market, "source", "unknown"),
            assets=list(returns.columns),
            date_range=f"{returns.index[0]:%Y-%m}~{returns.index[-1]:%Y-%m}",
            n_months=len(returns),
            notes=source_notes.get(getattr(market, "source", ""), ""),
        )
