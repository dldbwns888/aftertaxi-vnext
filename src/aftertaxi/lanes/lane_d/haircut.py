# -*- coding: utf-8 -*-
"""
lanes/lane_d/haircut.py — 실행 마찰 haircut 모델
=================================================
"백테스트 숫자와 실제 실행 사이에 얼마나 차이가 나는가?"

코어 무관. EngineResult를 읽어서 실행 비용을 보수적으로 추정.
runner / settlement / ledger / contracts / facade 변경 없음.

계산 모델 (설명 가능한 보수적 haircut):
  각 마찰 요인을 연율 drag(%)로 산출 → n_years 곱 → 배수 할인

  1. slippage_drag:  slippage_bps × annual_turnover_estimate
  2. fx_drag:        fx_spread / fx_rate × 환전 횟수/년
  3. delay_drag:     daily_vol × delay_days × rebal_freq
  4. div_delay_drag: div_yield × delay_days / 365
  5. tax_cash_drag:  tax_paid / gross_pv × opp_cost_months / 12

  total_annual_drag = sum(5개)
  haircut_factor = (1 - total_annual_drag) ^ n_years

가정:
  - 모든 drag는 독립적이고 연율 기준으로 합산 (보수적)
  - DCA 적립식에서 "연 회전율"은 C/O=0%, FULL=추정 20~40%
  - 단순 모델이므로 정밀한 현실 재현이 아닌 "방향성 haircut"

사용법:
  from aftertaxi.lanes.lane_d.haircut import apply_haircut, ExecutionHaircutConfig

  result = run_backtest(config, ...)
  hr = apply_haircut(result, ExecutionHaircutConfig())
  print(hr.summary_text())
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from aftertaxi.core.contracts import EngineResult


# ══════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class ExecutionHaircutConfig:
    """실행 마찰 파라미터.

    기본값: 한국 개인투자자, 해외 ETF, 월적립식 기준.
    """
    # 슬리피지 (매수+매도 편도, bps)
    slippage_bps: float = 5.0

    # 연 추정 회전율 (C/O=0.05, FULL=0.30 수동 지정)
    # None이면 C/O 기본값 0.05 사용
    annual_turnover: Optional[float] = None

    # FX 환전 스프레드 (원/달러, 편도)
    fx_spread_krw: float = 15.0

    # 연 환전 횟수 (월적립=12, 분기=4 등)
    fx_trades_per_year: float = 12.0

    # 리밸런스 지연 (영업일)
    rebalance_delay_days: float = 1.0

    # 연 리밸 횟수 (C/O=12, 연리밸=1 등)
    rebalances_per_year: float = 12.0

    # 일간 변동성 (연율 16% → 일간 ≈ 1%)
    daily_vol: float = 0.01

    # 배당 재투자 지연 (영업일)
    dividend_reinvest_delay_days: float = 7.0

    # 배당수익률 (연율, 없으면 EngineResult에서 추정)
    dividend_yield_annual: Optional[float] = None

    # 세금 납부 현금 보유 기간 (개월)
    # 양도세 5월 확정신고: 연말→5월 ≈ 5개월
    tax_cash_drag_months: float = 3.0

    # 세금 납부용 현금의 기회비용 (연율)
    # 현금 보유 대신 투자했으면 벌었을 수익률
    cash_opportunity_cost_annual: float = 0.06


# ══════════════════════════════════════════════
# Result
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class ExecutionHaircutResult:
    """실행 마찰 적용 결과."""
    # 원본
    base_mult_after_tax: float
    base_net_pv_krw: float

    # haircut 후
    haircut_mult_after_tax: float
    haircut_net_pv_krw: float

    # 요약
    haircut_factor: float          # < 1이면 실행 마찰로 감소
    total_annual_drag_pct: float   # 연율 총 drag (%)
    n_years: float

    # 항목별 분해 (연율 %)
    slippage_drag_pct: float
    fx_drag_pct: float
    delay_drag_pct: float
    dividend_delay_drag_pct: float
    tax_cash_drag_pct: float

    def summary_text(self) -> str:
        lines = [
            f"═══ Lane D: Execution Haircut ═══",
            f"  기간: {self.n_years:.1f}년",
            f"  원본 배수:   {self.base_mult_after_tax:.3f}x",
            f"  Haircut 후:  {self.haircut_mult_after_tax:.3f}x",
            f"  Haircut:     {(1 - self.haircut_factor) * 100:.2f}%",
            f"",
            f"  ── 항목별 연율 drag ──",
            f"  슬리피지:      {self.slippage_drag_pct:.3f}%",
            f"  FX 스프레드:   {self.fx_drag_pct:.3f}%",
            f"  리밸 지연:     {self.delay_drag_pct:.3f}%",
            f"  배당 재투자:   {self.dividend_delay_drag_pct:.3f}%",
            f"  세금 현금:     {self.tax_cash_drag_pct:.3f}%",
            f"  ────────────────────",
            f"  총 연율 drag:  {self.total_annual_drag_pct:.3f}%",
        ]
        return "\n".join(lines)


# ══════════════════════════════════════════════
# 계산
# ══════════════════════════════════════════════

def apply_haircut(
    result: EngineResult,
    config: Optional[ExecutionHaircutConfig] = None,
) -> ExecutionHaircutResult:
    """EngineResult에 실행 마찰 haircut 적용.

    코어 무관. result를 읽기만 한다.
    """
    if config is None:
        config = ExecutionHaircutConfig()

    n_years = result.n_months / 12.0
    fx_rate = result.reporting_fx_rate if result.reporting_fx_rate > 0 else 1300.0

    # ── 1. 슬리피지 drag (연율 %) ──
    # 매수+매도 각각 slippage_bps → 왕복 = 2 × slippage_bps
    # 연 회전율만큼 적용
    turnover = config.annual_turnover if config.annual_turnover is not None else 0.05
    slippage_drag = (config.slippage_bps / 10_000) * 2 * turnover * 100  # → %

    # ── 2. FX 스프레드 drag (연율 %) ──
    # 스프레드는 새 입금(환전)에만 적용. 기존 보유분은 이미 환전 완료.
    # annual_contrib_ratio = 연 납입액 / 평균 PV (DCA에서 시간이 갈수록 작아짐)
    if result.invested_usd > 0 and result.gross_pv_usd > 0 and n_years > 0:
        annual_contrib = result.invested_usd / n_years
        avg_pv = (result.invested_usd + result.gross_pv_usd) / 2  # 대략 중간값
        contrib_ratio = annual_contrib / avg_pv
    else:
        contrib_ratio = 1.0
    fx_drag = (config.fx_spread_krw / fx_rate) * config.fx_trades_per_year * contrib_ratio * 100

    # ── 3. 리밸 지연 drag (연율 %) ──
    # 리밸 지연의 비용 = 목표 비중에서 벗어난 기간의 tracking variance
    # 보수적 근사: daily_variance × delay_days × rebal_freq / 252
    # (분산 기반이라 크기가 작음 — 지연은 방향 중립이므로)
    daily_var = config.daily_vol ** 2
    delay_drag = daily_var * config.rebalance_delay_days * config.rebalances_per_year / 252.0 * 100

    # ── 4. 배당 재투자 지연 drag (연율 %) ──
    # 배당수익률 추정
    if config.dividend_yield_annual is not None:
        div_yield = config.dividend_yield_annual
    else:
        # EngineResult에서 추정
        total_div = sum(a.dividend_gross_usd for a in result.accounts)
        if result.gross_pv_usd > 0 and n_years > 0:
            div_yield = (total_div / n_years) / result.gross_pv_usd
        else:
            div_yield = 0.0

    # 배당 지급 후 재투자까지 idle 기간의 기회비용
    div_delay_drag = div_yield * (config.dividend_reinvest_delay_days / 365.0) * \
                     config.cash_opportunity_cost_annual * 100  # → %

    # ── 5. 세금 납부 현금 drag (연율 %) ──
    # 연간 평균 세금 납부액이 PV 대비 차지하는 비율 × 보유 기간 기회비용
    if result.gross_pv_usd > 0 and n_years > 0:
        annual_tax_usd = (result.tax.total_paid_krw / fx_rate) / n_years
        tax_pv_ratio = annual_tax_usd / result.gross_pv_usd
    else:
        tax_pv_ratio = 0.0
    tax_cash_drag = tax_pv_ratio * (config.tax_cash_drag_months / 12.0) * \
                    config.cash_opportunity_cost_annual * 100  # → %

    # ── 합산 ──
    total_annual_drag_pct = (slippage_drag + fx_drag + delay_drag +
                             div_delay_drag + tax_cash_drag)

    # haircut factor: (1 - annual_drag)^n_years
    haircut_factor = (1 - total_annual_drag_pct / 100.0) ** n_years
    haircut_factor = max(0.0, haircut_factor)  # 음수 방지

    # 적용
    base_mult = result.mult_after_tax
    haircut_mult = base_mult * haircut_factor
    haircut_net = result.net_pv_krw * haircut_factor

    return ExecutionHaircutResult(
        base_mult_after_tax=base_mult,
        base_net_pv_krw=result.net_pv_krw,
        haircut_mult_after_tax=haircut_mult,
        haircut_net_pv_krw=haircut_net,
        haircut_factor=haircut_factor,
        total_annual_drag_pct=total_annual_drag_pct,
        n_years=n_years,
        slippage_drag_pct=slippage_drag,
        fx_drag_pct=fx_drag,
        delay_drag_pct=delay_drag,
        dividend_delay_drag_pct=div_delay_drag,
        tax_cash_drag_pct=tax_cash_drag,
    )
