# -*- coding: utf-8 -*-
"""
analysis/random_lab.py — 랜덤 허상 실험실
==========================================
"완전 랜덤 전략 대부분이 죽는다"를 정량적으로 보여주는 실험 도구.

이것은 **채택기가 아니라 실험실**이다.
- 완전 랜덤 생성 허용
- 대부분 죽는 것이 정상
- validation 통과 극소수만 연구 후보로 표시
- search budget 공개 필수
- baseline 미달 자동 폐기

핵심 안전장치:
  - DSR n_trials에 총 생성 수를 **반드시** 전달
  - 출력 첫 줄 = "N개 중 M개 생존 (생존율 X%)"
  - source="random_lab" 태그로 registry 전략과 분리
  - C/O only. FULL/BAND 랜덤화 금지
  - 자산 풀은 사용자 명시 필수. 기본값 없음

코어 변경 없음. analysis/ 모듈.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from aftertaxi.strategies.spec import StrategySpec


# ══════════════════════════════════════════════
# DTO
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class RandomLabConfig:
    """랜덤 실험 설정.

    asset_pool에 기본값이 없다. 사용자가 반드시 명시해야 한다.
    이유: 기본값이 있으면 "아무 생각 없이 돌리기"를 유도.
    """
    asset_pool: Tuple[str, ...]         # ("SPY", "QQQ", "SSO", "TLT") — 기본값 없음
    n_candidates: int = 100             # search budget
    min_assets: int = 2
    max_assets: int = 4
    min_weight: float = 0.05            # 각 자산 최소 5%
    rebalance_every: int = 1            # C/O 고정
    seed: int = 42

    def __post_init__(self):
        if not self.asset_pool:
            raise ValueError("asset_pool은 비어있을 수 없음. 자산을 명시하세요.")
        if len(self.asset_pool) < 2:
            raise ValueError("asset_pool은 최소 2개 자산 필요.")
        if self.min_assets < 2:
            raise ValueError("min_assets는 최소 2.")
        if self.max_assets > len(self.asset_pool):
            raise ValueError(
                f"max_assets({self.max_assets}) > asset_pool 크기({len(self.asset_pool)})"
            )
        if self.n_candidates < 1:
            raise ValueError("n_candidates는 최소 1.")


@dataclass
class RandomLabReport:
    """랜덤 실험 결과.

    첫 줄이 survival rate. winner부터 보여주면 안 된다.
    """
    config: RandomLabConfig

    # ── search budget (정직하게) ──
    n_generated: int = 0
    n_after_baseline: int = 0
    n_after_basic: int = 0
    n_after_validation: int = 0

    # ── 결과 분포 ──
    baseline_mult: float = 0.0          # SPY B&H 세후 배수
    all_mults: np.ndarray = field(default_factory=lambda: np.array([]))
    survivors: List[Dict] = field(default_factory=list)

    @property
    def survival_rate(self) -> float:
        if self.n_generated == 0:
            return 0.0
        return self.n_after_validation / self.n_generated

    def summary_text(self) -> str:
        """첫 줄 = 생존율. winner부터 보여주지 않는다."""
        lines = [
            f"랜덤 실험: {self.n_generated}개 생성 → "
            f"{self.n_after_baseline}개 baseline 통과 → "
            f"{self.n_after_basic}개 basic 통과 → "
            f"{self.n_after_validation}개 validation 통과",
            f"생존율: {self.survival_rate:.1%}  "
            f"(DSR n_trials={self.n_generated})",
            f"Baseline (SPY B&H): {self.baseline_mult:.3f}x 세후",
            "",
        ]

        if self.all_mults.size > 0:
            lines.append(
                f"전체 분포: "
                f"median={np.median(self.all_mults):.3f}x, "
                f"p5={np.percentile(self.all_mults, 5):.3f}x, "
                f"p95={np.percentile(self.all_mults, 95):.3f}x"
            )

        if self.survivors:
            lines.append("")
            lines.append(f"연구 후보 ({len(self.survivors)}개, 자동 등록 아님):")
            for s in self.survivors[:5]:  # 최대 5개만 표시
                lines.append(
                    f"  {s['name']}: {s['mult_after_tax']:.3f}x "
                    f"(MDD={s['mdd']:.1%}, tax_drag={s.get('tax_drag_pct', 0):.1%})"
                )
            if len(self.survivors) > 5:
                lines.append(f"  ... 외 {len(self.survivors) - 5}개")
        else:
            lines.append("")
            lines.append("연구 후보: 없음 (전멸)")

        return "\n".join(lines)


# ══════════════════════════════════════════════
# 벡터화 생성
# ══════════════════════════════════════════════

def generate_random_specs(config: RandomLabConfig) -> List[StrategySpec]:
    """랜덤 전략 N개를 벡터화로 한 번에 생성.

    1. 자산 수 샘플링: min_assets~max_assets 균등
    2. 자산 선택: asset_pool에서 비복원 추출
    3. 비중 샘플링: Dirichlet(α=1) → 최소 비중 클램핑 → 재정규화
    """
    rng = np.random.default_rng(config.seed)
    pool = list(config.asset_pool)
    pool_size = len(pool)
    N = config.n_candidates

    # 1. 자산 수 벡터 (N,)
    n_assets_vec = rng.integers(
        config.min_assets, config.max_assets + 1, size=N
    )

    # 2+3. 자산 선택 + 비중 — 자산 수가 다르므로 그룹별 벡터화
    specs = []
    for n_assets in range(config.min_assets, config.max_assets + 1):
        mask = n_assets_vec == n_assets
        count = int(mask.sum())
        if count == 0:
            continue

        # 자산 인덱스 벡터화: (count, pool_size) 순열 → 앞 n_assets개 선택
        # argsort trick으로 비복원 추출 벡터화
        rand_matrix = rng.random((count, pool_size))
        sorted_idx = np.argsort(rand_matrix, axis=1)[:, :n_assets]  # (count, n_assets)

        # Dirichlet 비중 벡터화: (count, n_assets)
        raw_weights = rng.dirichlet(np.ones(n_assets), size=count)

        # 최소 비중 클램핑 + 재정규화
        clamped = np.maximum(raw_weights, config.min_weight)
        normalized = clamped / clamped.sum(axis=1, keepdims=True)
        # 부동소수점 오차로 min_weight 아래로 밀릴 수 있음 → 최종 보정
        # 부족분을 최대 비중에서 차감 (simplex projection)
        for row in range(count):
            below = normalized[row] < config.min_weight
            if below.any():
                deficit = config.min_weight - normalized[row, below]
                normalized[row, below] = config.min_weight
                max_idx = np.argmax(normalized[row])
                normalized[row, max_idx] -= deficit.sum()

        # StrategySpec 생성
        for i in range(count):
            assets = [pool[j] for j in sorted_idx[i]]
            weights = {a: float(w) for a, w in zip(assets, normalized[i])}
            name = "_".join(
                f"{a}{int(w * 100)}" for a, w in weights.items()
            )
            specs.append(StrategySpec(
                name=f"RND_{name}",
                family="random_lab",
                weights=weights,
                rebalance_every=config.rebalance_every,
                params={"n_assets": n_assets, "seed": config.seed},
                source="random_lab",
                description=f"랜덤 생성. search budget={N}의 일부.",
            ))

    # seed 결정성을 위해 원래 순서 복원
    # n_assets_vec 순서대로 specs를 재배치
    ordered = []
    cursors = {}
    for n_assets in range(config.min_assets, config.max_assets + 1):
        cursors[n_assets] = 0

    group_specs = {}
    cursor = 0
    for n_assets in range(config.min_assets, config.max_assets + 1):
        mask = n_assets_vec == n_assets
        count = int(mask.sum())
        group_specs[n_assets] = specs[cursor:cursor + count]
        cursor += count

    group_idx = {n: 0 for n in range(config.min_assets, config.max_assets + 1)}
    for n_assets in n_assets_vec:
        n = int(n_assets)
        ordered.append(group_specs[n][group_idx[n]])
        group_idx[n] += 1

    return ordered


# ══════════════════════════════════════════════
# 실행 파이프라인
# ══════════════════════════════════════════════

def run_random_lab(
    config: RandomLabConfig,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    baseline_spec: Optional[StrategySpec] = None,
    base_account_payload: Optional[dict] = None,
) -> RandomLabReport:
    """랜덤 허상 실험실 실행.

    파이프라인:
      생성(벡터화) → 엔진 실행(순차) → baseline gate → basic gate → DSR gate

    Parameters
    ----------
    config : 실험 설정
    returns, prices, fx_rates : 시장 데이터
    baseline_spec : baseline 전략. None이면 SPY B&H 사용.
    base_account_payload : 계좌 설정 dict. None이면 TAXABLE C/O 기본.
    """
    from aftertaxi.strategies.compile import compile_backtest
    from aftertaxi.core.facade import run_backtest
    from aftertaxi.core.attribution import build_attribution
    from aftertaxi.validation.basic import run_basic_checks
    from aftertaxi.validation.statistical import run_statistical_checks
    from aftertaxi.validation.reports import Grade

    report = RandomLabReport(config=config)

    # ── 0. 기본 계좌 설정 ──
    if base_account_payload is None:
        base_account_payload = {
            "accounts": [{
                "account_id": "taxable",
                "account_type": "TAXABLE",
                "monthly_contribution": 500,
                "rebalance_mode": "CONTRIBUTION_ONLY",
            }],
        }

    # ── 1. 벡터화 생성 ──
    specs = generate_random_specs(config)
    report.n_generated = len(specs)

    # ── 2. Baseline 실행 ──
    if baseline_spec is None:
        baseline_spec = StrategySpec(
            name="SPY_BnH_baseline",
            family="benchmark",
            weights={"SPY": 1.0},
            rebalance_every=1,
        )

    baseline_payload = {
        **base_account_payload,
        "strategy": {
            "name": baseline_spec.name,
            "weights": baseline_spec.weights,
            "rebalance_every": baseline_spec.rebalance_every,
        },
    }
    baseline_cfg = compile_backtest(baseline_payload)
    baseline_result = run_backtest(
        baseline_cfg, returns=returns, prices=prices, fx_rates=fx_rates
    )
    report.baseline_mult = baseline_result.mult_after_tax

    # ── 3. 전체 실행 + baseline gate ──
    all_mults = []
    candidates_after_baseline = []

    for spec in specs:
        payload = {
            **base_account_payload,
            "strategy": {
                "name": spec.name,
                "weights": spec.weights,
                "rebalance_every": spec.rebalance_every,
            },
        }
        try:
            cfg = compile_backtest(payload)
            result = run_backtest(
                cfg, returns=returns, prices=prices, fx_rates=fx_rates
            )
            mult = result.mult_after_tax
            all_mults.append(mult)

            # baseline gate
            if mult > report.baseline_mult:
                attr = build_attribution(result)
                candidates_after_baseline.append({
                    "spec": spec,
                    "result": result,
                    "attr": attr,
                    "mult_after_tax": mult,
                    "mdd": result.mdd,
                    "tax_drag_pct": attr.tax_drag_pct,
                    "name": spec.name,
                })
        except Exception:
            all_mults.append(0.0)  # 실행 실패 = 사망

    report.all_mults = np.array(all_mults)
    report.n_after_baseline = len(candidates_after_baseline)

    # ── 4. Basic validation gate ──
    candidates_after_basic = []
    for cand in candidates_after_baseline:
        checks = run_basic_checks(cand["result"])
        if all(c.grade != Grade.FAIL for c in checks):
            candidates_after_basic.append(cand)

    report.n_after_basic = len(candidates_after_basic)

    # ── 5. Statistical validation gate (DSR with honest n_trials) ──
    survivors = []
    for cand in candidates_after_basic:
        result = cand["result"]
        # 세후 월간 초과수익률 계산
        monthly_values = result.monthly_values
        if len(monthly_values) < 3:
            continue
        monthly_returns = np.diff(monthly_values) / monthly_values[:-1]

        stat_checks = run_statistical_checks(
            monthly_returns,
            n_trials=report.n_generated,  # 핵심: 총 생성 수를 정직하게 전달
            benchmark_sharpe=0.0,
        )

        # DSR check 찾기
        dsr_pass = True
        for check in stat_checks:
            if "DSR" in check.name and check.grade == Grade.FAIL:
                dsr_pass = False
                break

        if dsr_pass:
            survivors.append({
                "name": cand["name"],
                "weights": cand["spec"].weights,
                "mult_after_tax": cand["mult_after_tax"],
                "mdd": cand["mdd"],
                "tax_drag_pct": cand["tax_drag_pct"],
                "source": "random_lab",
            })

    report.n_after_validation = len(survivors)
    report.survivors = survivors

    return report
