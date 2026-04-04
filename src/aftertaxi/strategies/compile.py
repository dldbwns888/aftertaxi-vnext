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


def _merge_tax_config(preset_tax: TaxConfig, override: dict) -> TaxConfig:
    """preset TaxConfig + user override → 최종 TaxConfig.

    규칙: preset은 default supplier. user가 이긴다.
    """
    from dataclasses import asdict

    base = asdict(preset_tax)
    override = dict(override)  # 방어 복사 (caller의 dict 변형 방지)
    # "progressive": true 단축키 → KOREA_PROGRESSIVE_BRACKETS 주입
    if override.pop("progressive", False):
        from aftertaxi.core.contracts import KOREA_PROGRESSIVE_BRACKETS
        base["progressive_brackets"] = KOREA_PROGRESSIVE_BRACKETS

    unknown = set(override) - set(base)
    if unknown:
        raise ValueError(f"Unknown TaxConfig fields: {sorted(unknown)}")

    merged = {**base, **override}
    # progressive_brackets는 tuple이어야 함 (JSON에서 list로 올 수 있음)
    if merged.get("progressive_brackets") is not None:
        merged["progressive_brackets"] = tuple(
            tuple(x) if isinstance(x, list) else x
            for x in merged["progressive_brackets"]
        )
    return TaxConfig(**merged)


def compile_account(acct_dict: dict, index: int = 0, strict: bool = False) -> AccountConfig:
    """계좌 dict → AccountConfig.

    strict=True: 기본값 자동 채우기 대신 누락 시 에러.
    strict=False (기본): 기존 동작 유지 (monthly=1000 등 자동 보정).
    """
    import warnings
    acct_type = acct_dict.get("type", "TAXABLE").upper()

    if acct_type not in _ACCOUNT_PRESETS:
        supported = list(_ACCOUNT_PRESETS.keys())
        raise NotImplementedError(
            f"계좌 타입 '{acct_type}' 미지원. 지원: {supported}"
        )

    preset = _ACCOUNT_PRESETS[acct_type]

    # monthly_contribution
    if "monthly_contribution" not in acct_dict:
        if strict:
            raise ValueError(
                f"계좌 {index} ({acct_type}): monthly_contribution 누락. "
                f"strict 모드에서는 반드시 지정해야 합니다."
            )
        else:
            warnings.warn(
                f"계좌 {index} ({acct_type}): monthly_contribution 미지정 → 기본값 $1,000 적용.",
                UserWarning, stacklevel=2,
            )

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

    # BAND threshold
    band_threshold = acct_dict.get("band_threshold_pct", 0.05)

    # TaxConfig: preset merge user override
    tax_override = dict(acct_dict.get("tax", {}))
    # 하위 호환: top-level "progressive" → tax override로 이동
    if "progressive" in acct_dict:
        tax_override.setdefault("progressive", acct_dict["progressive"])
    if "progressive_threshold" in acct_dict:
        tax_override.setdefault("progressive_threshold", acct_dict["progressive_threshold"])
    tax_config = _merge_tax_config(preset["tax_config"], tax_override)

    return AccountConfig(
        account_id=account_id,
        account_type=preset["account_type"],
        monthly_contribution=monthly,
        rebalance_mode=rebal,
        tax_config=tax_config,
        annual_cap=annual_cap,
        allowed_assets=allowed,
        transaction_cost_bps=tx_bps,
        priority=priority,
        band_threshold_pct=band_threshold,
    )


def compile_accounts(acct_list: List[dict], strict: bool = False) -> List[AccountConfig]:
    """계좌 리스트 → AccountConfig 리스트."""
    if not acct_list:
        if strict:
            raise ValueError("accounts 목록이 비어 있습니다.")
        acct_list = [{"type": "TAXABLE"}]
    return [compile_account(a, i, strict=strict) for i, a in enumerate(acct_list)]


# ══════════════════════════════════════════════
# Full Backtest Compile
# ══════════════════════════════════════════════

def compile_backtest(payload: dict, strict: bool = False) -> BacktestConfig:
    """전체 payload → BacktestConfig.

    strict=True: 누락 필드 시 에러 (API/프로덕션용).
    strict=False: 기존 동작 유지 (GUI/연구용).

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
    accounts = compile_accounts(acct_dicts, strict=strict)

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


def compile_backtest_with_trace(payload: dict):
    """compile + CompileTrace 생성. UI용.

    Returns: (BacktestConfig, CompileTrace)
    """
    from aftertaxi.intent.plan import CompileTrace, CompileDecision

    config = compile_backtest(payload)
    decisions = []

    # 전략
    strat = payload.get("strategy", {})
    stype = strat.get("type", "custom")
    weights = config.strategy.weights
    decisions.append(CompileDecision(
        "전략", f"{stype} ({', '.join(f'{k} {v:.0%}' for k, v in weights.items())})",
        "strategy.type" if "type" in strat else "custom weights",
    ))

    # 계좌
    for ac in config.accounts:
        cap_str = f", 연 한도 ₩{ac.annual_cap:,.0f}" if ac.annual_cap else ""
        prog_str = ", 누진세" if ac.tax_config.progressive_brackets else ""
        decisions.append(CompileDecision(
            f"계좌 {ac.account_id}",
            f"{ac.account_type.value} ${ac.monthly_contribution:,.0f}/월 "
            f"{ac.rebalance_mode.value}{cap_str}{prog_str}",
            f"priority={ac.priority}",
        ))

    # 기간
    if config.n_months:
        decisions.append(CompileDecision("기간", f"{config.n_months}개월", "n_months"))

    # 배당
    if config.dividend_schedule:
        decisions.append(CompileDecision("배당", "활성", "dividend_yields"))

    # 건보료
    if config.enable_health_insurance:
        decisions.append(CompileDecision("건보료", "활성", "enable_health_insurance"))

    summary = f"{stype} / {len(config.accounts)}계좌 / {config.n_months or '?'}개월"
    trace = CompileTrace(input_intent_summary=summary, decisions=decisions)

    return config, trace


def apply_suggestion_patch(base_payload: dict, patch: dict) -> dict:
    """SuggestionPatch를 기존 payload에 안전하게 적용.

    규칙:
      1. _action=compare → payload 변경 없이 비교 의도만 반환
      2. accounts patch → 기존 accounts에 merge (replace 아님)
      3. strategy patch → 기존 strategy에 merge
      4. 원본 payload 변형 금지

    Returns: 새 payload (원본 불변)
    Raises: warnings.warn() when auto-correcting
    """
    import copy
    import warnings
    result = copy.deepcopy(base_payload)

    # compare action은 payload를 바꾸지 않음
    if patch.get("_action") == "compare":
        return result

    # accounts patch: 기존 accounts에 필드 merge
    if "accounts" in patch:
        existing = result.get("accounts", [])
        patch_accounts = patch["accounts"]

        for pa in patch_accounts:
            if "type" in pa:
                matched = False
                for ea in existing:
                    if ea.get("type", "").upper() == pa["type"].upper():
                        ea.update({k: v for k, v in pa.items()})
                        matched = True
                        break
                if not matched:
                    new_acct = dict(pa)
                    if "monthly_contribution" not in new_acct:
                        avg = sum(a.get("monthly_contribution", 1000)
                                  for a in existing) / max(1, len(existing))
                        new_acct["monthly_contribution"] = avg
                        warnings.warn(
                            f"새 계좌 '{pa.get('type', '?')}'에 monthly 미지정 → "
                            f"기존 평균 ${avg:,.0f} 자동 적용. 의도한 금액이 맞는지 확인하세요.",
                            UserWarning, stacklevel=2,
                        )
                    existing.append(new_acct)
            else:
                for ea in existing:
                    ea.update({k: v for k, v in pa.items()})

        result["accounts"] = existing

    # strategy patch
    if "strategy" in patch:
        existing_strat = result.get("strategy", {})
        existing_strat.update(patch["strategy"])
        result["strategy"] = existing_strat

    return result
