# -*- coding: utf-8 -*-
"""
strategies/builders.py — 내장 전략 빌더
========================================
전략 추가 = 이 파일에 함수 하나 + @registry.register("key")

aftertaxi 연구에서 확정된 전략들:
  - Q60S40: QQQ 60% + SSO 40% (코어)
  - SPY B&H: SPY 100% (벤치마크)
  - 60/40: SPY 60% + TLT 40% (전통)
  - QQQ_1.4x: 나스닥 프리미엄 신념 대안
"""
from aftertaxi.strategies.registry import registry
from aftertaxi.strategies.spec import StrategySpec


@registry.register("q60s40")
def build_q60s40(**kwargs) -> StrategySpec:
    """Q60S40: QQQ 60% + SSO 40%. aftertaxi 코어 확정 전략."""
    return StrategySpec(
        name="Q60S40_CO",
        family="static_allocation",
        weights={"QQQ": 0.6, "SSO": 0.4},
        rebalance_every=kwargs.get("rebalance_every", 1),
        params=kwargs,
        description="QQQ 60% + SSO 40%, C/O, 납입전용. "
                    "Shiller 152년 20년 승률 100%. 파괴테스트 10개 중 1개만 <1.5x.",
    )


@registry.register("spy_bnh")
def build_spy_bnh(**kwargs) -> StrategySpec:
    """SPY 100% Buy & Hold. 벤치마크."""
    return StrategySpec(
        name="SPY_BnH",
        family="benchmark",
        weights={"SPY": 1.0},
        rebalance_every=1,
        params=kwargs,
        description="SPY 100% 매수보유. 벤치마크.",
    )


@registry.register("qqq_bnh")
def build_qqq_bnh(**kwargs) -> StrategySpec:
    """QQQ 100% Buy & Hold."""
    return StrategySpec(
        name="QQQ_BnH",
        family="benchmark",
        weights={"QQQ": 1.0},
        rebalance_every=1,
        params=kwargs,
        description="QQQ 100% 매수보유.",
    )


@registry.register("6040")
def build_6040(stock: str = "SPY", bond: str = "TLT", **kwargs) -> StrategySpec:
    """전통 60/40."""
    return StrategySpec(
        name="60_40",
        family="static_allocation",
        weights={stock: 0.6, bond: 0.4},
        rebalance_every=kwargs.get("rebalance_every", 12),  # 연 1회
        params={"stock": stock, "bond": bond, **kwargs},
        description=f"{stock} 60% + {bond} 40%, 연 리밸.",
    )


@registry.register("qqq_1.4x")
def build_qqq_14x(**kwargs) -> StrategySpec:
    """QQQ 1.4x: 나스닥 프리미엄 신념 대안.
    α=0%면 Q60 승, α≥0.2%면 QQQ 승."""
    return StrategySpec(
        name="QQQ_1.4x",
        family="leveraged_single",
        weights={"QLD": 0.4, "QQQ": 0.6},  # QLD(2x)×0.4 + QQQ(1x)×0.6 ≈ 1.4x
        rebalance_every=kwargs.get("rebalance_every", 1),
        params=kwargs,
        description="나스닥 1.4x 근사. QLD 40% + QQQ 60%.",
    )


@registry.register("equal_weight")
def build_equal_weight(assets=None, **kwargs) -> StrategySpec:
    """동일 비중."""
    if assets is None:
        assets = ["SPY", "QQQ"]
    w = 1.0 / len(assets)
    return StrategySpec(
        name="EqualWeight",
        family="static_allocation",
        weights={a: w for a in assets},
        rebalance_every=kwargs.get("rebalance_every", 1),
        params={"assets": assets, **kwargs},
        description=f"{len(assets)}종 동일비중.",
    )


@registry.register("custom")
def build_custom(weights: dict = None, name: str = "Custom", **kwargs) -> StrategySpec:
    """사용자 정의 비중."""
    if weights is None:
        weights = {"SPY": 1.0}
    return StrategySpec(
        name=name,
        family="custom",
        weights=weights,
        rebalance_every=kwargs.get("rebalance_every", 1),
        params={"weights": weights, **kwargs},
        description="사용자 정의.",
    )
