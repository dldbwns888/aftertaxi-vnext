# Primary 승격 체크리스트

## 승격 판단: ✅ 준비 완료

aftertaxi-vnext는 aftertaxi(v3.1.0-freeze)를 구조적으로 대체할 수 있는 상태.

---

## 1단계: 코어 잠금 ✅

| 항목 | 상태 | 근거 |
|---|---|---|
| Oracle shadow 8/8 통과 | ✅ | 기존 엔진과 동일 숫자 (21 tests) |
| Oracle shadow 분류 완료 | ✅ | 481 tests → must-match/expected-delta/known-unsupported |
| Characterization golden | ✅ | 손계산 대조 포함 20 tests |
| Settlement 직접 테스트 | ✅ | year_end/final/건보료 12 tests |
| 코어 경계 문서 | ✅ | docs/core_boundary_guide.md |
| 세금 불변식 | ✅ | gross=usd×fx, net=gross-unpaid, assessed=paid+unpaid |

## 2단계: 기능 승계 ✅

| 항목 | 상태 | 근거 |
|---|---|---|
| strategies/registry | ✅ | 7종 빌더 + JSON 지원 |
| PersonSummary | ✅ | person-scope liability 분리 |
| validation/ 16 tools | ✅ | basic(5)+statistical(5)+stability(3)+robustness(2)+stress(1) |
| stress.py | ✅ | 랜덤 시장 생존 null test |
| Lane B 2-mode | ✅ | Overlap + Structural + CalibrationReport |
| allocation.py | ✅ | AllocationPlanner + priority |
| annual_cap + allowed_assets | ✅ | runner에서 구현 |

## 3단계: 플랫폼화 ✅

| 항목 | 상태 | 근거 |
|---|---|---|
| strategies/compile | ✅ | JSON → BacktestConfig |
| README 승격 | ✅ | Primary-candidate Engine |
| workbench 실연결 | ✅ | compile → engine → workbench payload |

---

## 코어 안정성 수치

```
소스: ~47 파일, ~7,500줄
테스트: ~31 파일, ~8,500줄, 320+ tests
비율: 소스 : 테스트 = 1.0 : 1.13
실행 시간: ~36초 (API 의존 제외)
```

## Known Limitations (미구현, 의도적)

| 기능 | 상태 | 이유 |
|---|---|---|
| BAND rebalance | NotImplementedError | 파라미터 의미론 비용 > 이득. 후순위. |
| BUDGET rebalance | NotImplementedError | 사실상 세금 예측 엔진. 신중 재검토 필요. |
| PENSION 계좌 | NotImplementedError | 별도 세금 체계 필요. |
| FIFO/HIFO lot method | NotImplementedError | AVGCOST만 지원. |
| 종합과세 누진구간 | 미착수 | 현재 고정 세율 MVP. |
| Lane D (execution realism) | 미착수 | 코어 parity 후 순위. |
| 건보료 멀티 계좌 분배 | MVP 한계 | 첫 TAXABLE에 전액 귀속. person 권위값 분리 완료. |

## aftertaxi와의 관계

```
aftertaxi (v3.1.0-freeze)
  - 상태: 유지보수 최소. 새 기능 추가 없음.
  - 역할: 연구 자산 보존, oracle shadow 기준선
  - 413 tests, 26,522줄

aftertaxi-vnext (active)
  - 상태: 사실상 primary. 모든 새 개발은 여기서.
  - 역할: 세후 퀀트 플랫폼 본체
  - 320+ tests, ~7,500줄
```

## 승격 후 변경 규칙

1. **코어 계약 변경은 characterization test 통과 필수**
   - EngineResult, AccountSummary, TaxSummary 필드 변경 시
   - golden 값 변동 시 변경 사유 기록

2. **새 기능은 코어 밖에 추가**
   - 새 세금: tax_engine → ledger 버킷 → settlement 순서
   - 새 전략: strategies/builders.py에 함수 하나
   - 새 검증: validation/에 모듈 추가
   - docs/core_boundary_guide.md 참조

3. **미구현 설정은 명시적 예외 유지**
   - facade._validate_config()에서 차단
   - silently ignored 금지

4. **테스트 비율 1.0 이상 유지**

## 향후 (maintenance + selective enhancements)

- BAND: 필요 시 좁은 버전 (threshold 1개)으로 시작
- BUDGET: 설계 문서 먼저, 구현은 그 후
- Lane D: 별도 설계 후
- rename: 안정화 후 판단 (aftertaxi-vnext → aftertaxi 또는 quant-platform)
