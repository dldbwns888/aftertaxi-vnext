# 코어 경계 가이드
#
# "다음에 기능 붙일 때 여기를 건드려라"

## 역할 분담

```
facade.py
  │  단일 진입점. 미구현 설정 검증.
  │  여기에 새 설정 검증을 추가한다.
  │
  ├─ runner.py
  │    월 루프. 실행 순서만 관리.
  │    새 "월간 이벤트"는 여기에 추가 (예: 월배당, 리밸, deposit).
  │    세금 계산/정산 로직은 넣지 않는다.
  │
  │    ├─ allocation.py
  │    │    "누구에게 얼마" 결정. ledger를 안 건드린다.
  │    │    새 배분 정책은 여기에 추가 (예: overflow, spill-over).
  │    │
  │    ├─ ledger.py
  │    │    상태 원자성. cash/position/tax state 갱신.
  │    │    새 "상태 필드"는 여기에 추가 (예: pending_cash, drip_qty).
  │    │    세금 계산은 tax_engine에 위임한다.
  │    │
  │    └─ settlement.py
  │         정산 순서. "언제 무엇을 어떤 순서로" 정산할지.
  │         새 "세금 종류"는 여기에 순서를 추가한다 (예: 종합과세).
  │         settlement이 ledger 메서드를 호출하는 순서가 의미다.
  │
  └─ tax_engine.py
       순수 세금 계산. 입력 → 출력, 상태 없음.
       새 "세금 공식"은 여기에 추가 (예: 누진세율, 건보료 변경).
```

## 기능별 수정 가이드

### 새 세금 종류 추가 (예: 종합과세 누진)
1. `tax_engine.py`에 순수 계산 함수 추가
2. `ledger.py`에 세금 버킷 필드 추가 (`_comprehensive_tax_assessed_krw`)
3. `settlement.py`에 정산 순서 삽입 (기존 순서 사이에)
4. `contracts.py` AccountSummary에 필드 추가
5. **runner.py는 안 건드린다**

### 새 리밸런스 정책 (예: BAND)
1. `contracts.py` RebalanceMode에 enum 추가
2. `facade.py` _validate_config()에서 NotImplementedError 제거
3. `runner.py`에 `_execute_band_rebalance()` 추가
4. `allocation.py` AccountOrder에 band 관련 정보 추가
5. **settlement.py, tax_engine.py는 안 건드린다**

### 새 계좌 유형 (예: PENSION)
1. `contracts.py` AccountType에 enum 추가
2. `contracts.py` TaxConfig에 연금 관련 세율 추가 (또는 프리셋)
3. `runner.py` ledger 생성 시 PENSION 세율 매핑
4. `settlement.py`에 PENSION 정산 분기 추가
5. `tax_engine.py`에 연금 세금 계산 추가 (필요 시)

### 새 데이터 필드 (예: pending_cash, DRIP)
1. `ledger.py`에 필드 추가
2. `ledger.py`의 관련 메서드에서 상태 갱신
3. `ledger.summary()`에 노출
4. `contracts.py` AccountSummary에 필드 추가

### 새 Lane
1. `lanes/lane_X/` 디렉토리 생성
2. `facade.py`를 호출하는 `run.py` 작성
3. **코어를 안 건드린다. facade만 호출한다.**

## 절대 하지 말 것

- runner에 세금 계산 로직 넣기 (→ tax_engine으로)
- runner에 정산 순서 넣기 (→ settlement로)
- settlement에서 ledger를 직접 생성하기 (ledger는 runner가 생성)
- ledger에서 다른 ledger 참조하기 (계좌 간 의존 금지)
- allocation에서 ledger를 직접 수정하기 (의도만 반환)
- lane에서 core 내부를 직접 import하기 (facade만)
- validation에서 core 상태를 변경하기 (읽기 전용)

## 폭발 위험 지점

### ledger.py (현재 444줄, 19 메서드)
가장 커질 가능성이 높다.
다음 중 2개 이상이 추가되면 분해를 고려:
- pending_cash (매수 대기 현금)
- drip_state (배당 재투자 전용 상태)
- split_history (주식 분할)
- margin_state (마진)

분해 방향: cash_state / position_book / tax_state / dividend_state

### runner.py (현재 335줄)
월 루프에 기능이 계속 붙으면 비대해진다.
현재: MTM → year_settle → dividend → deposit → buy → record
다음 추가 후보: split adjustment, execution delay, cash pending
→ 각 단계를 named function으로 분리해두면 나중에 runner를 pipeline으로 전환 가능
