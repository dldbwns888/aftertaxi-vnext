# -*- coding: utf-8 -*-
"""
lane_a/run.py — Lane A 실행 편의 함수
======================================
실제 ETF + FX로 세후 백테스트 실행.

사용법:
    from aftertaxi.lanes.lane_a.run import run_lane_a
    result = run_lane_a(
        tickers=["QQQ", "SSO"],
        weights={"QQQ": 0.6, "SSO": 0.4},
        monthly=1_000_000,   # 월 납입 KRW (USD 환산은 내부에서)
        start="2006-06",
    )
"""
from __future__ import annotations

from typing import Dict, List, Optional

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.lanes.lane_a.loader import load_lane_a


def run_lane_a(
    tickers: List[str],
    weights: Dict[str, float],
    monthly_usd: float = 1000.0,
    start: str = "2006-06-01",
    end: Optional[str] = None,
    rebalance_mode: str = "CO",
    rebalance_every: int = 1,
    account_type: str = "TAXABLE",
    strategy_name: str = "lane_a",
) -> EngineResult:
    """Lane A 실행.

    Parameters
    ----------
    tickers : ETF 티커 리스트
    weights : {ticker: weight} 비중
    monthly_usd : 월 납입액 (USD)
    start : 시작일
    end : 종료일
    rebalance_mode : "CO" 또는 "FULL"
    rebalance_every : N개월마다 리밸런싱
    account_type : "TAXABLE" 또는 "ISA"

    Returns
    -------
    EngineResult
    """
    # 데이터 로드
    data = load_lane_a(tickers, start=start, end=end)

    # config 구성
    mode = RebalanceMode.CONTRIBUTION_ONLY if rebalance_mode == "CO" else RebalanceMode.FULL
    acct_type = AccountType.TAXABLE if account_type == "TAXABLE" else AccountType.ISA

    config = BacktestConfig(
        accounts=[AccountConfig(
            account_id=account_type.lower(),
            account_type=acct_type,
            monthly_contribution=monthly_usd,
            rebalance_mode=mode,
        )],
        strategy=StrategyConfig(
            name=strategy_name,
            weights=weights,
            rebalance_every=rebalance_every,
        ),
    )

    return run_backtest(
        config,
        returns=data["returns"],
        prices=data["prices"],
        fx_rates=data["fx_rates"],
    )
