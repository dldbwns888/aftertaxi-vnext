# -*- coding: utf-8 -*-
"""
facade.py — 공개 API 단일 진입점
==================================
PR 2: 새 runner 사용. 시그니처 동일.

사용법:
    from aftertaxi.core.facade import run_backtest
    result = run_backtest(config, returns=returns, prices=prices, fx_store=fx_store)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from aftertaxi.core.contracts import BacktestConfig, EngineResult
from aftertaxi.core.runner import run_engine


def run_backtest(
    config: BacktestConfig,
    *,
    returns: pd.DataFrame,
    prices: Optional[pd.DataFrame] = None,
    fx_store=None,
    fx_rates: Optional[pd.Series] = None,
    journal=None,
) -> EngineResult:
    """단일 진입점. config + 데이터 → typed EngineResult.

    prices가 없으면 returns에서 누적 가격을 역산.
    fx_store(legacy FxRateStore) 또는 fx_rates(pd.Series)를 받음.
    journal: Optional[EventJournal]. 넘기면 내부에서 이벤트가 기록됨.
    """
    _validate_config(config)

    if prices is None:
        prices = _returns_to_prices(returns)

    if fx_rates is None and fx_store is not None:
        fx_rates = _extract_fx_series(fx_store)

    if fx_rates is None:
        raise ValueError("fx_rates 또는 fx_store를 제공해야 합니다.")

    return run_engine(config, prices, fx_rates, journal=journal)


def _validate_config(config: BacktestConfig) -> None:
    """미구현 설정이 활성화되면 예외.

    계약에 존재하지만 엔진이 무시하는 필드가 설정되면
    사용자가 "동작한다"고 착각하는 것을 방지.
    """
    from aftertaxi.core.contracts import RebalanceMode

    for acct in config.accounts:
        if acct.rebalance_mode == RebalanceMode.BUDGET:
            raise NotImplementedError(
                f"계좌 '{acct.account_id}': BUDGET 리밸런스 모드는 아직 미구현. "
                "CONTRIBUTION_ONLY 또는 FULL을 사용하세요."
            )
        if acct.lot_method != "AVGCOST":
            raise NotImplementedError(
                f"계좌 '{acct.account_id}': lot_method='{acct.lot_method}'는 미구현. "
                "현재 AVGCOST만 지원. FIFO/HIFO는 scope outside."
            )


def _returns_to_prices(returns: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    """월간 수익률 → 누적 가격."""
    return base * (1 + returns).cumprod()


def _extract_fx_series(fx_store) -> pd.Series:
    """FxRateStore → pd.Series 추출."""
    if isinstance(fx_store, pd.Series):
        return fx_store
    if hasattr(fx_store, "rates"):
        return fx_store.rates
    raise TypeError(f"fx_store에서 Series를 추출할 수 없음: {type(fx_store)}")
