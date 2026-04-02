# -*- coding: utf-8 -*-
"""
validation/ — 검증 레이어
=========================
엔진 결과를 받아서 "이 전략이 진짜인지" 평가.
코어를 안 건드리고 밖에서 붙는다.

사용법:
  from aftertaxi.validation import validate

  # 간편 (basic + statistical)
  report = validate(result=result, excess_returns=er)

  # 전체 스위트 (+ stability + heavy, 병렬 지원)
  report = validate(result=result, excess_returns=er, full=True, n_jobs=2)

  print(report.summary_text())
"""
from aftertaxi.validation.reports import ValidationReport, CheckResult, Grade
from aftertaxi.validation.basic import run_basic_checks
from aftertaxi.validation.statistical import run_statistical_checks
from aftertaxi.validation.stability import run_stability_checks
from aftertaxi.validation.run import run_validation_suite


def validate(
    result=None,
    excess_returns=None,
    strategy_name: str = "strategy",
    n_trials: int = 1,
    benchmark_sharpe: float = 0.0,
    bench_returns=None,
    is_oos_split=None,
    full: bool = False,
    n_jobs: int = 1,
) -> ValidationReport:
    """단일 진입점. full=False면 basic+statistical, full=True면 전체 스위트."""
    if full:
        return run_validation_suite(
            result=result,
            excess_returns=excess_returns,
            bench_returns=bench_returns,
            strategy_name=strategy_name,
            n_trials=n_trials,
            benchmark_sharpe=benchmark_sharpe,
            is_oos_split=is_oos_split,
            n_jobs=n_jobs,
        )

    report = ValidationReport(strategy_name=strategy_name)

    if result is not None:
        report.checks.extend(run_basic_checks(result))

    if excess_returns is not None:
        import numpy as np
        report.checks.extend(run_statistical_checks(
            np.asarray(excess_returns),
            n_trials=n_trials,
            benchmark_sharpe=benchmark_sharpe,
            bench_returns=bench_returns,
        ))

    return report
