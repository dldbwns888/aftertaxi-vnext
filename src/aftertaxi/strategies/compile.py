# -*- coding: utf-8 -*-
"""
strategies/compile.py — 입력 컴파일러
======================================
JSON/dict → typed contracts. 입력 파이프라인의 마지막 접착층.

사용법:
  payload = {
      "strategy": {"type": "q60s40"},
      "accounts": [
          {"type": "ISA", "monthly_contribution": 300, "priority": 0},
          {"type": "TAXABLE", "monthly_contribution": 700, "priority": 1},
      ],
      "n_months": 240,
  }
  config = compile_backtest(payload)
  result = run_backtest(config, ...)

지원:
  - registry에 등록된 strategy type
  - ISA / TAXABLE account presets
  - tax presets (TAXABLE_TAX, ISA_TAX)
  - annual_cap, allowed_assets, priority, transaction_cost_bps
  - dividend_schedule (annual_yield dict)
  - enable_health_insurance

미지원 → 명시적 예외:
  - PENSION account
  - BUDGET rebalance
  - AI/natural language 입력 (향후)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, RebalanceMode,
    StrategyConfig, TaxConfig,
    TAXABLE_TAX, ISA_TAX,
    make_taxable, make_isa,
)
from aftertaxi.strategies.registry import registry
from aftertaxi.strategies.spec import StrategySpec


# ══════════════════════════════════════════════
# Strategy Compile
# ══════════════════════════════════════════════

def compile_strategy(spec_dict: dict) -> StrategyConfig:
    """전략 dict → StrategyConfig.

    Parameters
    ----------
    spec_dict : {"type": "q60s40", "name": "my_strat", "params": {...}}
                또는 {"weights": {"SPY": 0.6, "QQQ": 0.4}, "rebalance_every": 12}
    """
    if "type" in spec_dict:
        # registry 경유
        spec = registry.build_from_dict(spec_dict)
        return spec.to_config()
    elif "weights" in spec_dict:
        # 직접 weights 지정
        return StrategyConfig(
            name=spec_dict.get("name", "custom"),
            weights=spec_dict["weights"],
            rebalance_every=spec_dict.get("rebalance_every", 1),
        )
    else:
        raise ValueError(
            "strategy에 'type' 또는 'weights' 필요. "
            f"받은 키: {list(spec_dict.keys())}"
        )


# ══════════════════════════════════════════════
# Account Compile
# ══════════════════════════════════════════════

_ACCOUNT_PRESETS = {
    "TAXABLE": {
        "account_type": AccountType.TAXABLE,
        "tax_config": TAXABLE_TAX,
        "rebalance_mode": RebalanceMode.CONTRIBUTION_ONLY,
        "priority": 1,
    },
    "ISA": {
        "account_type": AccountType.ISA,
        "tax_config": ISA_TAX,
        "rebalance_mode": RebalanceMode.CONTRIBUTION_ONLY,
        "annual_cap": 20_000_000.0,
        "priority": 0,
    },
}


def compile_account(acct_dict: dict, index: int = 0) -> AccountConfig:
    """계좌 dict → AccountConfig.

    Parameters
    ----------
    acct_dict : {"type": "ISA", "monthly_contribution": 300, ...}
    index : 자동 account_id 생성용 인덱스
    """
    acct_type = acct_dict.get("type", "TAXABLE").upper()

    if acct_type not in _ACCOUNT_PRESETS:
        supported = list(_ACCOUNT_PRESETS.keys())
        raise NotImplementedError(
            f"계좌 타입 '{acct_type}' 미지원. 지원: {supported}"
        )

    preset = _ACCOUNT_PRESETS[acct_type]

    # 기본값 + 사용자 오버라이드
    account_id = acct_dict.get("account_id", f"{acct_type.lower()}_{index}")
    monthly = acct_dict.get("monthly_contribution", 1000.0)
    priority = acct_dict.get("priority", preset["priority"])
    annual_cap = acct_dict.get("annual_cap", preset.get("annual_cap"))
    tx_bps = acct_dict.get("transaction_cost_bps", 0.0)
    rebal = acct_dict.get("rebalance_mode", preset["rebalance_mode"])

    # rebalance_mode 문자열 → enum
    if isinstance(rebal, str):
        try:
            rebal = RebalanceMode(rebal)
        except ValueError:
            raise NotImplementedError(
                f"리밸 모드 '{rebal}' 미지원. "
                f"지원: {[m.value for m in RebalanceMode]}"
            )

    # allowed_assets
    allowed = acct_dict.get("allowed_assets")
    if allowed is not None:
        allowed = set(allowed)

    return AccountConfig(
        account_id=account_id,
        account_type=preset["account_type"],
        monthly_contribution=monthly,
        rebalance_mode=rebal,
        tax_config=preset["tax_config"],
        annual_cap=annual_cap,
        allowed_assets=allowed,
        transaction_cost_bps=tx_bps,
        priority=priority,
    )


def compile_accounts(acct_list: List[dict]) -> List[AccountConfig]:
    """계좌 리스트 → AccountConfig 리스트."""
    return [compile_account(a, i) for i, a in enumerate(acct_list)]


# ══════════════════════════════════════════════
# Full Backtest Compile
# ══════════════════════════════════════════════

def compile_backtest(payload: dict) -> BacktestConfig:
    """전체 payload → BacktestConfig.

    Parameters
    ----------
    payload : {
        "strategy": {"type": "q60s40"},
        "accounts": [{"type": "ISA", "monthly_contribution": 300}, ...],
        "n_months": 240,
        "enable_health_insurance": false,
        "dividend_yields": {"SPY": 0.015}  # optional
    }
    """
    # strategy (필수)
    if "strategy" not in payload:
        raise ValueError("payload에 'strategy' 필수")
    strategy = compile_strategy(payload["strategy"])

    # accounts (기본: TAXABLE $1000)
    acct_dicts = payload.get("accounts", [{"type": "TAXABLE"}])
    accounts = compile_accounts(acct_dicts)

    # n_months
    n_months = payload.get("n_months")

    # dividend schedule
    div_schedule = None
    div_yields = payload.get("dividend_yields")
    if div_yields:
        from aftertaxi.core.dividend import DividendSchedule
        div_schedule = DividendSchedule(div_yields)

    # health insurance
    enable_hi = payload.get("enable_health_insurance", False)

    return BacktestConfig(
        accounts=accounts,
        strategy=strategy,
        n_months=n_months,
        dividend_schedule=div_schedule,
        enable_health_insurance=enable_hi,
    )
