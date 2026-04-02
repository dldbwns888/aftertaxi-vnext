# -*- coding: utf-8 -*-
"""
loaders/ — 멀티소스 데이터 로더
================================
추천 조합:
  - 가격 + 배당: Alpha Vantage (무료 26년+, close/adj/div 분리)
  - FX: FRED (무료 30년+, DEXKOUS)
  - 검증/상세: EODHD (close/adj 분리, 배당 날짜 상세)
  - 레거시: yfinance (무제한이지만 스크래핑)
"""

from aftertaxi.loaders.eodhd import (
    load_prices_eodhd,
    load_dividends_eodhd,
    load_fx_eodhd,
    dividends_to_monthly,
    DividendRecord,
)
from aftertaxi.loaders.alphavantage import load_prices_alphavantage
from aftertaxi.loaders.fred import load_fx_fred
