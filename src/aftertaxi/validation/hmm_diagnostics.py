# -*- coding: utf-8 -*-
"""
validation/hmm_diagnostics.py — HMM fit 신뢰도 진단
====================================================
"이 HMM fit이 믿을 만한가?"를 답하는 도구.

다른 모든 HMM 활용 아이디어의 **선행 조건**.
이 진단을 통과하지 못하면 regime-conditional 분석 전체가 의미 없다.

3가지 진단:
  1. 라벨 안정성: seed 10개로 fit → regime 라벨 일치율 (permutation 보정)
  2. 모델 적합성: BIC(2-regime) vs BIC(1-regime) → 유의한 개선인지
  3. 레짐 분리도: 두 regime의 평균 수익률 부호가 일관되게 반대인지

코어 변경 없음. 읽기 전용 진단.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class HMMDiagnosticResult:
    """HMM fit 진단 결과."""

    # 라벨 안정성
    label_agreement_rate: float       # 0~1. seed 간 regime 라벨 일치율 (permutation 보정)
    label_stable: bool                # agreement >= threshold

    # 모델 적합성
    bic_1regime: float                # 1-regime (단일 가우시안) BIC
    bic_2regime: float                # 2-regime HMM BIC
    bic_improvement: float            # (bic_1 - bic_2) / |bic_1|. 양수면 2-regime이 나음
    model_justified: bool             # improvement > threshold

    # 레짐 분리도
    regime_mean_signs: List[Tuple[float, float]]  # 각 seed의 (regime0_mean, regime1_mean)
    sign_consistency: float           # 0~1. 부호가 일관된 비율
    regimes_separated: bool           # consistency >= threshold

    # 종합
    n_seeds: int
    n_observations: int
    pass_all: bool                    # 3개 모두 통과

    def summary_text(self) -> str:
        """사람이 읽을 수 있는 진단 요약."""
        status = "✅ PASS" if self.pass_all else "❌ FAIL"
        lines = [
            f"HMM Diagnostic: {status}",
            f"  Observations: {self.n_observations} months",
            f"  Seeds tested: {self.n_seeds}",
            "",
            f"  1) Label stability: {self.label_agreement_rate:.1%} "
            f"({'✅' if self.label_stable else '❌'} need ≥80%)",
            f"  2) Model justified: BIC improvement {self.bic_improvement:.3f} "
            f"({'✅' if self.model_justified else '❌'} need >0.01)",
            f"     BIC(1-regime)={self.bic_1regime:.0f}, BIC(2-regime)={self.bic_2regime:.0f}",
            f"  3) Regime separation: sign consistency {self.sign_consistency:.1%} "
            f"({'✅' if self.regimes_separated else '❌'} need ≥80%)",
        ]
        if not self.pass_all:
            lines.append("")
            lines.append("  ⚠ HMM fit 불안정. regime-conditional 분석을 신뢰하지 마시오.")
        return "\n".join(lines)


def run_hmm_diagnostics(
    returns: np.ndarray,
    n_seeds: int = 10,
    n_regimes: int = 2,
    label_threshold: float = 0.80,
    bic_threshold: float = 0.01,
    sign_threshold: float = 0.80,
) -> HMMDiagnosticResult:
    """HMM fit 신뢰도 진단 실행.

    Parameters
    ----------
    returns : (T, N) 월간 수익률. 1D면 (T, 1)로 reshape.
    n_seeds : HMM fit 반복 횟수
    n_regimes : 테스트할 regime 수 (보통 2)
    label_threshold : 라벨 일치율 최소 기준
    bic_threshold : BIC 개선율 최소 기준
    sign_threshold : 부호 일관성 최소 기준

    Returns
    -------
    HMMDiagnosticResult
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        raise ImportError("hmmlearn 필요: pip install hmmlearn")

    arr = np.asarray(returns, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    T, N = arr.shape

    # ── 1. 여러 seed로 HMM fit → regime 라벨 수집 ──
    all_labels = []
    all_means = []
    bic_2regime_list = []

    for seed in range(n_seeds):
        model = GaussianHMM(
            n_components=n_regimes,
            covariance_type="full",
            n_iter=200,
            random_state=seed * 7 + 13,  # 다양한 초기화
        )
        model.fit(arr)
        labels = model.predict(arr)
        all_labels.append(labels)
        # 첫 번째 자산 기준 regime 평균
        means = [float(model.means_[k, 0]) for k in range(n_regimes)]
        all_means.append(tuple(means))
        bic_2regime_list.append(model.bic(arr))

    # ── 2. 라벨 안정성: pairwise agreement (permutation 보정) ──
    agreement_scores = []
    for i in range(n_seeds):
        for j in range(i + 1, n_seeds):
            agreement_scores.append(
                _label_agreement_permutation(all_labels[i], all_labels[j], n_regimes)
            )
    label_agreement = float(np.mean(agreement_scores)) if agreement_scores else 0.0

    # ── 3. BIC: 1-regime vs 2-regime ──
    model_1 = GaussianHMM(
        n_components=1,
        covariance_type="full",
        n_iter=200,
        random_state=42,
    )
    model_1.fit(arr)
    bic_1 = model_1.bic(arr)
    bic_2 = float(np.median(bic_2regime_list))  # median of multiple fits
    bic_improvement = (bic_1 - bic_2) / abs(bic_1) if abs(bic_1) > 0 else 0.0

    # ── 4. 레짐 분리도: 정규화된 평균 부호 일관성 ──
    # 각 seed에서 regime을 평균 수익률 순서로 정렬 (label permutation 보정)
    sorted_means = []
    for means_tuple in all_means:
        sorted_m = tuple(sorted(means_tuple))
        sorted_means.append(sorted_m)

    # 가장 낮은 regime 평균이 음수, 가장 높은 것이 양수인 비율
    sign_consistent = sum(
        1 for m in sorted_means if m[0] < 0 and m[-1] > 0
    )
    sign_consistency = sign_consistent / n_seeds if n_seeds > 0 else 0.0

    # regime 평균 쌍 리스트 (원본 순서)
    regime_mean_signs = [(m[0], m[-1]) for m in sorted_means]

    # ── 종합 ──
    label_stable = label_agreement >= label_threshold
    model_justified = bic_improvement > bic_threshold
    regimes_separated = sign_consistency >= sign_threshold

    return HMMDiagnosticResult(
        label_agreement_rate=label_agreement,
        label_stable=label_stable,
        bic_1regime=bic_1,
        bic_2regime=bic_2,
        bic_improvement=bic_improvement,
        model_justified=model_justified,
        regime_mean_signs=regime_mean_signs,
        sign_consistency=sign_consistency,
        regimes_separated=regimes_separated,
        n_seeds=n_seeds,
        n_observations=T,
        pass_all=label_stable and model_justified and regimes_separated,
    )


def _label_agreement_permutation(
    labels_a: np.ndarray,
    labels_b: np.ndarray,
    n_regimes: int,
) -> float:
    """두 라벨 시퀀스의 최대 일치율 (permutation 보정).

    HMM regime 라벨은 순서가 임의적이므로,
    가능한 모든 라벨 permutation 중 최대 일치율을 반환.
    n_regimes=2이면 2가지만 확인하면 된다.
    """
    from itertools import permutations

    T = len(labels_a)
    best = 0.0

    for perm in permutations(range(n_regimes)):
        mapped = np.array([perm[l] for l in labels_b])
        agreement = np.mean(labels_a == mapped)
        if agreement > best:
            best = agreement

    return float(best)
