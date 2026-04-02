# Lane D 설계안 — Execution Realism
#
# 상태: 설계 문서만. 구현 미착수.
# 코어 영향: 중간 (runner 경로에 새 단계 추가 가능)
# 우선순위: 후순위 (primary 승격 후)

## 질문

Lane D가 답하는 질문:
> "백테스트 숫자와 실제 실행 사이에 얼마나 차이가 나는가?"

기존 Lane들의 역할:
- Lane A: "실제 ETF + FX로 돌리면?" (현실 데이터)
- Lane B: "장기 구조적으로 살아남는가?" (합성 역사)
- Lane C: "운이 나쁘면 어떻게 되는가?" (분포)
- Lane D: "실제로 매매하면 얼마나 깎이는가?" (실행 마찰)

## Lane D가 모델링해야 할 것

### 1. 슬리피지 / 시장충격
- 지정가 ≠ 체결가
- 시장충격: σ × √(Q/V) (제곱근 법칙, 선형 아님)
- ETF 스프레드 (AUM, 거래량 의존)

### 2. 실행 지연
- 시그널 발생 → 실제 매매까지 1~N일
- 월말 리밸 신호 → 익영업일 체결
- 공휴일, 마감 후 시그널

### 3. 환전 마찰
- 실제 USD/KRW 환전 시 스프레드 (보통 10~50원/달러)
- 증권사별 환전 비용 차이
- 환전 타이밍 (매수 전? 매도 후?)

### 4. 배당 재투자 지연
- 배당 지급 → 재투자까지 N일
- 현금 유휴 기간

### 5. 세금 납부 타이밍
- 양도세 5월 확정신고 (실현 시점 ≠ 납부 시점)
- 현금 보유 필요 (세금 납부용)

## 구현 방안 (3가지 후보)

### 방안 A: haircut model (가장 싸고 안전)
- 코어 안 건드림
- Lane D = "Lane A 결과에 실행 비용 haircut 적용"
- `execution_haircut(result, slippage_bps=5, fx_spread=20, delay_months=0)`
- 결과: "실행 후 예상 배수" = 원래 배수 × haircut_factor

**장점:** 구현 1시간, 코어 무관, 해석 쉬움
**단점:** 정밀하지 않음, 경로 의존 효과 무시

### 방안 B: post-processor (중간)
- 엔진 결과(월별 PV)에 실행 마찰을 사후 적용
- 월별 PV에서 slippage/delay 효과를 빼는 방식
- `simulate_execution_friction(monthly_values, config)`

**장점:** 코어 무관, 경로 의존 일부 반영
**단점:** 정밀도 중간, "실행 마찰이 컸던 달"을 역추정

### 방안 C: runner 확장 (가장 정밀하지만 위험)
- runner 월 루프에 execution_delay, slippage 단계 추가
- `_execute_with_slippage(ledger, orders, slippage_model)`

**장점:** 가장 정밀
**단점:** 코어 비대화, 테스트 표면적 급증, 정산 순서 영향

## 추천

**1차: 방안 A (haircut model)**로 시작.
- lanes/lane_d/haircut.py
- 코어 무관
- 테스트 쉬움
- Lane A 결과에 적용하는 순수 함수

**2차: 필요 시 방안 B로 확장.**
**방안 C는 당분간 안 함.**

## haircut 파라미터 기본값 (한국 개인투자자 기준)

```
slippage_bps: 3~10 bps (ETF 스프레드 포함)
fx_spread_krw: 10~30원/달러
rebalance_delay_days: 1~3일
dividend_reinvest_delay_days: 5~10일
tax_cash_drag_months: 0~5개월 (5월 납부 시)
```

## 파일 배치

```
src/aftertaxi/lanes/lane_d/
    __init__.py
    haircut.py        — ExecutionHaircut 모델
    (향후) friction.py — 방안 B post-processor
```

## 코어 영향 없음 체크

- [x] runner.py 변경 없음
- [x] settlement.py 변경 없음
- [x] ledger.py 변경 없음
- [x] contracts.py 변경 없음
- [x] facade.py 변경 없음

Lane D는 Lane A/B/C와 동일하게 코어 밖에서 facade를 호출하거나,
EngineResult를 읽어서 후처리하는 구조.
