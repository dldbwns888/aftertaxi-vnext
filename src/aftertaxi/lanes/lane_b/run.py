# -*- coding: utf-8 -*-
"""
lane_b/run.py — Lane B 실행 + A/B overlap calibration
======================================================
Lane B: 합성 장기역사로 구조 검증.

핵심 제약:
  - Lane B는 독립 진실원이 아님. 합성 오차를 상속.
  - A/B overlap calibration으로 합성-실제 괴리를 정량화.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.lanes.lane_b.synthetic import (
    SyntheticParams, synthesize_leveraged_returns, returns_to_prices,
)


# ══════════════════════════════════════════════
# 데이터 로더
# ══════════════════════════════════════════════

def load_index_data(
    index_ticker: str = "^SP500TR",
    tbill_ticker: str = "^IRX",
    start: str = "1987-01-01",
    end: Optional[str] = None,
) -> dict:
    """장기 지수 + T-bill 월간 데이터.

    Returns
    -------
    dict: index_returns, tbill_rate, index_prices (all monthly)
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance 필요: pip install yfinance")

    # 지수
    raw = yf.download(index_ticker, start=start, end=end, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        idx_monthly = raw["Close"].iloc[:, 0].resample("ME").last().dropna()
    else:
        idx_monthly = raw["Close"].resample("ME").last().dropna()
    idx_returns = idx_monthly.pct_change().dropna()

    # T-bill (annualized yield %)
    raw_tb = yf.download(tbill_ticker, start=start, end=end, progress=False)
    if isinstance(raw_tb.columns, pd.MultiIndex):
        tb_monthly = raw_tb["Close"].iloc[:, 0].resample("ME").mean().dropna()
    else:
        tb_monthly = raw_tb["Close"].resample("ME").mean().dropna()
    tbill_rate = tb_monthly / 100.0  # % → decimal

    # 공통 인덱스
    common = idx_returns.index.intersection(tbill_rate.index)
    idx_returns = idx_returns.loc[common]
    tbill_rate = tbill_rate.loc[common]

    return {
        "index_returns": idx_returns,
        "tbill_rate": tbill_rate,
        "index_prices": idx_monthly,
        "n_months": len(common),
        "start_date": common[0],
        "end_date": common[-1],
    }


# ══════════════════════════════════════════════
# Lane B 실행
# ══════════════════════════════════════════════

def run_lane_b(
    weights: Dict[str, float],
    synthetic_map: Dict[str, SyntheticParams],
    monthly_usd: float = 1000.0,
    start: str = "1987-01-01",
    end: Optional[str] = None,
    fx_rate: float = 1300.0,
    index_ticker: str = "^SP500TR",
    tbill_ticker: str = "^IRX",
    strategy_name: str = "lane_b",
) -> EngineResult:
    """Lane B 합성 역사 백테스트.

    Parameters
    ----------
    weights : {"synthetic_spy": 0.6, "synthetic_2x": 0.4} 등
    synthetic_map : {asset_name: SyntheticParams}
        1x 자산은 SyntheticParams(leverage=1.0, annual_fee=0)
    monthly_usd : 월 납입액 (USD)
    fx_rate : 고정 환율 (합성이므로 실제 FX 불필요, 세금 계산용)
    """
    data = load_index_data(index_ticker, tbill_ticker, start, end)

    # 합성 수익률 생성
    returns_dict = {}
    for name, params in synthetic_map.items():
        syn_ret = synthesize_leveraged_returns(
            data["index_returns"], data["tbill_rate"], params,
        )
        returns_dict[name] = syn_ret

    returns_df = pd.DataFrame(returns_dict).dropna()
    prices_df = returns_df.apply(lambda col: returns_to_prices(col))

    # 고정 FX
    fx_rates = pd.Series(fx_rate, index=returns_df.index)

    config = BacktestConfig(
        accounts=[AccountConfig(
            account_id="taxable",
            account_type=AccountType.TAXABLE,
            monthly_contribution=monthly_usd,
            rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
        )],
        strategy=StrategyConfig(name=strategy_name, weights=weights),
    )

    return run_backtest(config, returns=returns_df, prices=prices_df, fx_rates=fx_rates)


# ══════════════════════════════════════════════
# A/B Overlap Calibration
# ══════════════════════════════════════════════

@dataclass
class OverlapCalibration:
    """A/B 겹침 구간 비교 결과."""
    overlap_months: int
    lane_a_mult: float
    lane_b_mult: float
    gap_mult: float        # B - A
    gap_pct: float         # (B - A) / A × 100
    lane_a_mdd: float
    lane_b_mdd: float

    @property
    def haircut_factor(self) -> float:
        """Lane B 결과에 적용할 할인율. < 1이면 B가 낙관적."""
        if self.lane_b_mult <= 0:
            return 1.0
        return self.lane_a_mult / self.lane_b_mult


def calibrate_overlap(
    lane_a_result: EngineResult,
    lane_b_result: EngineResult,
) -> OverlapCalibration:
    """동일 기간 Lane A vs Lane B 비교."""
    a_mult = lane_a_result.mult_pre_tax
    b_mult = lane_b_result.mult_pre_tax
    gap = b_mult - a_mult
    gap_pct = (gap / a_mult * 100) if a_mult > 0 else 0.0

    return OverlapCalibration(
        overlap_months=min(lane_a_result.n_months, lane_b_result.n_months),
        lane_a_mult=a_mult,
        lane_b_mult=b_mult,
        gap_mult=gap,
        gap_pct=gap_pct,
        lane_a_mdd=lane_a_result.mdd,
        lane_b_mdd=lane_b_result.mdd,
    )


# ══════════════════════════════════════════════
# Structural Analysis (Long-History)
# ══════════════════════════════════════════════

@dataclass
class StructuralReport:
    """Lane B 장기 구조 분석 결과.

    질문: "이 전략이 장기적으로 구조적 생존성이 있는가?"
    """
    total_months: int
    total_mult: float              # 전체 기간 세전 배수
    total_mdd: float

    # 롤링 20년 분석
    rolling_window_months: int
    n_windows: int
    rolling_median_mult: float
    rolling_p5_mult: float
    rolling_p95_mult: float
    rolling_win_rate: float        # mult > 1 비율
    rolling_worst_mult: float
    rolling_mults: np.ndarray      # 전체 배열

    def summary_text(self) -> str:
        return (
            f"═══ Lane B Structural ({self.total_months}mo) ═══\n"
            f"  전체: {self.total_mult:.2f}x, MDD {self.total_mdd:.1%}\n"
            f"  롤링 {self.rolling_window_months // 12}yr: "
            f"중앙 {self.rolling_median_mult:.2f}x, "
            f"5% {self.rolling_p5_mult:.2f}x, "
            f"승률 {self.rolling_win_rate:.0%}, "
            f"최악 {self.rolling_worst_mult:.2f}x\n"
            f"  ({self.n_windows}개 윈도우)"
        )


def run_lane_b_structural(
    weights: Dict[str, float],
    synthetic_map: Dict[str, SyntheticParams],
    monthly_usd: float = 1000.0,
    start: str = "1987-01-01",
    end: Optional[str] = None,
    fx_rate: float = 1300.0,
    rolling_years: int = 20,
    strategy_name: str = "lane_b_structural",
    index_ticker: str = "^SP500TR",
    tbill_ticker: str = "^IRX",
) -> StructuralReport:
    """Lane B 장기 구조 분석.

    전체 기간 백테스트 + 롤링 N년 윈도우 배수 분포.
    """
    # 전체 기간 실행
    full_result = run_lane_b(
        weights=weights,
        synthetic_map=synthetic_map,
        monthly_usd=monthly_usd,
        start=start, end=end,
        fx_rate=fx_rate,
        strategy_name=strategy_name,
        index_ticker=index_ticker,
        tbill_ticker=tbill_ticker,
    )

    # 롤링 윈도우 분석
    mv = full_result.monthly_values
    window = rolling_years * 12
    rolling_mults = []

    if len(mv) > window:
        for i in range(window, len(mv)):
            start_val = mv[i - window]
            end_val = mv[i]
            if start_val > 0:
                invested_in_window = monthly_usd * window
                mult = end_val / (start_val + invested_in_window / 2)  # 근사
                rolling_mults.append(mult)

    if not rolling_mults:
        # 데이터 부족 시 전체 배수만
        rolling_mults = [full_result.mult_pre_tax]

    rm = np.array(rolling_mults)

    return StructuralReport(
        total_months=full_result.n_months,
        total_mult=full_result.mult_pre_tax,
        total_mdd=full_result.mdd,
        rolling_window_months=window,
        n_windows=len(rm),
        rolling_median_mult=float(np.median(rm)),
        rolling_p5_mult=float(np.percentile(rm, 5)),
        rolling_p95_mult=float(np.percentile(rm, 95)),
        rolling_win_rate=float(np.mean(rm > 1.0)),
        rolling_worst_mult=float(np.min(rm)),
        rolling_mults=rm,
    )


# ══════════════════════════════════════════════
# CalibrationReport (2-mode 통합)
# ══════════════════════════════════════════════

@dataclass
class CalibrationReport:
    """Lane B 2-mode 통합 리포트.

    Mode 1 (Overlap): Lane A와 겹치는 구간에서 합성 오차 정량화.
    Mode 2 (Structural): 전체 장기 역사에서 구조적 생존성 평가.
    """
    overlap: Optional[OverlapCalibration] = None
    structural: Optional[StructuralReport] = None

    def summary_text(self) -> str:
        lines = ["═══ Lane B CalibrationReport ═══"]
        if self.overlap:
            lines.append(f"\n  [Overlap] {self.overlap.overlap_months}mo")
            lines.append(f"    A={self.overlap.lane_a_mult:.2f}x, "
                         f"B={self.overlap.lane_b_mult:.2f}x, "
                         f"gap={self.overlap.gap_pct:+.1f}%")
            lines.append(f"    haircut={self.overlap.haircut_factor:.3f}")
        if self.structural:
            lines.append(f"\n  [Structural] {self.structural.total_months}mo")
            lines.append(f"    전체 {self.structural.total_mult:.2f}x")
            lines.append(f"    롤링 {self.structural.rolling_window_months//12}yr: "
                         f"중앙 {self.structural.rolling_median_mult:.2f}x, "
                         f"승률 {self.structural.rolling_win_rate:.0%}")
        return "\n".join(lines)
