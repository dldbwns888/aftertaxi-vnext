# -*- coding: utf-8 -*-
"""
apps/gui/draft_models.py — GUI 입력 초안 모델
==============================================
GUI에서 입력하는 건 불완전하고 느슨하다.
Draft는 빈 값 허용, 문자열 허용, UI 친화적.

Draft ≠ BacktestConfig.
Draft → compile → BacktestConfig → engine.

Draft는 저장/불러오기 가능 (JSON).
Draft는 lightweight validation 가능 (compile 전 즉각 피드백).

사용법:
  draft = BacktestDraft(
      strategy=StrategyDraft(type="q60s40"),
      accounts=[AccountDraft(type="TAXABLE", monthly=1000)],
  )

  errors = draft.validate()  # [] 이면 OK
  payload = draft.to_dict()  # → JSON 가능
  config = compile_backtest(payload)  # → BacktestConfig
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import json


@dataclass
class StrategyDraft:
    """전략 초안. GUI 폼에서 채움."""
    type: Optional[str] = None        # registry key ("q60s40") 또는 None
    params: Dict[str, Any] = field(default_factory=dict)
    weights: Optional[Dict[str, float]] = None  # custom일 때 직접 지정
    name: Optional[str] = None        # 사용자 지정 이름

    def validate(self) -> List[str]:
        """경량 검증. compile 전 UI 즉각 피드백."""
        errors = []
        if not self.type and not self.weights:
            errors.append("전략 타입 또는 비중을 선택하세요")
        if self.weights:
            total = sum(self.weights.values())
            if abs(total - 1.0) > 0.01:
                errors.append(f"비중 합이 {total:.0%}입니다 (100%여야 함)")
        return errors

    def to_dict(self) -> dict:
        d = {}
        if self.type:
            d["type"] = self.type
        if self.params:
            d["params"] = self.params
        if self.weights:
            d["weights"] = self.weights
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class AccountDraft:
    """계좌 초안."""
    type: str = "TAXABLE"             # "TAXABLE" or "ISA"
    monthly: Optional[float] = None   # 월 납입 (USD)
    priority: Optional[int] = None
    annual_cap: Optional[float] = None
    allowed_assets: Optional[List[str]] = None

    def validate(self) -> List[str]:
        errors = []
        if self.type.upper() not in ("TAXABLE", "ISA"):
            errors.append(f"계좌 타입 '{self.type}' 미지원 (TAXABLE/ISA만)")
        if self.monthly is not None and self.monthly < 0:
            errors.append("월 납입금은 0 이상이어야 합니다")
        if self.annual_cap is not None and self.monthly is not None:
            if self.annual_cap < self.monthly:
                errors.append("연간 한도가 월 납입금보다 작습니다")
        return errors

    def to_dict(self) -> dict:
        d = {"type": self.type}
        if self.monthly is not None:
            d["monthly_contribution"] = self.monthly
        if self.priority is not None:
            d["priority"] = self.priority
        if self.annual_cap is not None:
            d["annual_cap"] = self.annual_cap
        if self.allowed_assets is not None:
            d["allowed_assets"] = self.allowed_assets
        return d


@dataclass
class BacktestDraft:
    """백테스트 전체 초안.

    GUI/CLI/API/AI 공통 입력 포맷.
    """
    strategy: StrategyDraft = field(default_factory=StrategyDraft)
    accounts: List[AccountDraft] = field(default_factory=list)
    n_months: Optional[int] = None
    enable_health_insurance: bool = False
    dividend_yields: Optional[Dict[str, float]] = None

    # 보기 설정 (실행 설정과 분리)
    lane_d: bool = False
    lane_d_compare: bool = False
    lane_d_paths: int = 50
    lane_d_years: int = 100
    include_validation: bool = False

    def validate(self) -> List[str]:
        """전체 경량 검증."""
        errors = self.strategy.validate()
        if not self.accounts:
            errors.append("계좌를 최소 1개 추가하세요")
        for i, acct in enumerate(self.accounts):
            for e in acct.validate():
                errors.append(f"계좌 {i+1}: {e}")
        if self.n_months is not None and self.n_months < 1:
            errors.append("기간은 1개월 이상이어야 합니다")
        return errors

    def warn(self) -> List[str]:
        """도메인 상식 기반 경고. (#9)

        에러는 아니지만 의도치 않은 설정을 감지.
        """
        warnings = []

        # ISA 한도 경고
        for i, acct in enumerate(self.accounts):
            if acct.type.upper() == "ISA" and acct.monthly:
                annual = acct.monthly * 12
                if annual > 2000:  # USD 기준 ~2400만원/yr ≈ $1850
                    warnings.append(
                        f"계좌 {i+1}: ISA 월 ${acct.monthly:.0f} → 연 ${annual:.0f}. "
                        f"한국 ISA 연간 한도(약 $1,850)를 초과할 수 있습니다."
                    )

        # 레버리지 ETF + 낮은 변동성 경고
        leveraged = {"SSO", "QLD", "TQQQ", "UPRO", "SOXL"}
        if self.strategy.type:
            from aftertaxi.strategies.metadata import get_metadata
            try:
                meta = get_metadata(self.strategy.type)
                used_assets = set(meta.default_weights.keys())
                if used_assets & leveraged:
                    warnings.append(
                        f"레버리지 ETF({used_assets & leveraged}) 포함. "
                        f"합성 데이터 사용 시 변동성을 30%+ 로 설정하세요 (실제 vol ≈ 30~50%)."
                    )
            except KeyError:
                pass

        # 장기 + 고액
        total_monthly = sum(a.monthly or 0 for a in self.accounts)
        if self.n_months and self.n_months > 120 and total_monthly > 2000:
            warnings.append(
                f"10년+ 고액 적립(월 ${total_monthly:,.0f}): "
                f"종합과세 누진구간 진입 가능. progressive 세율 확인을 권장합니다."
            )

        return warnings

    def to_dict(self) -> dict:
        """compile.compile_backtest()가 먹는 형식으로 변환."""
        d: dict = {"strategy": self.strategy.to_dict()}
        if self.accounts:
            d["accounts"] = [a.to_dict() for a in self.accounts]
        if self.n_months is not None:
            d["n_months"] = self.n_months
        if self.enable_health_insurance:
            d["enable_health_insurance"] = True
        if self.dividend_yields:
            d["dividend_yields"] = self.dividend_yields
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "BacktestDraft":
        """dict/JSON에서 복원."""
        strat_data = data.get("strategy", {})
        strategy = StrategyDraft(
            type=strat_data.get("type"),
            params=strat_data.get("params", {}),
            weights=strat_data.get("weights"),
            name=strat_data.get("name"),
        )
        accounts = [
            AccountDraft(
                type=a.get("type", "TAXABLE"),
                monthly=a.get("monthly_contribution"),
                priority=a.get("priority"),
                annual_cap=a.get("annual_cap"),
                allowed_assets=a.get("allowed_assets"),
            )
            for a in data.get("accounts", [])
        ]
        return cls(
            strategy=strategy,
            accounts=accounts,
            n_months=data.get("n_months"),
            enable_health_insurance=data.get("enable_health_insurance", False),
            dividend_yields=data.get("dividend_yields"),
        )
