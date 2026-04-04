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
# 576+ passed
```

## 데이터 주의사항

- **합성 데이터**: 빠른 아이디어 검토용. 실제 시장과 다를 수 있음. 멀티자산은 첫 번째 자산만 사용.
- **yfinance**: Close = split-adjusted, 배당 미반영. 총수익률과 차이 있음.
- **세금 계산**: 한국 세법 기반이지만 모든 예외를 커버하지 않음. 실전 의사결정 전 세무사 확인 권장.
- **이 도구는 연구용 워크벤치**이며 투자 조언이 아닙니다.

## 한계 (솔직하게)

이 엔진은 **"세후 투자 아이디어를 빠르게 탐색하는 연구 도구"**입니다.
**"신뢰도 높은 실전 투자 의사결정 플랫폼"이 아닙니다.**

알아야 할 것:
- FX-only 최소 백테스트 실행기입니다. 체결 현실(슬리피지, 호가, 분할매매)은 모사하지 않습니다.
- AVGCOST 전용. FIFO/HIFO는 미지원.
- BUDGET 리밸런싱, PENSION 계좌는 미구현.
- 합성 데이터에서 멀티자산 상관관계는 제한적입니다.
- 테스트 576개는 소프트웨어 안정성이지, 금융모델 타당성 보증이 아닙니다.
- 결과를 실전 진실로 받아들이기 전에 데이터 품질과 세법 예외를 직접 검증하세요.

## 개선 로드맵

한계를 인정하고 끝내지 않습니다. 이 순서로 신뢰도를 올리고 있습니다.

| 버전 | 목표 | 상태 |
|---|---|---|
| **v1.1** | 데이터 신뢰도 — provenance, fingerprint, source 분리 | ✅ 완료 |
| **v1.2** | 세금 검증 — 골든 tax case, 실제 예시 대조, 지원 범위 명문화 | 🔧 진행중 |
| v1.3 | 실행 현실성 — 슬리피지/체결 정책 레이어 | 📌 계획 |
| v1.4 | 검증 게이트화 — validation grade 기본 노출, 성과보다 검증 우선 | 📌 계획 |

**장기 목표**: 연구용 워크벤치 → 신뢰 가능한 의사결정 보조 도구

## 새 전략 추가

→ [docs/add_strategy.md](docs/add_strategy.md)

## 라이선스

Private research use.
