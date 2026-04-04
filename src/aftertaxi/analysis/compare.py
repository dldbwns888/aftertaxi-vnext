# -*- coding: utf-8 -*-
"""
workbench/compare.py — 멀티 전략 비교 리포트 + 통계 검정
========================================================
EngineResult 2개 이상 → 비교 테이블 + 우열 판정.

new capability: 코어 무관. EngineResult를 읽기만 한다.

사용법:
  from aftertaxi.workbench.compare import compare_strategies, ComparisonReport

  report = compare_strategies([result_a, result_b], names=["Q60S40", "SPY"])
  print(report.summary_text())
  print(report.winner)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from aftertaxi.core.contracts import EngineResult


@dataclass
class StrategyMetrics:
    """단일 전략 핵심 지표."""
    name: str
    mult_pre_tax: float
    mult_after_tax: float
    mdd: float
    invested_usd: float
    gross_pv_usd: float
    net_pv_krw: float
    tax_drag_pct: float
    n_months: int
    # 월간 수익률 통계 (monthly_values에서 계산)
    annualized_return: float = 0.0
    annualized_vol: float = 0.0
    sharpe_ratio: float = 0.0


@dataclass
class PairwiseTest:
    """두 전략 간 통계 검정 결과."""
    strategy_a: str
    strategy_b: str
    test_name: str
    statistic: float
    p_value: float
    significant: bool  # p < 0.05
    detail: str = ""


@dataclass
class ComparisonReport:
    """멀티 전략 비교 리포트."""
    metrics: List[StrategyMetrics]
    pairwise_tests: List[PairwiseTest] = field(default_factory=list)

    @property
    def winner_pre_tax(self) -> str:
        return max(self.metrics, key=lambda m: m.mult_pre_tax).name

    @property
    def winner_after_tax(self) -> str:
        return max(self.metrics, key=lambda m: m.mult_after_tax).name

    @property
    def winner(self) -> str:
        """세후 기준 우승."""
        return self.winner_after_tax

    def rank_table(self) -> List[dict]:
        """세후 배수 기준 랭킹 테이블."""
        ranked = sorted(self.metrics, key=lambda m: m.mult_after_tax, reverse=True)
        return [
            {
                "rank": i + 1,
                "name": m.name,
                "mult_pre_tax": m.mult_pre_tax,
                "mult_after_tax": m.mult_after_tax,
                "mdd": m.mdd,
                "tax_drag": m.tax_drag_pct,
                "sharpe": m.sharpe_ratio,
            }
            for i, m in enumerate(ranked)
        ]

    def summary_text(self) -> str:
        lines = [f"═══ 전략 비교 ({len(self.metrics)}개) ═══"]
        for r in self.rank_table():
            lines.append(
                f"  #{r['rank']} {r['name']:15s} "
                f"세전 {r['mult_pre_tax']:.2f}x  세후 {r['mult_after_tax']:.2f}x  "
                f"MDD {r['mdd']:.1%}  세금drag {r['tax_drag']:.1f}%  "
                f"SR {r['sharpe']:.2f}"
            )
        lines.append(f"  → 세후 우승: {self.winner}")

        if self.pairwise_tests:
            lines.append(f"\n  ── 통계 검정 ──")
            for t in self.pairwise_tests:
                sig = "✓" if t.significant else "✗"
                lines.append(
                    f"  {t.strategy_a} vs {t.strategy_b}: "
                    f"{t.test_name} p={t.p_value:.4f} {sig}"
                )

        return "\n".join(lines)


# ══════════════════════════════════════════════
# 지표 추출
# ══════════════════════════════════════════════

def _extract_metrics(result: EngineResult, name: str) -> StrategyMetrics:
    """EngineResult → StrategyMetrics."""
    mv = result.monthly_values
    tax_drag = result.tax_drag * 100

    # 월간 수익률
    ann_ret = 0.0
    ann_vol = 0.0
    sharpe = 0.0
    if len(mv) > 1:
        monthly_ret = np.diff(mv) / np.where(mv[:-1] > 0, mv[:-1], 1.0)
        monthly_ret = monthly_ret[np.isfinite(monthly_ret)]
        if len(monthly_ret) > 2:
            ann_ret = float(np.mean(monthly_ret) * 12)
            ann_vol = float(np.std(monthly_ret) * np.sqrt(12))
            sharpe = float(ann_ret / ann_vol) if ann_vol > 1e-8 else 0.0

    return StrategyMetrics(
        name=name,
        mult_pre_tax=result.mult_pre_tax,
        mult_after_tax=result.mult_after_tax,
        mdd=result.mdd,
        invested_usd=result.invested_usd,
        gross_pv_usd=result.gross_pv_usd,
        net_pv_krw=result.net_pv_krw,
        tax_drag_pct=tax_drag,
        n_months=result.n_months,
        annualized_return=ann_ret,
        annualized_vol=ann_vol,
        sharpe_ratio=sharpe,
    )


# ══════════════════════════════════════════════
# 통계 검정 (#5)
# ══════════════════════════════════════════════

def _pairwise_ttest(
    result_a: EngineResult, result_b: EngineResult,
    name_a: str, name_b: str,
) -> Optional[PairwiseTest]:
    """두 전략 월간 수익률 paired t-test."""
    mv_a, mv_b = result_a.monthly_values, result_b.monthly_values
    min_len = min(len(mv_a), len(mv_b))
    if min_len < 3:
        return None

    ret_a = np.diff(mv_a[:min_len]) / np.where(mv_a[:min_len - 1] > 0, mv_a[:min_len - 1], 1.0)
    ret_b = np.diff(mv_b[:min_len]) / np.where(mv_b[:min_len - 1] > 0, mv_b[:min_len - 1], 1.0)

    diff = ret_a - ret_b
    diff = diff[np.isfinite(diff)]
    if len(diff) < 3:
        return None

    from scipy import stats
    t_stat, p_val = stats.ttest_1samp(diff, 0)

    return PairwiseTest(
        strategy_a=name_a,
        strategy_b=name_b,
        test_name="paired_ttest",
        statistic=float(t_stat),
        p_value=float(p_val),
        significant=p_val < 0.05,
        detail=f"n={len(diff)}, mean_diff={np.mean(diff):.6f}",
    )


def _pairwise_wilcoxon(
    result_a: EngineResult, result_b: EngineResult,
    name_a: str, name_b: str,
) -> Optional[PairwiseTest]:
    """두 전략 월간 수익률 Wilcoxon signed-rank test (비모수)."""
    mv_a, mv_b = result_a.monthly_values, result_b.monthly_values
    min_len = min(len(mv_a), len(mv_b))
    if min_len < 10:
        return None

    ret_a = np.diff(mv_a[:min_len]) / np.where(mv_a[:min_len - 1] > 0, mv_a[:min_len - 1], 1.0)
    ret_b = np.diff(mv_b[:min_len]) / np.where(mv_b[:min_len - 1] > 0, mv_b[:min_len - 1], 1.0)

    diff = ret_a - ret_b
    diff = diff[np.isfinite(diff)]
    # 0인 차이 제거 (Wilcoxon 요구)
    diff = diff[np.abs(diff) > 1e-10]
    if len(diff) < 10:
        return None

    from scipy import stats
    try:
        stat, p_val = stats.wilcoxon(diff)
    except ValueError:
        return None

    return PairwiseTest(
        strategy_a=name_a,
        strategy_b=name_b,
        test_name="wilcoxon",
        statistic=float(stat),
        p_value=float(p_val),
        significant=p_val < 0.05,
        detail=f"n={len(diff)}",
    )


# ══════════════════════════════════════════════
# 메인 함수
# ══════════════════════════════════════════════

def compare_strategies(
    results: List[EngineResult],
    names: Optional[List[str]] = None,
    include_tests: bool = True,
) -> ComparisonReport:
    """멀티 전략 비교.

    Parameters
    ----------
    results : EngineResult 리스트
    names : 전략 이름 리스트 (None이면 strategy_0, 1, ...)
    include_tests : True면 pairwise 통계 검정 추가
    """
    if names is None:
        names = [f"strategy_{i}" for i in range(len(results))]

    if len(results) != len(names):
        raise ValueError(f"results({len(results)})와 names({len(names)}) 길이 불일치")

    metrics = [_extract_metrics(r, n) for r, n in zip(results, names)]

    pairwise = []
    if include_tests and len(results) >= 2:
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                t = _pairwise_ttest(results[i], results[j], names[i], names[j])
                if t:
                    pairwise.append(t)
                w = _pairwise_wilcoxon(results[i], results[j], names[i], names[j])
                if w:
                    pairwise.append(w)

    return ComparisonReport(metrics=metrics, pairwise_tests=pairwise)
