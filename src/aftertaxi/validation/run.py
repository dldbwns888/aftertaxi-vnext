# -*- coding: utf-8 -*-
"""
validation/run.py — 검증 스위트 오케스트레이터
===============================================
basic + statistical + stability를 한 번에 실행.
무거운 검증(Bootstrap, Permutation)만 선택적 병렬화.

사용법:
  report = run_validation_suite(
      result=engine_result,
      excess_returns=er,
      strategy_name="Q60S40",
      n_jobs=2,
  )
  print(report.summary_text())
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np

from aftertaxi.core.contracts import EngineResult
from aftertaxi.validation.reports import CheckResult, ValidationReport


def run_validation_suite(
    result: Optional[EngineResult] = None,
    excess_returns: Optional[np.ndarray] = None,
    bench_returns: Optional[np.ndarray] = None,
    strategy_name: str = "strategy",
    n_trials: int = 1,
    benchmark_sharpe: float = 0.0,
    is_oos_split: Optional[int] = None,
    n_jobs: int = 1,
) -> ValidationReport:
    """전체 검증 스위트 실행.

    Parameters
    ----------
    result : EngineResult (basic checks용)
    excess_returns : 월간 초과수익률 (statistical + stability용)
    bench_returns : 벤치마크 수익률 (permutation용)
    strategy_name : 전략명
    n_trials : 시도한 변형 수 (DSR용)
    benchmark_sharpe : PSR 비교 기준
    is_oos_split : IS/OOS 분할 인덱스
    n_jobs : 병렬 워커 수 (1이면 순차)
    """
    report = ValidationReport(strategy_name=strategy_name)

    # 1. Basic checks (빠름, 항상 순차)
    if result is not None:
        from aftertaxi.validation.basic import run_basic_checks
        report.checks.extend(run_basic_checks(result))

    if excess_returns is None:
        return report

    er = np.asarray(excess_returns, dtype=float)

    # 2. 빠른 검증 (순차)
    from aftertaxi.validation.statistical import check_dsr, check_psr, check_cusum
    report.checks.append(check_dsr(er, n_trials))
    report.checks.append(check_psr(er, benchmark_sharpe))
    report.checks.append(check_cusum(er))

    # 3. 무거운 검증 (선택적 병렬)
    heavy_tasks = _build_heavy_tasks(er, bench_returns)

    if n_jobs != 1 and len(heavy_tasks) > 1:
        from joblib import Parallel, delayed
        heavy_results = Parallel(n_jobs=n_jobs)(
            delayed(fn)(*args, **kwargs) for fn, args, kwargs in heavy_tasks
        )
    else:
        heavy_results = [fn(*args, **kwargs) for fn, args, kwargs in heavy_tasks]

    report.checks.extend(heavy_results)

    # 4. 안정성 검증 (순차, 빠름)
    from aftertaxi.validation.stability import (
        check_rolling_sharpe, check_walk_forward, check_is_oos_decay,
    )
    report.checks.append(check_rolling_sharpe(er))
    report.checks.append(check_walk_forward(er))
    if is_oos_split is not None:
        report.checks.append(check_is_oos_decay(er, is_oos_split))

    return report


def _build_heavy_tasks(er, bench_returns):
    """무거운 검증 태스크 목록. (fn, args, kwargs) 튜플."""
    from aftertaxi.validation.statistical import check_bootstrap_sharpe, check_permutation

    tasks = [
        (check_bootstrap_sharpe, (er,), {}),
    ]
    if bench_returns is not None:
        tasks.append(
            (check_permutation, (er, np.asarray(bench_returns, dtype=float)), {}),
        )
    return tasks
