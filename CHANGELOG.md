# Changelog

## v1.0.0 (2026-04)

### 구조
- Service layer (`apps/service.py`) — 앱↔코어 분리
- `experiments/` — memory, fingerprint 분리
- `analysis/` — workbench 리네임 (re-export 하위호환)
- Compile strict mode
- Golden baseline 4개 잠금

### 세금 검증
- `docs/tax_scope.md` — 지원/미지원 명세
- 세금 golden 15 cases (3자 대조)
- 종합과세 누진 8구간

### 분석
- ISA 최적화 (`optimize_isa`)
- KRW attribution 분해 (자산/환율/세금)
- 세금 구조 해석 (`interpret_tax_structure`)
- Advisor 2.0 (종합 판단)
- 파라미터 sweep
- 자산별 기여 + underwater 분석

### UX
- 전략 빌더 wizard (안전/균형/공격/직접)
- Advisor 원클릭 재실행
- Baseline 자동 비교 (SPY B&H)
- 연도별 세금 분해 (실제 데이터)

### 검증
- `run_validated_strategy()` — DSR/PSR/CUSUM
- decision_support mode
- DataProvenance 정식 승격

### 배포
- MIT License
- Streamlit Cloud 준비
- 로컬 원클릭 런처 (start.bat/sh)

### 코어
- PR A~D 리팩터 (deposit/compile/runner/settlement)
- BAND rebalance
- HMM regime paths (Lane D)
- 602 tests
