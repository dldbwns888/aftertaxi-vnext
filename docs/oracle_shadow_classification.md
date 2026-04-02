# Oracle Shadow 분류 — aftertaxi → vnext
#
# 기존 aftertaxi 테스트 24파일 (481 tests)을 3분류:
#   MUST-MATCH: vnext가 같은 숫자를 내야 하는 핵심 세후 로직
#   EXPECTED-DELTA: vnext가 의도적으로 다른 결과를 내는 것 (설명 필요)
#   KNOWN-UNSUPPORTED: vnext에 없는 기능 (NotImplementedError)
#
# 추가로: NOT-APPLICABLE (어댑터/파이프라인, vnext 범위 밖)

# ══════════════════════════════════════════════
# MUST-MATCH (FX-only 코어, 세금, 정산)
# ══════════════════════════════════════════════
#
# 이 테스트들은 vnext가 동일한 숫자를 내야 primary 승격 근거가 된다.
#
# test_portfolio_runner_fx.py (35)
#   - B&H DCA: qty, avg_cost, realized_gain, tax, PV
#   - FULL rebalance: sell qty, sell-before-buy
#   - C/O: zero sells, qty tracking
#   - Year boundary tax
#   → 핵심 중의 핵심. 이게 안 맞으면 엔진이 틀린 것.
#
# test_broker_reconciliation.py (28)
#   - 실제 브로커 시나리오 재현
#   - gain case: qty, avg_cost, realized, tax, loss_cf, cash, net_value
#   - loss carryforward: multi-year, vintage expiry
#   → 세후 숫자 신뢰의 핵심.
#
# test_avgcost_holding.py (15)
#   - AVGCOST 원가 추적
#   - 부분 매도, 추가 매수 후 원가 변동
#   → vnext ledger의 Position.avg_cost 로직과 직접 매핑.
#
# test_tax_carryforward.py (11)
#   - 손실이월 연도별 관리
#   - 5년 만료
#   - 다년도 이월+상쇄
#   → vnext ledger.loss_carryforward_krw와 직접 매핑.
#
# test_fx_book.py (36)
#   - FX 원가 기록, 환율 변동, 원화 환산
#   → vnext ledger의 KRW 원가 추적과 매핑.
#
# test_fx_book_v3_invariants.py (23)
#   - FX book 불변식 (cash ≥ 0, position ≥ 0, assessed = paid + unpaid)
#   → vnext contracts.py 불변식과 직접 대응.
#
# test_fx_deposit_contract.py (9)
#   - FX 모드 입금 계약
#   → vnext ledger.deposit()과 매핑.
#
# test_golden_broker_cases.py (3)
# test_golden_system_cases.py (4)
#   - 고정된 golden 값과 비교
#   → vnext characterization test의 원형.
#
# test_runner_fx_date_rules.py (18)
#   - 날짜/연도 전환 규칙
#   → vnext runner의 year boundary 로직.
#
# test_runner_fx_dirty_cases.py (17)
#   - edge case: NaN, 짧은 데이터, 빈 포지션 등
#   → vnext의 방어 코드 검증.
#
# 소계: ~199 tests


# ══════════════════════════════════════════════
# EXPECTED-DELTA (vnext가 의도적으로 다른 것)
# ══════════════════════════════════════════════
#
# test_engine_v2.py (10)
#   - FIFO lot method 포함
#   → vnext는 AVGCOST만 지원. FIFO 테스트는 skip.
#   → AVGCOST 관련 테스트만 must-match.
#
# test_v2_contract.py (23)
#   - 일부 BUDGET/LEGACY 의존
#   - 손실이월 빈티지 만료 → must-match
#   - 세금 네이밍/alias → expected-delta (vnext는 typed)
#   - BUDGET conservative → known-unsupported
#
# test_ledger_fx_integration.py (23)
#   - legacy/FX 공존 테스트
#   → vnext는 FX-only. legacy 경로 테스트는 해당 없음.
#   → FX 경로 테스트만 must-match.
#
# test_runner_fx.py (23)
#   - 일부 legacy mode 참조
#   → FX-only 부분만 must-match.
#
# 소계: ~79 tests (부분 must-match, 부분 skip)


# ══════════════════════════════════════════════
# KNOWN-UNSUPPORTED (vnext에 없는 기능)
# ══════════════════════════════════════════════
#
# test_budget_and_naming.py (7)
#   - BUDGET 리밸 모드
#   → vnext NotImplementedError. 전부 skip.
#
# test_acceptance.py (9)
#   - BUDGET 포함 수용 테스트
#   → BUDGET 제외한 나머지는 must-match 후보.
#
# test_integrity_matrix.py (67)
#   - BAND/BUDGET 의존 테스트 포함
#   → FX-only + C/O + FULL 부분만 must-match.
#   → BAND/BUDGET 부분은 known-unsupported.
#
# 소계: ~83 tests (대부분 skip, 일부 부분 must-match)


# ══════════════════════════════════════════════
# NOT-APPLICABLE (vnext 범위 밖)
# ══════════════════════════════════════════════
#
# test_adapter_validation.py (22) — vectorbt adapter
# test_finrl_adapter.py (29) — finrl adapter
# test_visualization_extract.py (1) — 시각화
# test_pipeline_backup.py (18) — 데이터 파이프라인
# test_pipeline_ecos.py (14) — ECOS 데이터
# test_pipeline_store.py (16) — DuckDB 스토어
#
# 소계: 100 tests (전부 skip)


# ══════════════════════════════════════════════
# 요약
# ══════════════════════════════════════════════
#
# MUST-MATCH:        ~199 tests (11개 파일)
# EXPECTED-DELTA:     ~79 tests (4개 파일, 부분 must-match)
# KNOWN-UNSUPPORTED:  ~83 tests (3개 파일, 대부분 skip)
# NOT-APPLICABLE:    ~100 tests (6개 파일, 전부 skip)
#
# 1단계 종료 조건:
#   1. MUST-MATCH 전부 통과 (또는 차이 원인 문서화)
#   2. EXPECTED-DELTA 차이 원인 전부 문서화
#   3. KNOWN-UNSUPPORTED 명시적 skip + 문서
#
# 우선순위:
#   P0: test_portfolio_runner_fx (35) — 엔진 핵심 경로
#   P0: test_broker_reconciliation (28) — 세후 숫자 신뢰
#   P0: test_golden_* (7) — golden 값 비교
#   P1: test_avgcost_holding (15) — 원가 추적
#   P1: test_tax_carryforward (11) — 손실이월
#   P1: test_fx_book* (59) — FX 원가/불변식
#   P2: test_runner_fx_date_rules (18) — 날짜 규칙
#   P2: test_runner_fx_dirty_cases (17) — edge cases
