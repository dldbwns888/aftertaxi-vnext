# -*- coding: utf-8 -*-
"""test_data_cache.py — 데이터 캐시 + metadata-builder 동기화 테스트"""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aftertaxi.apps.data_cache import DataCache


class TestDataCache:

    @pytest.fixture
    def cache(self):
        tmp = Path(tempfile.mkdtemp()) / "test_cache.db"
        c = DataCache(db_path=tmp)
        yield c
        c.close()

    def test_put_and_get_prices(self, cache):
        idx = pd.date_range("2024-01-01", periods=12, freq="ME")
        df = pd.DataFrame({"SPY": range(100, 112)}, index=idx)
        n = cache.put_prices("SPY", "yfinance", df)
        assert n == 12

        result = cache.get_prices("SPY", "yfinance")
        assert result is not None
        assert len(result) == 12
        assert "SPY" in result.columns

    def test_cache_miss(self, cache):
        result = cache.get_prices("NONEXISTENT", "yfinance")
        assert result is None

    def test_stale_check(self, cache):
        idx = pd.date_range("2024-01-01", periods=5, freq="ME")
        df = pd.DataFrame({"SPY": range(5)}, index=idx)
        cache.put_prices("SPY", "test", df)

        # max_age=0 → 즉시 stale
        result = cache.get_prices("SPY", "test", max_age_hours=0)
        assert result is None

        # max_age 충분 → 캐시 히트
        result = cache.get_prices("SPY", "test", max_age_hours=999)
        assert result is not None

    def test_put_and_get_fx(self, cache):
        idx = pd.date_range("2024-01-01", periods=12, freq="ME")
        s = pd.Series(1300.0 + np.arange(12), index=idx, name="USDKRW")
        n = cache.put_fx("USDKRW", "yfinance", s)
        assert n == 12

        result = cache.get_fx("USDKRW", "yfinance")
        assert result is not None
        assert len(result) == 12

    def test_clear(self, cache):
        idx = pd.date_range("2024-01-01", periods=5, freq="ME")
        cache.put_prices("SPY", "test", pd.DataFrame({"SPY": range(5)}, index=idx))
        cache.clear(ticker="SPY")
        assert cache.get_prices("SPY", "test") is None

    def test_summary(self, cache):
        idx = pd.date_range("2024-01-01", periods=5, freq="ME")
        cache.put_prices("SPY", "test", pd.DataFrame({"SPY": range(5)}, index=idx))
        s = cache.summary()
        assert s["n_prices"] == 5
        assert "SPY" in s["tickers"]


class TestCachedYfinance:

    def test_yfinance_with_cache(self):
        """캐시 모드로 yfinance 로드 → 두 번째는 캐시에서."""
        from aftertaxi.apps.data_provider import load_market_data

        # 첫 번째: 네트워크 다운로드
        d1 = load_market_data(
            ["SPY"], source="yfinance",
            start="2024-01-01", fx_rate=1300.0,
            cache=True, max_age_hours=999,
        )
        assert d1.n_months > 0

        # 두 번째: 캐시 히트 (source에 "cached" 표시)
        d2 = load_market_data(
            ["SPY"], source="yfinance",
            start="2024-01-01", fx_rate=1300.0,
            cache=True, max_age_hours=999,
        )
        assert "cached" in d2.source
        assert d2.n_months > 0


class TestMetadataBuilderSync:

    def test_existing_strategies_synced(self):
        """기존 7개 전략이 registry와 metadata 양쪽에 있음."""
        from aftertaxi.strategies import registry
        from aftertaxi.strategies.metadata import get_metadata

        for key in registry.available():
            meta = get_metadata(key)
            assert meta.key == key

    def test_register_with_metadata(self):
        """register(key, metadata=...) 한 번에 등록."""
        from aftertaxi.strategies.registry import StrategyRegistry
        from aftertaxi.strategies.metadata import StrategyMetadata, get_metadata
        from aftertaxi.strategies.spec import StrategySpec

        test_registry = StrategyRegistry()
        meta = StrategyMetadata(
            key="test_sync", label="Test Sync", category="test",
            description="sync test",
        )

        @test_registry.register("test_sync", metadata=meta)
        def build_test(**kw):
            return StrategySpec(name="TestSync", weights={"SPY": 1.0})

        # builder 등록됨
        assert "test_sync" in test_registry.available()
        # metadata 등록됨
        m = get_metadata("test_sync")
        assert m.label == "Test Sync"
