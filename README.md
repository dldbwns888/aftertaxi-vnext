# aftertaxi-vnext

한국 거주자의 해외 ETF 적립식 세후 백테스트 엔진.

## 설치 (30초)

```bash
git clone https://github.com/dldbwns888/aftertaxi-vnext.git
cd aftertaxi-vnext
pip install -e . --break-system-packages
```

## 첫 실행

```bash
# CLI
aftertaxi examples/01_spy_basic.json

# Streamlit GUI
streamlit run src/aftertaxi/apps/gui/streamlit_app.py
```

## 예제

| 파일 | 설명 |
|---|---|
| `examples/01_spy_basic.json` | SPY 100% B&H, 20년 |
| `examples/02_q60s40_isa.json` | QQQ+SSO 6:4, ISA 우선 |
| `examples/03_progressive_tax.json` | 종합과세 누진 |
| `examples/04_band_rebalance.json` | BAND 5% 리밸런싱 |
| `examples/05_full_setup.json` | ISA+누진+BAND 전체 조합 |

## 아키텍처

```
apps/          CLI, Streamlit, Memory
  ↓
intent/        자연어 의도 → 구조화
advisor/       진단 + 제안 (계산 금지, 판단만)
  ↓
strategies/    전략 빌더 + compile + metadata
  ↓
core/          엔진 (facade → runner → settlement → ledger → tax_engine)
  ↓
validation/    검증 (DSR, PSR, PBO, walk-forward)
lanes/         Lane A~D (benchmark, 비교, tax-alpha, 합성 생존)
workbench/     분석 도구 (compare, sensitivity, tax_savings, interpret)
```

## 핵심 기능

- **세후 백테스트**: 양도세 22% + 누진세 8구간 + ISA 비과세 + 이월결손금 5년
- **TAXABLE / ISA**: 계좌별 세금 정책, 연간 납입 한도 (KRW), priority 기반 배분
- **3가지 리밸런싱**: CONTRIBUTION_ONLY / FULL / BAND
- **Advisor**: 세금 drag, ISA 활용, MDD 진단 → 개선 제안 (max 3)
- **Lane D**: 합성 경로 생존성 (sign-flip, HMM regime)
- **초보자/고급 모드**: Streamlit GUI

## 테스트

```bash
pytest tests/ -q
# 558 passed
```

## 새 전략 추가

→ [docs/add_strategy.md](docs/add_strategy.md)

## 라이선스

Private research use.
