# -*- coding: utf-8 -*-
"""
lab/strategy_builder/pipeline.py — Strategy Builder 전체 파이프라인
==================================================================
생성 → 스케줄 → 백테스트 → 1차 필터 → validation → 리포트.

안전장치:
  - 리포트 첫 줄 = search budget (생존율)
  - baseline 강제 비교
  - DSR n_trials = 총 생성 수
  - verdict 기본값 = "rejected"
  - source = "strategy_builder"

코어 수정: 0줄.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.lab.strategy_builder.genome import (
    StrategyGenome, genome_to_weight_schedule, count_switches,
)
from aftertaxi.lab.strategy_builder.generator import (
    GeneratorConfig, generate_genomes,
)
from aftertaxi.lab.strategy_builder.signal_runner import run_signal_backtest


# ══════════════════════════════════════════════
# DTO
# ══════════════════════════════════════════════

@dataclass
class CandidateEntry:
    """단일 후보 결과."""
    genome: StrategyGenome
    result: EngineResult
    n_switches: int
    verdict: str = "rejected"       # rejected / research_candidate / finalist

    @property
    def mult_after_tax(self) -> float:
        return self.result.mult_after_tax

    @property
    def tax_drag(self) -> float:
        return self.result.tax_drag

    @property
    def mdd(self) -> float:
        return self.result.mdd

    def summary_line(self) -> str:
        return (
            f"{self.genome.label[:55]:<55} | "
            f"{self.mult_after_tax:.3f}x | "
            f"MDD={self.mdd:.1%} | "
            f"tax_drag={self.tax_drag:.1%} | "
            f"sw={self.n_switches} | "
            f"{self.verdict}"
        )


@dataclass
class PipelineConfig:
    """파이프라인 설정."""
    generator: GeneratorConfig

    # 계좌 설정
    monthly_usd: float = 1000.0
    account_type: str = "TAXABLE"
    rebalance_mode: str = "FULL"

    # 1차 필터
    max_mdd: float = -0.80          # MDD 하한
    max_switches_per_year: float = 12.0  # 연간 최대 전환 수
    max_tax_drag: float = 0.50      # 세금 drag 상한

    # validation
    enable_validation: bool = True
    dsr_significance: float = 0.05


@dataclass
class PipelineReport:
    """파이프라인 결과 리포트.

    첫 줄은 반드시 search budget.
    """
    config: PipelineConfig

    # search budget (정직하게)
    n_generated: int = 0
    n_valid_structure: int = 0
    n_ran: int = 0
    n_after_baseline: int = 0
    n_after_fast_filter: int = 0
    n_after_validation: int = 0

    # baseline
    baseline_mult: float = 0.0
    baseline_tax: float = 0.0

    # 후보
    finalists: List[CandidateEntry] = field(default_factory=list)
    all_mults: np.ndarray = field(default_factory=lambda: np.array([]))

    @property
    def survival_rate(self) -> float:
        if self.n_generated == 0:
            return 0.0
        return self.n_after_validation / self.n_generated

    def summary_text(self) -> str:
        lines = [
            "═══ Strategy Builder Report ═══",
            "",
            f"  Search budget: {self.n_generated}개 생성 → "
            f"{self.n_after_validation}개 생존 "
            f"(생존율 {self.survival_rate:.1%})",
            "",
            f"  파이프라인:",
            f"    생성:          {self.n_generated}",
            f"    구조 유효:     {self.n_valid_structure}",
            f"    백테스트 완료: {self.n_ran}",
            f"    baseline 통과: {self.n_after_baseline}",
            f"    필터 통과:     {self.n_after_fast_filter}",
            f"    validation:    {self.n_after_validation}",
            "",
            f"  Baseline (SPY B&H): {self.baseline_mult:.3f}x 세후, "
            f"tax={self.baseline_tax/1e6:.1f}M KRW",
        ]

        if self.all_mults.size > 0:
            lines.append("")
            lines.append(
                f"  전체 분포: "
                f"median={np.median(self.all_mults):.3f}x, "
                f"p5={np.percentile(self.all_mults, 5):.3f}x, "
                f"p95={np.percentile(self.all_mults, 95):.3f}x"
            )

        if self.finalists:
            lines.append("")
            lines.append(
                f"  연구 후보 ({len(self.finalists)}개, 자동 등록 아님):"
            )
            for c in self.finalists[:10]:
                lines.append(f"    {c.summary_line()}")
            if len(self.finalists) > 10:
                lines.append(f"    ... 외 {len(self.finalists) - 10}개")
        else:
            lines.append("")
            lines.append("  연구 후보: 없음 (전멸)")

        lines.append("")
        lines.append(
            "  ※ 이 결과는 연구 후보이며 투자 결정의 근거가 아닙니다."
        )
        return "\n".join(lines)


# ══════════════════════════════════════════════
# 파이프라인 실행
# ══════════════════════════════════════════════

def run_pipeline(
    config: PipelineConfig,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
) -> PipelineReport:
    """Strategy Builder 전체 파이프라인.

    순서:
    1. generate_genomes → N개 (구조 유효만)
    2. genome → weight_schedule → run_signal_backtest
    3. baseline (SPY B&H) 실행
    4. 1차 필터: baseline gate + MDD + switches + tax_drag
    5. validation gate: DSR (n_trials = 총 생성 수)
    6. 순위: mult_after_tax 기준, 단 plateau 우선
    """
    report = PipelineReport(config=config)
    report.n_generated = config.generator.n_candidates

    # 1. 생성
    genomes = generate_genomes(config.generator)
    report.n_valid_structure = len(genomes)

    # 2. baseline 실행
    baseline_result = _run_baseline(returns, prices, fx_rates, config)
    report.baseline_mult = baseline_result.mult_after_tax
    report.baseline_tax = baseline_result.tax.total_assessed_krw

    # 3. 백테스트 전체 실행
    bt_config = _make_backtest_config(config)
    candidates = []
    all_mults = []

    for genome in genomes:
        try:
            schedule = genome_to_weight_schedule(genome, prices)
            result = run_signal_backtest(
                bt_config, prices, fx_rates,
                weight_schedule=schedule,
            )
            sw = count_switches(schedule)
            entry = CandidateEntry(
                genome=genome, result=result, n_switches=sw,
            )
            candidates.append(entry)
            all_mults.append(result.mult_after_tax)
        except Exception:
            # 실행 실패 → 폐기
            all_mults.append(0.0)

    report.n_ran = len(candidates)
    report.all_mults = np.array(all_mults)

    # 4. 1차 필터
    survivors = _fast_filter(candidates, baseline_result, config)
    report.n_after_baseline = sum(
        1 for c in candidates
        if c.mult_after_tax >= baseline_result.mult_after_tax
    )
    report.n_after_fast_filter = len(survivors)

    # 5. validation gate
    if config.enable_validation and survivors:
        validated = _validation_gate(
            survivors,
            returns=returns,
            baseline_result=baseline_result,
            n_total_generated=config.generator.n_candidates,
            significance=config.dsr_significance,
        )
    else:
        validated = survivors

    report.n_after_validation = len(validated)

    # 6. 순위 + verdict 업데이트
    validated.sort(key=lambda c: c.mult_after_tax, reverse=True)
    for c in validated:
        c.verdict = "research_candidate"
    if validated:
        validated[0].verdict = "finalist"

    report.finalists = validated
    return report


# ══════════════════════════════════════════════
# 내부 함수
# ══════════════════════════════════════════════

def _run_baseline(
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    config: PipelineConfig,
) -> EngineResult:
    """SPY B&H baseline 실행."""
    # prices에 SPY가 있으면 사용, 없으면 첫 자산
    asset = "SPY" if "SPY" in prices.columns else prices.columns[0]
    baseline_config = BacktestConfig(
        accounts=[AccountConfig(
            "baseline", AccountType.TAXABLE, config.monthly_usd,
        )],
        strategy=StrategyConfig("baseline", {asset: 1.0}),
    )
    return run_backtest(
        baseline_config, returns=returns, prices=prices, fx_rates=fx_rates,
    )


def _make_backtest_config(config: PipelineConfig) -> BacktestConfig:
    """파이프라인 설정 → BacktestConfig."""
    acct_type = (
        AccountType.TAXABLE
        if config.account_type == "TAXABLE"
        else AccountType.ISA
    )
    rebal = RebalanceMode(config.rebalance_mode)
    return BacktestConfig(
        accounts=[AccountConfig(
            "lab", acct_type, config.monthly_usd,
            rebalance_mode=rebal,
        )],
        # strategy weights는 signal_runner에서 무시됨 (schedule 사용)
        # 단 fallback용으로 첫 자산 100%
        strategy=StrategyConfig("lab", {"_placeholder": 1.0}),
    )


def _fast_filter(
    candidates: List[CandidateEntry],
    baseline: EngineResult,
    config: PipelineConfig,
) -> List[CandidateEntry]:
    """1차 필터. 저비용, 백테스트 결과만으로 판단."""
    survivors = []
    n_months = baseline.n_months
    n_years = max(n_months / 12, 1)

    for c in candidates:
        # baseline gate
        if c.mult_after_tax < baseline.mult_after_tax:
            continue
        # MDD gate
        if c.mdd < config.max_mdd:
            continue
        # switches gate (연간 기준)
        annual_switches = c.n_switches / n_years
        if annual_switches > config.max_switches_per_year:
            continue
        # tax drag gate
        if c.tax_drag > config.max_tax_drag:
            continue

        survivors.append(c)

    return survivors


def _validation_gate(
    candidates: List[CandidateEntry],
    returns: pd.DataFrame,
    baseline_result: EngineResult,
    n_total_generated: int,
    significance: float = 0.05,
) -> List[CandidateEntry]:
    """validation 게이트. DSR 기반 다중 비교 보정.

    n_trials = 총 생성 수 (1차 필터 후가 아님).
    """
    try:
        from aftertaxi.validation.statistical import check_dsr
    except ImportError:
        # validation 모듈 없으면 필터 없이 통과
        return candidates

    # baseline monthly values를 벤치마크로 사용
    bench_mv = baseline_result.monthly_values
    validated = []

    for c in candidates:
        mv = c.result.monthly_values
        min_len = min(len(mv), len(bench_mv))
        if min_len < 12:
            continue

        # excess returns 계산
        strat_returns = np.diff(mv[:min_len]) / mv[:min_len - 1]
        bench_returns = np.diff(bench_mv[:min_len]) / bench_mv[:min_len - 1]
        # 0 방지
        strat_returns = np.nan_to_num(strat_returns, nan=0.0)
        bench_returns = np.nan_to_num(bench_returns, nan=0.0)
        excess = strat_returns - bench_returns

        if len(excess) < 12:
            continue

        # DSR check (n_trials = 총 생성 수)
        try:
            dsr_result = check_dsr(
                excess_returns=excess,
                n_trials=n_total_generated,
            )
            if dsr_result.passed:
                validated.append(c)
        except Exception:
            # DSR 계산 실패 → 보수적으로 폐기
            continue

    return validated
