# 새 전략 추가 가이드

3개 파일, 10분이면 됩니다.

## 1단계: metadata 등록 (strategies/metadata.py)

```python
StrategyMetadata(
    key="my_strategy",           # 고유 키
    label="내 전략",              # UI 표시명
    description="설명",
    builder="build_my_strategy",  # 빌더 함수명
    params=[
        ParamSchema("lookback", "int", 12, label="룩백 (월)"),
        ParamSchema("threshold", "float", 0.05, label="임계값"),
    ],
)
```

`_REGISTRY` dict에 추가하면 CLI/GUI에 자동 노출됩니다.

## 2단계: 빌더 함수 (strategies/builders.py)

```python
def build_my_strategy(params: dict) -> StrategyConfig:
    lookback = params.get("lookback", 12)
    return StrategyConfig(
        name="my_strategy",
        weights={"SPY": 0.6, "TLT": 0.4},
        rebalance_every=lookback,
    )
```

StrategyConfig의 핵심 필드:
- `name`: 식별자
- `weights`: `{자산: 비중}` dict (합 = 1.0)
- `rebalance_every`: 리밸런싱 주기 (월)

## 3단계: compile 연결 (strategies/compile.py)

`compile_strategy()`가 metadata의 `builder` 이름으로 자동 매칭합니다.
**대부분의 경우 compile.py를 건드릴 필요 없습니다.**

## 테스트

```bash
# 빠른 확인
aftertaxi - --months 24 <<< '{"strategy": {"type": "my_strategy"}}'

# 또는 JSON 파일
echo '{"strategy": {"type": "my_strategy", "params": {"lookback": 6}}}' > my.json
aftertaxi my.json
```

## 전략이 받는 compile 흐름

```
JSON/GUI payload
  → compile_strategy(payload)
    → metadata에서 builder 찾기
    → builder(params) → StrategyConfig
  → compile_accounts(payload)
    → AccountConfig (세금/ISA/리밸 설정)
  → BacktestConfig
    → run_backtest()
```

## 주의사항

- `weights` 합은 반드시 1.0
- 자산 티커는 데이터 소스에 존재해야 함 (yfinance 기준)
- 합성 데이터는 첫 번째 자산만 사용 (multi-asset은 실제 데이터 권장)
- rebalance_every=1이면 매월, 12면 매년
