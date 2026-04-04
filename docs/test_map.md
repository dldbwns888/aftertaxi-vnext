# 테스트 맵

## 🔴 빨간불 — 깨지면 엔진이 변한 것

| 파일 | 역할 | 깨지면 |
|---|---|---|
| `test_golden_baseline.py` (4) | 리팩터링 안전망. seed=42 고정 결과. | 엔진/세금/배분 로직 변경 |
| `test_tax_golden.py` (15) | 세법 정확도. 법 조항 + 수기 대조. | 세금 계산 오류 |
| `test_oracle_shadow.py` (8) | 기존 aftertaxi 대비 동일 결과. | 코어 회귀 |

## 🟡 노란불 — 깨지면 계약이 흔들린 것

| 파일 | 역할 |
|---|---|
| `test_compile_strict.py` (4) | compile strict mode 계약 |
| `test_compile_merge.py` (11) | 세금 preset merge 규칙 |
| `test_apply_patch.py` (9) | Advisor patch 안전성 |
| `test_cross_feature.py` (9) | BAND+누진, 이월결손금 교차 |
| `test_deposit_ownership.py` (5) | deposit 원자성 |
| `test_bug_report.py` (6) | 버그 리포트 회귀 방지 |

## 🟢 초록불 — 기능 테스트

나머지 전부. 개별 기능의 동작 검증.

## 빠른 확인

```bash
# 핵심만 (30초)
pytest tests/test_golden_baseline.py tests/test_tax_golden.py -v

# 계약 (1분)
pytest tests/test_golden_baseline.py tests/test_tax_golden.py tests/test_compile_strict.py tests/test_apply_patch.py tests/test_cross_feature.py -v

# 전체 (45초)
pytest tests/ -q
```
