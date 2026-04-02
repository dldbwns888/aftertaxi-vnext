# -*- coding: utf-8 -*-
"""
lane_a/compare.py — adjusted vs explicit dividend 비교
======================================================
같은 구간, 같은 전략, 같은 설정으로 두 경로를 돌리고
결과 차이를 정량화.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, EngineResult, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.attribution import ResultAttribution, build_attribution
from aftertaxi.lanes.lane_a.loader import load_lane_a, load_lane_a_explicit


@dataclass
class ComparisonResult:
    """adjusted vs explicit 비교 결과."""
    # 설정
    tickers: List[str]
    start: str
    end: str
    strategy_name: str
    monthly_contribution: float

    # adjusted path
    adj_result: EngineResult
    adj_attribution: ResultAttribution

    # explicit path
    exp_result: EngineResult
    exp_attribution: ResultAttribution

    # 배당 schedule 정보
    exp_annual_yields: Dict[str, float]

    def delta_table(self) -> List[Dict]:
        """비교 항목별 delta 계산."""
        rows = []

        def _row(label, adj_val, exp_val, unit="", lower_better=False):
            delta = exp_val - adj_val
            if adj_val != 0:
                pct = delta / abs(adj_val) * 100
            else:
                pct = 0.0
            rows.append({
                "항목": label,
                "adjusted": adj_val,
                "explicit": exp_val,
                "차이": delta,
                "차이%": pct,
                "단위": unit,
            })

        ar, er = self.adj_result, self.exp_result
        aa, ea = self.adj_attribution, self.exp_attribution

        _row("세전 PV (USD)", ar.gross_pv_usd, er.gross_pv_usd, "USD")
        _row("세후 PV (KRW)", ar.net_pv_krw, er.net_pv_krw, "KRW")
        _row("세전 배수", ar.mult_pre_tax, er.mult_pre_tax, "x")
        _row("세후 배수", ar.mult_after_tax, er.mult_after_tax, "x")
        _row("MDD", ar.mdd, er.mdd, "%")
        _row("세금 총합 (KRW)", aa.total_tax_assessed_krw, ea.total_tax_assessed_krw, "KRW", True)
        _row("양도세 (KRW)", aa.total_capital_gains_tax_krw, ea.total_capital_gains_tax_krw, "KRW", True)
        _row("배당세 (KRW)", aa.total_dividend_tax_krw, ea.total_dividend_tax_krw, "KRW", True)
        _row("건보료 (KRW)", aa.total_health_insurance_krw, ea.total_health_insurance_krw, "KRW", True)
        _row("거래비용 (USD)", aa.total_transaction_cost_usd, ea.total_transaction_cost_usd, "USD", True)
        _row("배당 총액 (USD)", aa.total_dividend_gross_usd, ea.total_dividend_gross_usd, "USD")
        _row("배당 원천징수 (USD)", aa.total_dividend_withholding_usd, ea.total_dividend_withholding_usd, "USD", True)
        _row("배당 순액 (USD)", aa.total_dividend_net_usd, ea.total_dividend_net_usd, "USD")

        return rows

    def summary_text(self) -> str:
        """사람이 읽기 쉬운 비교 리포트."""
        lines = [
            f"═══ Lane A Price Mode Comparison ═══",
            f"구간: {self.start} ~ {self.end}",
            f"전략: {self.strategy_name}",
            f"월납입: ${self.monthly_contribution:,.0f}",
            f"배당 yield: {self.exp_annual_yields}",
            "",
        ]

        table = self.delta_table()
        # 헤더
        lines.append(f"{'항목':<20} {'adjusted':>14} {'explicit':>14} {'차이':>14} {'차이%':>8}")
        lines.append("─" * 74)

        for r in table:
            adj_s = f"{r['adjusted']:>13,.2f}"
            exp_s = f"{r['explicit']:>13,.2f}"
            d_s = f"{r['차이']:>+13,.2f}"
            p_s = f"{r['차이%']:>+7.2f}%"
            lines.append(f"{r['항목']:<20} {adj_s} {exp_s} {d_s} {p_s}")

        # 해석
        lines.append("")
        lines.append("═══ 해석 ═══")

        ar, er = self.adj_result, self.exp_result
        aa, ea = self.adj_attribution, self.exp_attribution

        # 세전 PV 차이
        pv_ratio = er.gross_pv_usd / ar.gross_pv_usd if ar.gross_pv_usd > 0 else 0
        if pv_ratio < 0.98:
            lines.append(f"• explicit PV가 {(1-pv_ratio)*100:.1f}% 낮음 — 원천징수 15%가 가격에서 빠져서")
        elif pv_ratio > 1.02:
            lines.append(f"• explicit PV가 {(pv_ratio-1)*100:.1f}% 높음 — 가격 데이터 차이 가능성")
        else:
            lines.append(f"• 세전 PV 차이 {(pv_ratio-1)*100:.1f}% — 유사")

        # 배당 가시성
        if ea.total_dividend_gross_usd > 0 and aa.total_dividend_gross_usd == 0:
            lines.append("• adjusted에서는 배당이 보이지 않음 (가격에 묻힘)")
            lines.append("• explicit에서는 배당 gross/withholding/net이 분리되어 attribution 가능")

        # 세금 차이
        tax_diff = ea.total_tax_assessed_krw - aa.total_tax_assessed_krw
        if abs(tax_diff) > 10000:
            lines.append(f"• 세금 차이: {tax_diff:+,.0f} KRW — 배당세/건보료 경로 차이")

        # caveat
        lines.append("")
        lines.append("═══ Caveats ═══")
        lines.append("• yfinance Close = split-adjusted (v1.2). 버전에 따라 의미 다를 수 있음")
        lines.append("• DividendSchedule은 평균 yield 기반 근사 (분기별 금액 변동 미반영)")
        lines.append("• explicit path의 원천징수가 배당 재투자 수량을 줄여 compound 효과에 영향")

        return "\n".join(lines)


def compare_price_modes(
    tickers: List[str],
    start: str = "2023-01-01",
    end: str = "2024-01-01",
    strategy_name: str = "equal_weight",
    monthly_contribution: float = 1000.0,
    transaction_cost_bps: float = 0.0,
    enable_health_insurance: bool = False,
    cache_dir=None,
) -> ComparisonResult:
    """adjusted vs explicit dividend path 비교 실행.

    같은 구간, 같은 전략, 같은 설정. 가격/배당 입력만 다름.
    """
    weights = {t: 1.0 / len(tickers) for t in tickers}
    strategy = StrategyConfig(strategy_name, weights)

    account = AccountConfig(
        "taxable", AccountType.TAXABLE, monthly_contribution,
        transaction_cost_bps=transaction_cost_bps,
    )

    # ── ADJUSTED path ──
    adj_data = load_lane_a(tickers, start=start, end=end, cache_dir=cache_dir)
    adj_config = BacktestConfig(
        accounts=[account],
        strategy=strategy,
        enable_health_insurance=enable_health_insurance,
        # dividend_schedule 없음 → adjusted close에 배당 포함
    )
    adj_result = run_backtest(
        adj_config,
        returns=adj_data["returns"],
        prices=adj_data["prices"],
        fx_rates=adj_data["fx_rates"],
    )

    # ── EXPLICIT path ──
    exp_data = load_lane_a_explicit(
        tickers, start=start, end=end, cache_dir=cache_dir,
    )
    exp_config = BacktestConfig(
        accounts=[account],
        strategy=strategy,
        dividend_schedule=exp_data.dividend_schedule,
        enable_health_insurance=enable_health_insurance,
    )
    exp_result = run_backtest(
        exp_config,
        returns=exp_data.returns,
        prices=exp_data.prices,
        fx_rates=exp_data.fx_rates,
    )

    return ComparisonResult(
        tickers=tickers,
        start=start,
        end=end,
        strategy_name=strategy_name,
        monthly_contribution=monthly_contribution,
        adj_result=adj_result,
        adj_attribution=build_attribution(adj_result),
        exp_result=exp_result,
        exp_attribution=build_attribution(exp_result),
        exp_annual_yields=exp_data.dividend_schedule.annual_yields,
    )
