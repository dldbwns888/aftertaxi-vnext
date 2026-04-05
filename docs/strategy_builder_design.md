# Strategy Builder 설계 — aftertaxi-vnext

## 1. 총평

### 적합성

원본형 Strategy Builder를 이 프로젝트에 넣는 것은 **조건부 적합**이다.

이유: aftertaxi-vnext의 기존 연구 결론(Q60S40 B&H가 모든 신호 기반 전략을 세후 기준으로 이겼다)과 정면으로 충돌한다. 사실상 "이길 수 없다는 걸 이미 알면서 전략 공장을 돌리는" 구조가 된다.

그러나 이것이 의미 있는 세 가지 이유:
1. **기존 결론의 반증 기회** — Q60S40 우위가 데이터 기간 한정인지, 구조적으로 불변인지 확인할 수 있다
2. **세후 고유 현상 탐색** — 250만 공제 분산, ISA 전략적 활용, 저회전 세금 효율 등 DCA 세후 특수 알파를 찾을 수 있다
3. **허상 정량화** — "N천 개 전략 중 생존 0개"가 증거로서 가치가 있다 (negative result publishing)

### 필수 격리 장치

1. **코어 엔진 변경 최소화** — `StrategyConfig`에 `weight_schedule` 1필드만 추가. runner 수정 ~5줄.
2. **전용 디렉토리 격리** — `strategy_builder/`를 `analysis/` 또는 별도 top-level 패키지로 배치. `core/` 미침범.
3. **생성 ≠ 채택 원칙** — 생성된 전략은 전부 `verdict="rejected"`가 기본값. validation 통과해야 `"research_candidate"`로 승격.
4. **family-search-review 스킬 병행** — 이 모듈에 대한 모든 PR은 family-search-review를 트리거.
5. **search budget 공개 강제** — 리포트 첫 줄은 반드시 `"N개 생성, M개 생존 (생존율 X%)"`.
6. **baseline 강제 비교** — SPY B&H를 모든 리포트에 병렬 표시. baseline 미달은 자동 폐기.

---

## 2. 원본 Strategy Builder 구조 (StrategyQuant X 참조)

StrategyQuant X의 Strategy Builder를 DCA 세후 백테스트 맥락으로 번역한다.

### 2.1 규칙 블록 풀 (Block Pool)

SQX에서 entry/exit/filter/management 4종 블록을 쓰는 것을 DCA 맥락으로 변환:

**Signal 블록** (SQX의 entry/exit에 대응) — "언제 성장형/쉘터형으로 전환하는가"

| ID | 블록명 | 파라미터 | 범위 |
|---|---|---|---|
| S01 | AbsMomentum | lookback_months | 1–12 |
| S02 | RelMomentum | asset_a, asset_b, lookback | 1–12 |
| S03 | SMACross | fast, slow | fast: 1–6, slow: 6–12 |
| S04 | PriceVsSMA | sma_months | 6–12 |
| S05 | VolFilter | lookback, threshold | 3–12, 0.12–0.25 |
| S06 | FREDMacro | indicator, threshold | UNRATE/T10Y2Y/etc |
| S07 | AlwaysOn | — | — (B&H, 신호 없음) |
| S08 | DualMomentum | abs_lb, rel_lb | 1–12 각각 |

**Allocation 블록** (SQX의 management에 대응) — "무엇을 얼마나 보유하는가"

| ID | 블록명 | 파라미터 |
|---|---|---|
| A01 | StaticWeight | weights: Dict[str, float] |
| A02 | EqualWeight | assets: List[str] |
| A03 | InverseVol | lookback: 3–12 |
| A04 | MomentumWeight | lookback: 1–12, top_n: 1–4 |

**Shelter 블록** — "위험 회피 시 어디로 가는가"

| ID | 블록명 |
|---|---|
| H01 | FullCash (SGOV/BIL) |
| H02 | ShortBond (SHY) |
| H03 | LongBond (TLT) |
| H04 | ReducedExposure (50% cash) |
| H05 | StayInvested (B&H, 쉘터 없음) |

**Rebalance 블록** — "보유 자산을 어떻게 조정하는가"

| ID | 블록명 | 비고 |
|---|---|---|
| R01 | ContributionOnly | 매도 0, 세금 0 |
| R02 | Full | 매월 목표비중 조정 |
| R03 | Band(threshold) | 괴리 초과 시만 FULL |

### 2.2 전략 AST / 규칙 트리

```
StrategyGenome = {
    growth: AllocationBlock,     # 성장 포지션
    shelter: ShelterBlock,       # 방어 포지션
    signal: SignalBlock,         # 전환 신호
    rebalance: RebalanceBlock,   # 실행 정책
    filter: Optional[SignalBlock],  # 추가 필터 (AND 조건)
}
```

예시 (대피+1.6x):
```python
StrategyGenome(
    growth=StaticWeight({"SSO": 0.8, "VOO": 0.2}),
    shelter=FullCash("SGOV"),
    signal=AbsMomentum(asset="SPY", lookback=9),
    rebalance=Full(),
    filter=None,
)
```

예시 (Q60S40 B&H):
```python
StrategyGenome(
    growth=StaticWeight({"QQQ": 0.6, "SSO": 0.4}),
    shelter=StayInvested(),  # 쉘터 없음
    signal=AlwaysOn(),        # 항상 성장
    rebalance=ContributionOnly(),
    filter=None,
)
```

### 2.3 랜덤 생성기

```python
def generate_genome(rng, block_pool, asset_pool) -> StrategyGenome:
    """규칙 블록 풀에서 랜덤 조합 생성.
    
    1. signal 블록 1개 랜덤 선택 + 파라미터 랜덤화
    2. growth allocation 1개 랜덤 선택 + 자산/비중 랜덤화
    3. shelter 블록 1개 랜덤 선택
    4. rebalance 블록 1개 랜덤 선택
    5. filter: 50% 확률로 추가 signal 블록 1개 (AND 조합)
    """
```

핵심 제약:
- 자산 풀은 사용자 명시 (기본값 없음)
- 레버리지 자산은 별도 풀로 분리 (무제한 레버리지 조합 방지)
- 파라미터 범위는 블록 정의 시 고정 (범위 밖 랜덤화 금지)
- seed 기반 재현성 필수

### 2.4 유효성 검사기 (Genome Validator)

생성 직후, 백테스트 전에 수행하는 구조적 필터:

```python
def validate_genome(genome: StrategyGenome) -> bool:
    """구조적으로 말이 안 되는 전략 사전 폐기.
    
    실패 조건:
    - signal=AlwaysOn인데 shelter≠StayInvested (사용되지 않는 쉘터)
    - signal이 있는데 rebalance=ContributionOnly (신호에 반응 불가)
    - growth와 shelter가 동일한 자산 구성
    - 비중 합 ≠ 1.0
    - 레버리지 자산만으로 100% 구성 (max_leverage 초과)
    """
```

### 2.5 백테스트 실행기

전략 AST → 월간 비중 스케줄 → 엔진 실행.

```python
def genome_to_weight_schedule(
    genome: StrategyGenome,
    prices: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> List[Dict[str, float]]:
    """StrategyGenome + 가격 데이터 → 월별 목표비중 리스트.
    
    각 월에서:
    1. signal.evaluate(prices, step) → bool (성장/쉘터)
    2. filter가 있으면 AND 적용
    3. 성장이면 growth.get_weights(prices, step)
       쉘터이면 shelter.get_weights()
    """
```

엔진 연결: `StrategyConfig`에 `weight_schedule: Optional[List[Dict[str, float]]]`를 추가.
runner.py에서 `weight_schedule[step]`이 있으면 그것을 쓰고, 없으면 기존 `weights` 사용.

**코어 변경 범위**: contracts.py 1필드 + runner.py ~5줄. 기존 테스트 전부 통과.

### 2.6 1차 필터 (Fast Filter)

백테스트 완료 후 즉시 적용하는 저비용 필터:

| 필터 | 기준 | 이유 |
|---|---|---|
| baseline_gate | mult_after_tax >= SPY B&H | 벤치마크 미달 자동 폐기 |
| mdd_gate | MDD > -80% | 극단적 손실 제거 |
| turnover_gate | 연간 회전율 < 300% | 세금 폭탄 제거 |
| tax_drag_gate | tax_drag < 50% | 세금이 수익의 절반 이상이면 폐기 |
| min_months_gate | n_months >= 120 | 10년 미만 결과 불신 |

### 2.7 Validation 게이트

1차 필터 통과자에게만 적용 (비용이 크므로):

| 게이트 | 모듈 | 역할 |
|---|---|---|
| DSR | validation/statistical.py | n_trials=총 생성 수. Bonferroni 보정 |
| PSR | validation/statistical.py | Sharpe 통계적 유의성 |
| Permutation | validation/statistical.py | 무작위 대비 유의미성 |
| Walk-forward | validation/stability.py | IS/OOS 시간 안정성 |
| CPCV/PBO | validation/robustness.py | 과적합 확률 |
| Rolling Sharpe | validation/stability.py | Sharpe 안정성 |
| IS/OOS Decay | validation/stability.py | 과적합 징후 |

**핵심**: DSR의 `n_trials`에 **총 생성 수**를 반드시 전달. 1차 필터 후 남은 수가 아님.

### 2.8 Databank / Candidate Store

```python
@dataclass
class CandidateEntry:
    genome: StrategyGenome          # 전략 구조 (재현 가능)
    engine_result: EngineResult     # 엔진 결과
    attribution: ResultAttribution  # 세금/FX 분해
    validation_grade: str           # "A"/"B"/"C"/"F"
    verdict: str                    # "rejected" / "research_candidate" / "finalist"
    
    # 투명성
    search_budget: int              # 총 생성 수
    rank_in_cohort: int             # 이 코호트에서의 순위
    baseline_delta: float           # SPY B&H 대비 세후 배수 차이
    
    # DCA 세후 고유 메트릭
    annual_turnover: float          # 세금 비용 proxy
    exemption_utilization: float    # 250만 공제 활용률
    isa_benefit_captured: bool      # ISA 전환세 면제 활용 여부
```

**폐기 정책**: validation_grade="F"인 항목은 genome + 1줄 요약만 보관, engine_result는 폐기 (디스크 절약).

### 2.9 Evolution 엔진 (선택)

| 연산 | 설명 | 위치 |
|---|---|---|
| Mutation | 파라미터 ±1 변경 (lookback 6→7) | `strategy_builder/evolution.py` |
| Block Swap | signal 블록 교체 (AbsMom→SMACross) | `strategy_builder/evolution.py` |
| Crossover | 두 genome의 signal+allocation 교차 | `strategy_builder/evolution.py` |
| Elitism | 상위 10% 보존 | `strategy_builder/evolution.py` |

**제약**: evolution은 search budget을 **누적**한다. 10세대 × 100개 = 1,000이 DSR n_trials.

---

## 3. aftertaxi-vnext 대응 설계

| Strategy Builder 구성요소 | aftertaxi 대응 위치 | 새 모듈 | 기존 수정 |
|---|---|---|---|
| 블록 풀 정의 | 새 모듈 | `strategy_builder/blocks.py` | — |
| 전략 AST (StrategyGenome) | 새 모듈 | `strategy_builder/genome.py` | — |
| 랜덤 생성기 | 새 모듈 | `strategy_builder/generator.py` | — |
| 유효성 검사기 | 새 모듈 | `strategy_builder/validator.py` | — |
| 월간 비중 스케줄 변환 | 새 모듈 | `strategy_builder/scheduler.py` | — |
| 백테스트 실행 | `core/facade.py` 경유 | — | `contracts.py` +1필드, `runner.py` ~5줄 |
| 1차 필터 | `analysis/random_lab.py` 패턴 참조 | `strategy_builder/filters.py` | — |
| Validation 게이트 | `validation/` 재사용 | `strategy_builder/gates.py` (조립) | — |
| Databank | 새 모듈 | `strategy_builder/databank.py` | — |
| Evolution | 새 모듈 (선택) | `strategy_builder/evolution.py` | — |
| Search budget 기록 | `experiments/` 패턴 참조 | `strategy_builder/budget.py` | — |
| 리포트 | `analysis/` 패턴 참조 | `strategy_builder/report.py` | — |
| CLI/GUI 연결 | `apps/` | — | `apps/cli.py` 서브커맨드 추가 |

**핵심 원칙**: `strategy_builder/`는 `core/`를 직접 수정하지 않는다. `facade.run_backtest()`만 호출.

코어 변경은 `weight_schedule` 1필드뿐이며, 이것도 None이면 기존 동작 그대로.

---

## 4. 구현안

### PR1: 코어 최소 확장 — weight_schedule

**목표**: 엔진이 월별 동적 비중을 받아서 실행할 수 있게 한다.

**새 파일**: 없음

**수정 파일**:
- `core/contracts.py`: `StrategyConfig`에 `weight_schedule: Optional[List[Dict[str, float]]] = None` 추가
- `core/runner.py`: `_step_deposit_and_rebalance`에서 `weight_schedule[step]` 분기 (~5줄)

**핵심 함수 시그니처**:
```python
# contracts.py
@dataclass(frozen=True)
class StrategyConfig:
    name: str
    weights: Dict[str, float]
    rebalance_every: int = 1
    weight_schedule: Optional[List[Dict[str, float]]] = None  # NEW
```

```python
# runner.py (변경 부분)
def _step_deposit_and_rebalance(...):
    # 동적 비중: schedule이 있으면 해당 step의 비중 사용
    if config.strategy.weight_schedule is not None and step < len(config.strategy.weight_schedule):
        target_weights = config.strategy.weight_schedule[step]
    else:
        target_weights = config.strategy.weights
    ...
```

**테스트 계획**:
- `weight_schedule=None` → 기존 동작 동일 (golden baseline 4/4 통과)
- `weight_schedule=[{"SPY":1.0}]*60` → 기존 SPY B&H와 동일
- `weight_schedule`이 중간에 비중 변경 → FULL rebalance 세금 발생 확인
- `weight_schedule` 길이 < n_months → 이후는 마지막 비중 유지 or fallback to weights

**위험**: 코어 변경. golden baseline 반드시 통과 확인.

**완료 기준**: golden 4/4 + weight_schedule 전용 테스트 4건 + oracle shadow 영향 없음.

---

### PR2: StrategyGenome + 블록 풀 + 생성기

**목표**: 규칙 블록을 조합해서 전략 AST를 랜덤 생성한다.

**새 파일**:
- `strategy_builder/__init__.py`
- `strategy_builder/blocks.py` — SignalBlock, AllocationBlock, ShelterBlock, RebalanceBlock
- `strategy_builder/genome.py` — StrategyGenome dataclass
- `strategy_builder/generator.py` — `generate_genomes(config, rng) -> List[StrategyGenome]`
- `strategy_builder/validator.py` — `validate_genome(genome) -> bool`
- `strategy_builder/scheduler.py` — `genome_to_weight_schedule(genome, prices) -> List[Dict]`

**핵심 함수 시그니처**:
```python
# blocks.py
class SignalBlock(ABC):
    @abstractmethod
    def evaluate(self, prices: pd.DataFrame, step: int, lookback_data: pd.DataFrame) -> bool:
        """이 시점에서 '성장 모드' 여부를 반환."""

class AllocationBlock(ABC):
    @abstractmethod
    def get_weights(self, prices: pd.DataFrame, step: int) -> Dict[str, float]:
        """이 시점의 목표 비중을 반환."""
```

```python
# genome.py
@dataclass(frozen=True)
class StrategyGenome:
    growth: AllocationBlock
    shelter: AllocationBlock  # ShelterBlock은 AllocationBlock의 서브셋
    signal: SignalBlock
    rebalance: str            # "CO" / "FULL" / "BAND"
    filter: Optional[SignalBlock] = None
    
    def fingerprint(self) -> str:
        """재현 가능한 구조 해시. 같은 구조 = 같은 fingerprint."""
    
    def to_dict(self) -> dict:
        """직렬화. databank 저장용."""
```

```python
# generator.py
@dataclass
class GeneratorConfig:
    asset_pool: Tuple[str, ...]         # 기본값 없음
    leverage_pool: Tuple[str, ...] = () # SSO, QLD 등 별도 관리
    shelter_pool: Tuple[str, ...] = ("SGOV", "SHY", "TLT")
    n_candidates: int = 100
    signal_blocks: Tuple[str, ...] = ("abs_momentum", "rel_momentum", "sma_cross", "always_on")
    max_leverage_ratio: float = 2.0     # 포트폴리오 레버리지 상한
    filter_prob: float = 0.3            # 추가 필터 블록 확률
    seed: int = 42

def generate_genomes(config: GeneratorConfig) -> List[StrategyGenome]:
    """블록 풀에서 랜덤 조합 N개 생성."""
```

**DTO**: `StrategyGenome`, `GeneratorConfig`

**테스트 계획**:
- 생성된 genome이 validate_genome 통과율 확인 (90%+ 목표)
- fingerprint 결정성: 같은 seed → 같은 genome 목록
- genome_to_weight_schedule 산출물이 올바른 길이/형식
- AlwaysOn signal → 고정 비중 스케줄 (기존 B&H와 동치)
- genome.to_dict() → from_dict() 라운드트립

**위험**: 블록 수가 늘어날수록 조합 폭발. signal_blocks 제한 필수.

**완료 기준**: generate 100개 + validate + schedule 변환 + 1개 엔진 실행까지 E2E 동작.

---

### PR3: 파이프라인 — 대량 실행 + 필터 + validation 연결

**목표**: N개 전략을 백테스트하고 필터링하고 validation 게이트를 통과시킨다.

**새 파일**:
- `strategy_builder/filters.py` — 1차 필터 (baseline, MDD, turnover, tax_drag)
- `strategy_builder/gates.py` — validation 게이트 조립 (기존 validation/ 재사용)
- `strategy_builder/pipeline.py` — 전체 파이프라인 실행
- `strategy_builder/report.py` — 리포트 생성

**핵심 함수 시그니처**:
```python
# pipeline.py
@dataclass
class BuilderConfig:
    generator: GeneratorConfig
    account_payload: dict               # 계좌 설정 (TAXABLE/ISA)
    baseline_type: str = "spy_bnh"      # 강제 비교 기준
    enable_validation: bool = True      # False면 1차 필터까지만
    enable_evolution: bool = False      # PR4에서 추가
    n_jobs: int = 1                     # 병렬

@dataclass
class BuilderReport:
    config: BuilderConfig
    
    # search budget (정직하게)
    n_generated: int
    n_valid_structure: int              # validate_genome 통과
    n_after_baseline: int
    n_after_fast_filter: int
    n_after_validation: int
    n_finalists: int
    
    # baseline 결과
    baseline_result: EngineResult
    
    # 후보
    finalists: List[CandidateEntry]     # validation 통과 (보통 0~5개)
    rejected_summary: List[dict]        # 폐기 1줄 요약
    
    # 전체 분포
    all_mults: np.ndarray               # 세후 배수 분포
    
    def summary_text(self) -> str:
        """첫 줄: 생존율. 그 다음: baseline. 그 다음: 후보."""

def run_builder(
    config: BuilderConfig,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
) -> BuilderReport:
    """Strategy Builder 전체 파이프라인 실행.
    
    순서:
    1. generate_genomes → N개
    2. validate_genome → 구조 필터
    3. genome_to_weight_schedule → 비중 스케줄
    4. run_backtest → 엔진 실행
    5. fast_filter → baseline/MDD/turnover/tax_drag
    6. run_validation_suite → DSR/PSR/walk-forward (n_trials=N)
    7. rank_finalists → plateau/robust 우선
    8. build_report
    """
```

**테스트 계획**:
- 100개 생성 → 전멸 시나리오 (정상 동작)
- baseline이 항상 리포트에 포함
- DSR n_trials = n_generated (1차 필터 후가 아님)
- 결과 finalists가 baseline 이상만 포함
- search budget 숫자 합산 일치 (n_generated = n_valid + n_invalid)

**위험**: 대량 실행 시간. 100개 × 20년 = ~200초. n_jobs 병렬 필수.

**완료 기준**: 100개 파이프라인 E2E + 리포트 출력 + baseline 비교 동작.

---

### PR4 (선택): Evolution 엔진

**목표**: 상위 후보에서 mutation/crossover로 다음 세대를 생성한다.

**새 파일**:
- `strategy_builder/evolution.py` — mutate, crossover, select_elite
- `strategy_builder/evolution_runner.py` — 다세대 실행

**핵심 함수 시그니처**:
```python
# evolution.py
def mutate(genome: StrategyGenome, rng, block_pool) -> StrategyGenome:
    """파라미터 ±1 또는 블록 교체. 원본 불변."""

def crossover(a: StrategyGenome, b: StrategyGenome, rng) -> StrategyGenome:
    """두 genome의 블록을 교차 조합."""

# evolution_runner.py
@dataclass
class EvolutionConfig:
    n_generations: int = 5
    population_size: int = 50
    elite_ratio: float = 0.1
    mutation_rate: float = 0.3
    crossover_rate: float = 0.3

def run_evolution(
    config: EvolutionConfig,
    builder_config: BuilderConfig,
    returns, prices, fx_rates,
) -> List[BuilderReport]:
    """다세대 실행. 각 세대의 BuilderReport를 반환.
    
    search budget = sum(population_size * n_generations)
    DSR n_trials = 누적 총 생성 수
    """
```

**위험**: evolution이 과적합 기계가 될 수 있다. DSR n_trials를 누적해야 하며, 최종 리포트에서 "N세대 × M개 = 총 K개에서 생존 L개"를 공개해야 한다.

**완료 기준**: 3세대 × 50개 = 150개 누적 budget + DSR 정확 + plateau 우선 정렬.

---

## 5. 격리 장치

### 5.1 허상 전략 공장 방지

| 장치 | 구현 위치 | 강도 |
|---|---|---|
| **DSR n_trials = 총 생성 수** | gates.py | 필수. 우회 불가 |
| **baseline 강제 표시** | report.py | 필수. baseline 없으면 리포트 생성 거부 |
| **verdict 기본값 = "rejected"** | databank.py | 필수. validation 통과해야 승격 |
| **source = "strategy_builder"** | genome.py | 필수. registry 전략과 분리 |
| **search budget 첫 줄** | report.py | 필수. 생존율부터 보여줌 |
| **turnover gate** | filters.py | 필수. 고회전 = 세금 폭탄 사전 제거 |
| **exemption utilization** | report.py | 권장. 250만 공제 분산 효율 표시 |

### 5.2 결과를 "연구 후보"로만 다루는 장치

- `CandidateEntry.verdict`는 `"rejected"` → `"research_candidate"` → `"finalist"` 3단계만
- `"confirmed"`, `"production"`, `"recommended"` 같은 verdict는 **존재하지 않음**
- 리포트 footer에 고정 문구: `"이 결과는 연구 후보이며 투자 결정의 근거가 아닙니다."`
- finalist도 "Q60S40 B&H 대비 얼마나 다른가"를 반드시 표시

### 5.3 폐기/보관 정책

| verdict | genome | engine_result | validation | 보관 |
|---|---|---|---|---|
| rejected (구조 불량) | ❌ | ❌ | ❌ | 카운트만 |
| rejected (baseline 미달) | ✅ 1줄 | ❌ | ❌ | 요약만 |
| rejected (validation 실패) | ✅ | ❌ | ✅ 요약 | 요약 |
| research_candidate | ✅ 전체 | ✅ 전체 | ✅ 전체 | 전체 |
| finalist | ✅ 전체 | ✅ 전체 | ✅ 전체 | 전체 + 세후 분해 |

---

## 6. 추천 구현 순서

| PR | 내용 | 코어 변경 | 예상 규모 | 선행 조건 |
|---|---|---|---|---|
| **PR1** | weight_schedule 코어 확장 | ✅ (최소) | ~50줄 + 테스트 | golden baseline 통과 |
| **PR2** | genome + 블록 풀 + 생성기 | ❌ | ~400줄 + 테스트 | PR1 |
| **PR3** | 파이프라인 + 필터 + 리포트 | ❌ | ~500줄 + 테스트 | PR2 |
| **PR4** | evolution (선택) | ❌ | ~200줄 + 테스트 | PR3 |

---

## 7. DCA 세후 특수 게이트 (aftertaxi 고유)

일반적인 Strategy Builder에는 없지만, 이 프로젝트에서 반드시 넣어야 하는 게이트:

| 게이트 | 기준 | 이유 |
|---|---|---|
| **세후 배수 기준** | mult_after_tax 기준으로 순위 | 세전 승자 ≠ 세후 승자 |
| **연간 회전율** | < 100% 우선 | 회전 = 세금 실현 |
| **250만 공제 활용** | 연간 매도 이익을 250만 이하로 분산하는 전략 가산점 | DCA 고유 |
| **ISA 최적화** | ISA 계좌에서의 전환세 면제 활용 여부 | 한국 고유 |
| **plateau 우선** | 파라미터 ±1 변경 시 결과 안정성 | 과적합 방지 |
| **B&H 대비 세후 delta** | baseline보다 낮으면 자동 폐기 | 이 프로젝트의 핵심 결론 존중 |

---

## 한 줄 결론

**하나만 먼저 만든다면: PR1 (weight_schedule 코어 확장) — 이것 없이는 나머지 전부 불가능하고, 이것만으로도 수동 신호 전략 실험이 즉시 가능해진다.**
