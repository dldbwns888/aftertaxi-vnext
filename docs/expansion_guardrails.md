# 확장 규칙 — 금지선과 권장선

## 핵심 원칙

> 코어는 보호하고, 바깥을 확장한다.

## 확장 권장 (✅ 자유롭게)

| 영역 | 예시 | 이유 |
|---|---|---|
| **strategies/** | 새 빌더, metadata, compile 확장 | 코어 무관 |
| **validation/** | 새 검증 도구, 새 리포트 | 결과 읽기만 |
| **lanes/** | Lane D 고도화, 새 lane | facade 호출만 |
| **loaders/** | 새 데이터 소스, 캐시 개선 | 코어 무관 |
| **workbench/** | compare, export, view model | 결과 읽기만 |
| **apps/** | CLI 옵션, Streamlit, API | compile 경유 |
| **tests/** | 새 golden, 새 시나리오 | 항상 환영 |
| **docs/** | quickstart, 해석 가이드 | 항상 환영 |

## 확장 주의 (⚠ 설계 먼저)

| 영역 | 예시 | 조건 |
|---|---|---|
| **contracts.py** 필드 추가 | PersonSummary 확장, 새 AccountSummary 필드 | characterization test 먼저 |
| **settlement.py** 순서 변경 | 새 세금 종류 삽입 | 기존 golden 통과 확인 |
| **tax_engine.py** 공식 추가 | 종합과세 누진 | 설계 문서 + 테스트 먼저 |
| **runner.py** 단계 추가 | 새 월간 이벤트 | 기존 oracle shadow 통과 |

## 확장 금지 (❌ 당분간)

| 영역 | 이유 |
|---|---|
| **ledger.py 대수술** | 관리 가능 상태. 분해는 2개 이상 기능 추가 후 |
| **FIFO/HIFO lot method** | 한국용 AVGCOST 전용. 복잡도 비용 > 기능 가치 |
| **BUDGET rebalance** | 파라미터 의미론 비용 > 이득 |
| **PENSION 계좌** | 별도 세금 체계. 독립 설계 필요 |
| **runner에 정책 분기 추가** | settlement로 위임. runner는 순서만 |
| **새 레포 분리** | vnext 안에서만 확장 |
| **facade 시그니처 변경** | 하위 호환 깨짐 |

## 기능 추가 시 판단 기준

```
"실제 돈 상태를 바꾸는가?"
  → YES: core (설계 먼저, golden 필수)
  → NO: 아래 계속

"결과를 평가/반증하는가?"
  → YES: validation/

"다른 세계/데이터 생성 방식인가?"
  → YES: lane

"보여주기/입출력 편의인가?"
  → YES: workbench/apps/

"입력 형식 변환인가?"
  → YES: strategies/compile
```

## 계약 변경 시 필수 절차

1. characterization test 추가 또는 기존 golden 확인
2. oracle shadow 통과
3. 변경 사유 커밋 메시지에 기록
4. docs/core_boundary_guide.md 업데이트

## 현재 NotImplementedError (의도적 보류)

| 기능 | 파일 | 상태 |
|---|---|---|
| BUDGET rebalance | facade.py | 보류 (정책 복잡성) |
| FIFO/HIFO lot method | facade.py | **scope outside** (한국용 AVGCOST 전용) |
| PENSION 계좌 | compile.py | 보류 (별도 세금) |
| 종합과세 누진 | tax_engine.py | **✅ 구현 완료** |
| Lane D FX 랜덤화 | synthetic.py | 보류 (preserve_fx=True) |
