# -*- coding: utf-8 -*-
"""
test_market_db.py — MarketDB 통합 테스트
==========================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
import pytest
from pathlib import Path
import tempfile

from aftertaxi.loaders.market_db import MarketDB

AV_KEY = "1F77HAKH3TOIU5DZ"
FRED_KEY = "f8808fc62203cc8e92829766b2fde343"
EODHD_TOKEN = "69ce250dca4179.05825535"


@pytest.fixture(scope="module")
def db():
    """모듈 스코프 DB — 한 번만 ingest."""
    tmp = Path(tempfile.mkdtemp()) / "test_market.db"
    db = MarketDB(db_path=tmp)

    # Alpha Vantage (SPY만, rate limit 절약)
    db.ingest_alphavantage(["SPY"], AV_KEY)
    # FRED FX
    db.ingest_fred(FRED_KEY, start="2020-01-01")

    yield db
    db.close()


# ══════════════════════════════════════════════
# 기본 쿼리
# ══════════════════════════════════════════════

class TestBasicQueries:

    def test_get_prices(self, db):
        df = db.get_prices("SPY")
        assert len(df) > 100
        assert "close" in df.columns
        assert "adjusted_close" in df.columns

    def test_get_prices_with_date_filter(self, db):
        df = db.get_prices("SPY", start="2024-01-01", end="2024-12-31")
        assert len(df) > 0
        assert len(df) <= 12

    def test_get_dividends(self, db):
        df = db.get_dividends("SPY")
        assert len(df) > 0
        assert "amount" in df.columns

    def test_get_fx(self, db):
        fx = db.get_fx("USDKRW")
        assert len(fx) > 0
        assert fx.iloc[-1] > 1000

    def test_sources_for(self, db):
        sources = db.sources_for("SPY")
        assert "alphavantage" in sources

    def test_summary(self, db):
        s = db.summary()
        assert "prices" in s
        assert "alphavantage" in s["prices"]
        assert "SPY" in s["prices"]["alphavantage"]

    def test_nonexistent_ticker(self, db):
        df = db.get_prices("NONEXISTENT")
        assert len(df) == 0


# ══════════════════════════════════════════════
# 엔진 연결
# ══════════════════════════════════════════════

class TestEngineIntegration:

    def test_db_to_engine(self, db):
        """DB 데이터로 엔진 실행."""
        from aftertaxi.core.contracts import (
            AccountConfig, AccountType, BacktestConfig, StrategyConfig,
        )
        from aftertaxi.core.facade import run_backtest
        from aftertaxi.core.dividend import DividendSchedule

        prices_df = db.get_prices("SPY", start="2020-01-01", end="2024-12-31")
        fx = db.get_fx("USDKRW", start="2020-01-01", end="2024-12-31")

        # close 컬럼을 SPY로 rename
        prices = prices_df[["close"]].rename(columns={"close": "SPY"})

        common = prices.index.intersection(fx.index)
        prices = prices.loc[common]
        fx = fx.loc[common]
        returns = prices.pct_change().fillna(0.0)

        # 배당
        divs = db.get_dividends("SPY", start="2020-01-01", end="2024-12-31")
        if len(divs) > 0:
            annual_div = divs["amount"].sum() / max(len(prices) / 12, 1)
            last_price = prices["SPY"].iloc[-1]
            annual_yield = annual_div / last_price if last_price > 0 else 0
        else:
            annual_yield = 0

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("spy_db", {"SPY": 1.0}),
                dividend_schedule=DividendSchedule({"SPY": annual_yield}) if annual_yield > 0 else None,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        assert result.gross_pv_usd > 0
        assert result.n_months >= 12


# ══════════════════════════════════════════════
# yfinance 교차 검증
# ══════════════════════════════════════════════

class TestCrossIngest:

    def test_ingest_yfinance(self):
        """yfinance도 같은 DB에 적재 가능."""
        yf = pytest.importorskip("yfinance")

        tmp = Path(tempfile.mkdtemp()) / "cross.db"
        db = MarketDB(db_path=tmp)
        n = db.ingest_yfinance(["SPY"], start="2024-01-01")
        assert n > 0

        sources = db.sources_for("SPY")
        assert "yfinance" in sources
        db.close()
