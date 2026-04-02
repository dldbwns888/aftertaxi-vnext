# Quickstart — 5분 안에 첫 백테스트

## 1. 설치

```bash
git clone https://github.com/dldbwns888/aftertaxi-vnext.git
cd aftertaxi-vnext

# 기본 (코어만)
pip install -e .

# 전체 (데이터+GUI+병렬+개발도구)
pip install -e ".[all]"

# 필요한 것만
pip install -e ".[data]"      # yfinance
pip install -e ".[gui]"       # streamlit
pip install -e ".[parallel]"  # joblib
```

## 2. 가장 빠른 실행 (CLI)

JSON 파일 하나로 백테스트:

```bash
# config.json 생성
echo '{"strategy":{"type":"q60s40"}}' > config.json

# 실행 (합성 데이터, 20년)
aftertaxi config.json --months 240
```

출력:
```
═══ 세후 DCA 백테스트 결과 ═══
  기간: 240개월 (20.0년)
  투입:     $     240,000
  세전 PV:  $     413,221  (1.72x)
  세후 PV:  ₩ 495,865,200  (1.59x)
  MDD:            -18.3%
  세금 drag:      7.5%
```

## 3. 실제 ETF 데이터로 실행

```bash
# 실제 SPY 데이터 (yfinance)
echo '{"strategy":{"type":"spy_bnh"},"accounts":[{"type":"TAXABLE","monthly_contribution":1000}]}' > spy.json

aftertaxi spy.json --months 120
```

## 4. 전략 비교 (CLI + Lane D)

```bash
# Q60S40 + Lane D 합성 생존 시뮬레이션
echo '{"strategy":{"type":"q60s40"}}' > q60.json

aftertaxi q60.json --months 240 --lane-d --lane-d-paths 20 --lane-d-years 50
```

## 5. GUI (Streamlit)

```bash
pip install streamlit
streamlit run src/aftertaxi/apps/gui/streamlit_app.py
```

브라우저에서:
1. 사이드바에서 전략 선택
2. 계좌 설정
3. "백테스트 실행" 클릭

## 6. Python API

```python
from aftertaxi.strategies.compile import compile_backtest
from aftertaxi.core.facade import run_backtest
from aftertaxi.apps.data_provider import load_market_data

# 전략 정의
config = compile_backtest({
    "strategy": {"type": "q60s40"},
    "accounts": [
        {"type": "ISA", "monthly_contribution": 300},
        {"type": "TAXABLE", "monthly_contribution": 700},
    ],
    "n_months": 240,
})

# 데이터 로드 (합성)
data = load_market_data(
    list(config.strategy.weights.keys()),
    source="synthetic", n_months=240,
)

# 실행
result = run_backtest(config, returns=data.returns,
                      prices=data.prices, fx_rates=data.fx)

print(f"세전 {result.mult_pre_tax:.2f}x, 세후 {result.mult_after_tax:.2f}x")
```

## 7. 등록된 전략 목록

| 키 | 이름 | 비중 |
|---|---|---|
| `q60s40` | Q60S40 (코어) | QQQ 60% + SSO 40% |
| `spy_bnh` | SPY Buy & Hold | SPY 100% |
| `qqq_bnh` | QQQ Buy & Hold | QQQ 100% |
| `6040` | 전통 60/40 | SPY 60% + TLT 40% |
| `qqq_1.4x` | QQQ 1.4x | QLD 40% + QQQ 60% |
| `equal_weight` | 동일 비중 | 커스텀 |
| `custom` | 사용자 정의 | 커스텀 |

## 8. JSON 설정 형식

```json
{
  "strategy": {
    "type": "q60s40",
    "params": {"rebalance_every": 1}
  },
  "accounts": [
    {"type": "ISA", "monthly_contribution": 300, "priority": 0},
    {"type": "TAXABLE", "monthly_contribution": 700, "priority": 1}
  ],
  "n_months": 240,
  "enable_health_insurance": false,
  "dividend_yields": {"QQQ": 0.005, "SSO": 0.01}
}
```

## 9. 다음 단계

- [코어 경계 가이드](core_boundary_guide.md) — 기능별 수정 가이드
- [확장 규칙](expansion_guardrails.md) — 금지선과 권장선
- [Lane D 설계](lane_d_design.md) — 실행 마찰 + 합성 생존
- [Oracle Shadow 분류](oracle_shadow_classification.md) — 기존 엔진 대비 검증
