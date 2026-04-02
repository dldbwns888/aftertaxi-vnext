# -*- coding: utf-8 -*-
"""
validation/ — 검증 레이어
=========================
엔진 결과를 받아서 "이 전략이 진짜인지" 평가.
코어를 안 건드리고 밖에서 붙는다.

사용법:
  from aftertaxi.validation import validate, run_validation_suite
  
  # 간단 검증
  report = validate(result, excess_returns, strategy_name="Q60S40")
  
  # 전체 스위트 (병렬)
  report = run_validation_suite(result, er, n_jobs=2)
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
) -> ValidationReport:
    """간편 검증. basic + statistical."""
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
