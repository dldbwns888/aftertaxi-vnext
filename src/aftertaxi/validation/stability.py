# -*- coding: utf-8 -*-
"""
validation/stability.py — 안정성 검증 (순수 함수)
==================================================
quant-v5 validation.py에서 이식.
전략 수익률의 시간적 안정성을 평가.

  6. Rolling Sharpe: 이동 창에서 Sharpe가 안정적인지
  7. Walk-Forward: IS/OOS 분할 Sharpe 일관성
  9. IS-OOS Decay: IS→OOS 성과 감쇠율
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from aftertaxi.validation.reports import CheckResult, Grade


def run_stability_checks(
    excess_returns: np.ndarray,
    split_index: Optional[int] = None,
    n_wf_splits: int = 5,
    rolling_window: int = 60,
) -> List[CheckResult]:
    """안정성 검증 전체 실행."""
    er = np.asarray(excess_returns, dtype=float)
    checks = [
        check_rolling_sharpe(er, window=rolling_window),
        check_walk_forward(er, n_splits=n_wf_splits),
    ]
    if split_index is not None:
        checks.append(check_is_oos_decay(er, split_index))
    return checks


# ══════════════════════════════════════════════
# 6. Rolling Sharpe
# ══════════════════════════════════════════════

def check_rolling_sharpe(
    excess_returns: np.ndarray,
    window: int = 60,
    min_pct_positive: float = 60.0,
) -> CheckResult:
    """Rolling Sharpe 분석.

    이동 창에서 Sharpe가 양수인 비율로 안정성 판단.
    """
    er = np.asarray(excess_returns, dtype=float)
    T = len(er)

    if T < window + 12:
        return CheckResult(
            name="rolling_sharpe", grade=Grade.WARN, value=0.0,
            threshold=min_pct_positive,
            detail=f"데이터 부족 (T={T}, window={window})",
        )

    rs = []
    for i in range(window, T):
        chunk = er[i - window:i]
        if np.std(chunk) > 1e-10:
            rs.append(np.mean(chunk) / np.std(chunk) * np.sqrt(12))

    if len(rs) == 0:
        return CheckResult(
            name="rolling_sharpe", grade=Grade.WARN, value=0.0,
            threshold=min_pct_positive, detail="유효 window 없음",
        )

    rs = np.array(rs)
    mean_sr = float(np.mean(rs))
    pct_positive = float(np.mean(rs > 0) * 100)
    pct_strong = float(np.mean(rs > 0.7) * 100)
    pct_neg = float(np.mean(rs < 0) * 100)

    if pct_positive >= min_pct_positive:
        grade = Grade.PASS
    elif pct_positive >= 50:
        grade = Grade.WARN
    else:
        grade = Grade.FAIL

    detail = (f"평균 SR={mean_sr:.3f}, 양수 {pct_positive:.0f}%, "
              f"강건(>0.7) {pct_strong:.0f}%, 음수 {pct_neg:.0f}%")

    return CheckResult(
        name="rolling_sharpe", grade=grade, value=pct_positive,
        threshold=min_pct_positive, detail=detail,
    )


# ══════════════════════════════════════════════
# 7. Walk-Forward
# ══════════════════════════════════════════════

def check_walk_forward(
    excess_returns: np.ndarray,
    n_splits: int = 5,
    max_cv: float = 1.0,
) -> CheckResult:
    """Walk-Forward 교차검증.

    n_splits로 시간 분할 → 각 구간 Sharpe → CV(변동계수) < max_cv이면 PASS.
    """
    er = np.asarray(excess_returns, dtype=float)
    T = len(er)
    sz = max(T // n_splits, 1)

    if T < n_splits * 12:
        return CheckResult(
            name="walk_forward", grade=Grade.WARN, value=999.0,
            threshold=max_cv, detail=f"데이터 부족 (T={T}, splits={n_splits})",
        )

    split_srs = []
    for k in range(n_splits):
        start = k * sz
        end = (k + 1) * sz if k < n_splits - 1 else T
        chunk = er[start:end]
        sr = np.mean(chunk) / np.std(chunk) * np.sqrt(12) if np.std(chunk) > 1e-10 else 0.0
        split_srs.append(sr)

    is_srs = split_srs[:-1]
    oos_sr = split_srs[-1]
    is_mean = float(np.mean(is_srs)) if is_srs else 0.0

    all_srs = np.array(split_srs)
    cv = float(np.std(all_srs) / abs(np.mean(all_srs))) if abs(np.mean(all_srs)) > 1e-10 else 999.0

    decay = (oos_sr / is_mean - 1) * 100 if is_mean != 0 else 0.0

    if cv < max_cv:
        grade = Grade.PASS
    elif cv < 2.0:
        grade = Grade.WARN
    else:
        grade = Grade.FAIL

    detail = (f"IS mean={is_mean:.3f} → OOS={oos_sr:.3f}, "
              f"감쇠={decay:+.0f}%, CV={cv:.2f}")

    return CheckResult(
        name="walk_forward", grade=grade, value=cv, threshold=max_cv, detail=detail,
    )


# ══════════════════════════════════════════════
# 9. IS-OOS Decay
# ══════════════════════════════════════════════

def check_is_oos_decay(
    excess_returns: np.ndarray,
    split_index: int,
    max_decay_pct: float = -26.0,
) -> CheckResult:
    """IS→OOS Sharpe 감쇠율.

    학술 기준: -26% 이내면 합격 (Harvey et al.).
    """
    er = np.asarray(excess_returns, dtype=float)

    if split_index < 12 or split_index >= len(er) - 12:
        return CheckResult(
            name="is_oos_decay", grade=Grade.WARN, value=0.0,
            threshold=max_decay_pct, detail="IS/OOS 구간 부족",
        )

    is_er = er[:split_index]
    oos_er = er[split_index:]

    is_sr = np.mean(is_er) / np.std(is_er) * np.sqrt(12) if np.std(is_er) > 1e-10 else 0.0
    oos_sr = np.mean(oos_er) / np.std(oos_er) * np.sqrt(12) if np.std(oos_er) > 1e-10 else 0.0

    decay = (oos_sr / is_sr - 1) * 100 if is_sr != 0 else 0.0

    if decay > max_decay_pct:
        grade = Grade.PASS
        detail = f"IS={is_sr:.3f} → OOS={oos_sr:.3f}, 감쇠={decay:+.1f}% (학술기준 {max_decay_pct}% 이내)"
    else:
        grade = Grade.WARN
        detail = f"IS={is_sr:.3f} → OOS={oos_sr:.3f}, 감쇠={decay:+.1f}% (학술기준 {max_decay_pct}% 초과)"

    return CheckResult(
        name="is_oos_decay", grade=grade, value=decay, threshold=max_decay_pct, detail=detail,
    )
