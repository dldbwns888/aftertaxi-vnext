# -*- coding: utf-8 -*-
"""
validation/statistical.py — 통계적 검증 (순수 함수)
====================================================
quant-v5 validation.py v6.0에서 이식.

변경:
  - Validator class 상태 제거 → 순수 함수
  - print() 제거 → CheckResult 반환
  - self.pro_results 누적 제거 → 개별 결과만
  - 입력: numpy 배열 (월간 초과수익률)
  - 출력: CheckResult (typed, frozen)

포함 도구:
  1. DSR (Deflated Sharpe Ratio) — Bailey & López de Prado
  2. PSR (Probabilistic Sharpe Ratio)
  3. Bootstrap Sharpe CI (Block Bootstrap)
  4. Permutation Test (전략 vs 벤치마크)
  5. CUSUM (구조 변화 감지)
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

from aftertaxi.validation.reports import CheckResult, Grade


def run_statistical_checks(
    excess_returns: np.ndarray,
    n_trials: int = 1,
    benchmark_sharpe: float = 0.0,
    bench_returns: Optional[np.ndarray] = None,
    confidence: float = 0.95,
    n_bootstrap: int = 5000,
) -> List[CheckResult]:
    """통계 검증 전체 실행."""
    er = np.asarray(excess_returns, dtype=float)
    checks = [
        check_dsr(er, n_trials),
        check_psr(er, benchmark_sharpe),
        check_bootstrap_sharpe(er, confidence, n_bootstrap),
    ]
    if bench_returns is not None:
        checks.append(check_permutation(er, np.asarray(bench_returns, dtype=float)))
    checks.append(check_cusum(er))
    return checks


# ══════════════════════════════════════════════
# 1. Deflated Sharpe Ratio (DSR)
# ══════════════════════════════════════════════

def check_dsr(
    excess_returns: np.ndarray,
    n_trials: int = 1,
    significance: float = 0.05,
) -> CheckResult:
    """Deflated Sharpe Ratio.

    시도 횟수(n_trials)를 감안하여 Sharpe가 우연이 아닌지 판정.
    Bailey & López de Prado (2014).

    Parameters
    ----------
    excess_returns : 월간 초과수익률
    n_trials : 시도한 전략 변형 수
    significance : 유의수준 (0.05)
    """
    er = np.asarray(excess_returns, dtype=float)
    T = len(er)
    if T < 12 or np.std(er) < 1e-10:
        return CheckResult(
            name="dsr", grade=Grade.WARN, value=0.0, threshold=significance,
            detail=f"데이터 부족 (T={T}) 또는 분산 0",
        )

    sr = np.mean(er) / np.std(er) * np.sqrt(12)
    sr_m = np.mean(er) / np.std(er)  # 월간 SR
    sk = float(stats.skew(er))
    ku = float(stats.kurtosis(er, fisher=True))

    N = max(int(n_trials), 2)
    # 기대 최대 Sharpe (Euler-Mascheroni 근사)
    emax = (np.sqrt(2 * np.log(N))
            - (np.log(np.pi) + np.log(max(np.log(N), 0.01)))
            / (2 * np.sqrt(2 * np.log(N))))

    # SR 표준오차 (비정규 보정)
    se = np.sqrt((1 - sk * sr_m + (ku / 4) * sr_m**2) / max(T, 1)) * np.sqrt(12)
    se = max(se, 1e-6)

    dsr_stat = (sr - emax) / se
    p_value = 1 - stats.norm.cdf(dsr_stat)

    if p_value < significance:
        grade = Grade.PASS
        detail = f"SR={sr:.3f} > E[max]={emax:.3f}, p={p_value:.4f} (유의)"
    else:
        grade = Grade.WARN
        detail = f"SR={sr:.3f}, E[max]={emax:.3f}, p={p_value:.4f} (비유의, n_trials={N})"

    return CheckResult(
        name="dsr", grade=grade, value=p_value, threshold=significance, detail=detail,
    )


# ══════════════════════════════════════════════
# 2. Probabilistic Sharpe Ratio (PSR)
# ══════════════════════════════════════════════

def check_psr(
    excess_returns: np.ndarray,
    benchmark_sharpe: float = 0.0,
    min_psr: float = 0.95,
) -> CheckResult:
    """Sharpe가 benchmark를 초과할 확률.

    Parameters
    ----------
    benchmark_sharpe : 비교 기준 연율 Sharpe (0이면 "양수인지만 검증")
    min_psr : 최소 요구 PSR (0.95 = 95% 확률)
    """
    er = np.asarray(excess_returns, dtype=float)
    T = len(er)
    if T < 12 or np.std(er) < 1e-10:
        return CheckResult(
            name="psr", grade=Grade.WARN, value=0.0, threshold=min_psr,
            detail=f"데이터 부족 (T={T})",
        )

    sr = np.mean(er) / np.std(er) * np.sqrt(12)
    sr_m = np.mean(er) / np.std(er)
    sk = float(stats.skew(er))
    ku = float(stats.kurtosis(er, fisher=True))

    se = np.sqrt((1 - sk * sr_m + (ku / 4) * sr_m**2) / max(T, 1)) * np.sqrt(12)
    se = max(se, 1e-6)

    psr_val = float(stats.norm.cdf((sr - benchmark_sharpe) / se))

    if psr_val >= min_psr:
        grade = Grade.PASS
    elif psr_val >= 0.80:
        grade = Grade.WARN
    else:
        grade = Grade.FAIL

    detail = f"SR={sr:.3f}, P(SR>{benchmark_sharpe:.2f})={psr_val:.1%}"
    return CheckResult(
        name="psr", grade=grade, value=psr_val, threshold=min_psr, detail=detail,
    )


# ══════════════════════════════════════════════
# 3. Bootstrap Sharpe CI
# ══════════════════════════════════════════════

def check_bootstrap_sharpe(
    excess_returns: np.ndarray,
    confidence: float = 0.95,
    n_bootstrap: int = 5000,
    block_size: int = 12,
) -> CheckResult:
    """Block Bootstrap으로 Sharpe 신뢰구간.

    CI 하한 > 0이면 PASS.
    """
    er = np.asarray(excess_returns, dtype=float)
    T = len(er)
    if T < 24:
        return CheckResult(
            name="bootstrap_sharpe", grade=Grade.WARN, value=0.0, threshold=0.0,
            detail=f"데이터 부족 (T={T})",
        )

    sr_obs = np.mean(er) / np.std(er) * np.sqrt(12) if np.std(er) > 0 else 0.0
    rng = np.random.default_rng(42)
    n_blocks = max(T // block_size, 1)

    vals = []
    for _ in range(n_bootstrap):
        starts = rng.integers(0, max(T - block_size, 1), n_blocks)
        samp = np.concatenate([er[s:s + block_size] for s in starts])[:T]
        if np.std(samp) > 1e-10:
            vals.append(np.mean(samp) / np.std(samp) * np.sqrt(12))

    if len(vals) < 100:
        return CheckResult(
            name="bootstrap_sharpe", grade=Grade.WARN, value=sr_obs, threshold=0.0,
            detail="유효 bootstrap 샘플 부족",
        )

    vals = np.asarray(vals)
    alpha = (1 - confidence) / 2
    ci_lo = float(np.percentile(vals, alpha * 100))
    ci_hi = float(np.percentile(vals, (1 - alpha) * 100))
    prob_pos = float(np.mean(vals > 0))

    if ci_lo > 0:
        grade = Grade.PASS
        detail = f"SR={sr_obs:.3f}, {confidence:.0%} CI=[{ci_lo:.3f}, {ci_hi:.3f}], P(>0)={prob_pos:.1%}"
    elif prob_pos > 0.80:
        grade = Grade.WARN
        detail = f"SR={sr_obs:.3f}, CI=[{ci_lo:.3f}, {ci_hi:.3f}], P(>0)={prob_pos:.1%} (CI에 0 포함)"
    else:
        grade = Grade.FAIL
        detail = f"SR={sr_obs:.3f}, CI=[{ci_lo:.3f}, {ci_hi:.3f}], P(>0)={prob_pos:.1%}"

    return CheckResult(
        name="bootstrap_sharpe", grade=grade, value=ci_lo, threshold=0.0, detail=detail,
    )


# ══════════════════════════════════════════════
# 4. Permutation Test
# ══════════════════════════════════════════════

def check_permutation(
    strat_returns: np.ndarray,
    bench_returns: np.ndarray,
    n_perm: int = 5000,
    significance: float = 0.05,
) -> CheckResult:
    """전략이 벤치마크보다 유의하게 나은지 Permutation으로 검정.

    양측 검정.
    """
    sr = np.asarray(strat_returns, dtype=float)
    br = np.asarray(bench_returns, dtype=float)
    n = min(len(sr), len(br))
    if n < 12:
        return CheckResult(
            name="permutation", grade=Grade.WARN, value=1.0, threshold=significance,
            detail=f"데이터 부족 (n={n})",
        )

    sr = sr[:n]
    br = br[:n]
    obs_diff = float(np.mean(sr) - np.mean(br))

    rng = np.random.default_rng(42)
    cb = np.column_stack([sr, br])
    perm_diffs = np.zeros(n_perm)

    for i in range(n_perm):
        mask = rng.integers(0, 2, n)
        a = np.where(mask == 0, cb[:, 0], cb[:, 1])
        b = np.where(mask == 0, cb[:, 1], cb[:, 0])
        perm_diffs[i] = np.mean(a) - np.mean(b)

    p_two = float(np.mean(np.abs(perm_diffs) >= abs(obs_diff)))

    if p_two < significance:
        grade = Grade.PASS
        detail = f"초과수익 {obs_diff*12*100:.2f}%/yr, p={p_two:.4f} (유의)"
    elif p_two < 0.10:
        grade = Grade.WARN
        detail = f"초과수익 {obs_diff*12*100:.2f}%/yr, p={p_two:.4f} (약한 유의)"
    else:
        grade = Grade.FAIL
        detail = f"초과수익 {obs_diff*12*100:.2f}%/yr, p={p_two:.4f} (비유의)"

    return CheckResult(
        name="permutation", grade=grade, value=p_two, threshold=significance, detail=detail,
    )


# ══════════════════════════════════════════════
# 5. CUSUM (구조 변화 감지)
# ══════════════════════════════════════════════

def check_cusum(excess_returns: np.ndarray) -> CheckResult:
    """CUSUM 검정으로 수익률 구조 변화 감지.

    stat > critical이면 구조 변화 있음 (WARN).
    """
    er = np.asarray(excess_returns, dtype=float)
    T = len(er)
    if T < 24:
        return CheckResult(
            name="cusum", grade=Grade.WARN, value=0.0, threshold=0.0,
            detail=f"데이터 부족 (T={T})",
        )

    mu = np.mean(er)
    cs = np.cumsum(er - mu)
    max_idx = int(np.argmax(np.abs(cs)))
    ts = float(np.max(np.abs(cs)) / (T * np.std(er))) if np.std(er) > 0 else 0.0
    critical = 1.36 / np.sqrt(T)

    has_break = ts > critical

    if has_break:
        before_mean = np.mean(er[:max_idx]) * 12 * 100 if max_idx > 6 else np.mean(er) * 12 * 100
        after_mean = np.mean(er[max_idx:]) * 12 * 100 if max_idx < T - 6 else before_mean
        grade = Grade.WARN
        detail = f"구조 변화 감지 (month {max_idx}): 전 {before_mean:.1f}%/yr → 후 {after_mean:.1f}%/yr"
    else:
        grade = Grade.PASS
        detail = f"안정 (stat={ts:.4f} < critical={critical:.4f})"

    return CheckResult(
        name="cusum", grade=grade, value=ts, threshold=critical, detail=detail,
    )
