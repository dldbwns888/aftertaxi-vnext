# -*- coding: utf-8 -*-
"""
validation/robustness.py — 강건성 검증 (순수 함수)
===================================================
quant-v5 validation.py v6.0에서 이식.

  10. CPCV (Combinatorial Purged Cross-Validation) — Lopez de Prado 2018
  11. PBO (Probability of Backtest Overfitting) — Bailey/Lopez de Prado 2014
"""
from __future__ import annotations

from itertools import combinations
from typing import Callable, Dict, List, Optional

import numpy as np

from aftertaxi.validation.reports import CheckResult, Grade


def run_robustness_checks(
    excess_returns: np.ndarray,
    returns_matrix: Optional[np.ndarray] = None,
    n_cpcv_groups: int = 10,
    n_cpcv_test: int = 2,
    purge_months: int = 3,
    pbo_splits: int = 8,
) -> List[CheckResult]:
    """강건성 검증 전체 실행."""
    er = np.asarray(excess_returns, dtype=float)
    checks = [
        check_cpcv(er, n_groups=n_cpcv_groups, n_test_groups=n_cpcv_test,
                   purge_months=purge_months),
    ]
    if returns_matrix is not None:
        checks.append(check_pbo(np.asarray(returns_matrix, dtype=float), S=pbo_splits))
    return checks


# ══════════════════════════════════════════════
# 10. CPCV
# ══════════════════════════════════════════════

def check_cpcv(
    excess_returns: np.ndarray,
    n_groups: int = 10,
    n_test_groups: int = 2,
    purge_months: int = 3,
    min_pct_positive: float = 70.0,
) -> CheckResult:
    """Combinatorial Purged Cross-Validation.

    시간 블록 조합으로 OOS Sharpe 분포를 구하고,
    OOS Sharpe > 0 비율이 min_pct_positive% 이상이면 PASS.
    """
    er = np.asarray(excess_returns, dtype=float)
    T = len(er)
    group_size = T // n_groups

    if group_size < 6:
        return CheckResult(
            name="cpcv", grade=Grade.WARN, value=0.0,
            threshold=min_pct_positive,
            detail=f"데이터 부족: T={T}, groups={n_groups}",
        )

    boundaries = [(g * group_size, min((g + 1) * group_size, T))
                  for g in range(n_groups)]

    combos = list(combinations(range(n_groups), n_test_groups))
    rng = np.random.default_rng(42)
    max_paths = 300
    if len(combos) > max_paths:
        combos = [combos[i] for i in rng.choice(len(combos), max_paths, replace=False)]

    oos_sharpes = []
    for test_groups in combos:
        test_set = set()
        purge_set = set()
        for tg in test_groups:
            s, e = boundaries[tg]
            test_set.update(range(s, e))
            purge_set.update(range(max(0, s - purge_months), min(T, e + purge_months)))

        train_idx = sorted([i for i in range(T) if i not in test_set and i not in purge_set])
        test_idx = sorted(test_set)

        if len(train_idx) < 12 or len(test_idx) < 6:
            continue

        oos_er = er[test_idx]
        sr = np.mean(oos_er) / np.std(oos_er) * np.sqrt(12) if np.std(oos_er) > 1e-8 else 0.0
        oos_sharpes.append(sr)

    if len(oos_sharpes) == 0:
        return CheckResult(
            name="cpcv", grade=Grade.WARN, value=0.0,
            threshold=min_pct_positive, detail="유효 경로 없음",
        )

    oos_arr = np.array(oos_sharpes)
    pct_pos = float(np.mean(oos_arr > 0) * 100)
    mean_sr = float(np.mean(oos_arr))
    ci_lo = float(np.percentile(oos_arr, 2.5))
    ci_hi = float(np.percentile(oos_arr, 97.5))

    if pct_pos >= min_pct_positive:
        grade = Grade.PASS
    elif pct_pos >= 50:
        grade = Grade.WARN
    else:
        grade = Grade.FAIL

    detail = (f"{len(oos_sharpes)}경로 | OOS SR={mean_sr:.3f} ± {np.std(oos_arr):.3f} | "
              f"SR>0: {pct_pos:.0f}% | 95%CI=[{ci_lo:.3f}, {ci_hi:.3f}]")

    return CheckResult(
        name="cpcv", grade=grade, value=pct_pos, threshold=min_pct_positive, detail=detail,
    )


# ══════════════════════════════════════════════
# 11. PBO
# ══════════════════════════════════════════════

def check_pbo(
    returns_matrix: np.ndarray,
    S: int = 8,
    max_pbo: float = 0.50,
    metric_func: Optional[Callable] = None,
) -> CheckResult:
    """Probability of Backtest Overfitting.

    returns_matrix: (T, N) — N개 전략 변형의 T개월 수익률.
    IS에서 최고인 전략이 OOS에서 하위 절반에 있는 확률 = PBO.
    PBO < 50%이면 과적합 아님.
    """
    M = np.asarray(returns_matrix, dtype=float)
    if M.ndim == 1:
        M = M.reshape(-1, 1)
    T, N = M.shape

    if metric_func is None:
        def metric_func(x):
            x = np.asarray(x)
            return np.mean(x) / np.std(x) * np.sqrt(12) if np.std(x) > 1e-8 else 0.0

    n_blocks = 2 * S
    block_size = T // n_blocks
    if block_size < 2 or N < 2:
        return CheckResult(
            name="pbo", grade=Grade.WARN, value=0.5,
            threshold=max_pbo,
            detail=f"데이터/전략 부족: T={T}, N={N}, block={block_size}",
        )

    blocks = []
    for b in range(n_blocks):
        start = b * block_size
        end = start + block_size if b < n_blocks - 1 else T
        blocks.append(M[start:end])

    all_indices = list(range(n_blocks))
    combos = list(combinations(all_indices, S))
    rng = np.random.default_rng(42)
    max_combos = 500
    if len(combos) > max_combos:
        combos = [combos[i] for i in rng.choice(len(combos), max_combos, replace=False)]

    logits = []
    for is_idx in combos:
        oos_idx = tuple(i for i in all_indices if i not in is_idx)
        is_ret = np.concatenate([blocks[i] for i in is_idx], axis=0)
        oos_ret = np.concatenate([blocks[i] for i in oos_idx], axis=0)

        is_perf = np.array([metric_func(is_ret[:, j]) for j in range(N)])
        oos_perf = np.array([metric_func(oos_ret[:, j]) for j in range(N)])

        best_is = np.argmax(is_perf)
        oos_rank = np.sum(oos_perf >= oos_perf[best_is])
        rel_rank = (oos_rank - 1) / max(N - 1, 1)
        logit = np.log(max(rel_rank, 1e-6) / max(1 - rel_rank, 1e-6))
        logits.append(logit)

    logits = np.array(logits)
    pbo_val = float(np.mean(logits > 0)) if len(logits) > 0 else 0.5

    if pbo_val < max_pbo:
        grade = Grade.PASS
        detail = f"PBO={pbo_val:.1%} ({len(combos)}조합, {N}전략) — 과적합 아님"
    else:
        grade = Grade.WARN
        detail = f"PBO={pbo_val:.1%} ({len(combos)}조합, {N}전략) — 과적합 경고"

    return CheckResult(
        name="pbo", grade=grade, value=pbo_val, threshold=max_pbo, detail=detail,
    )
