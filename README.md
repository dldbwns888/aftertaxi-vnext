# aftertaxi-vnext

세후 DCA 레버리지 ETF 백테스트 엔진 — FX-only 재설계.

## 현재 상태: PR 1 (Strangler Facade)

기존 [aftertaxi](https://github.com/dldbwns888/aftertaxi) engine_v2를 facade로 감싸서 새 typed contract으로 변환.
내부 엔진은 아직 기존 코드를 호출. PR 2에서 새 runner로 교체 예정.

## 설계 원칙

- **FX-only core**: legacy 단일통화 모드 없음
- **Typed contracts**: dict 결과 금지. 모든 필드 명시적
- **Explicit tax semantics**: `paid`/`assessed`/`unpaid` 의미 혼동 없음
- **Facade-first**: GUI/CLI/API 모두 `run_backtest()` 하나로 진입
- **Shadow compare**: 매 PR마다 기존 엔진과 숫자 일치 검증

## 세금 필드 불변식

```
gross_pv_krw == gross_pv_usd × reporting_fx_rate
net_pv_krw   == gross_pv_krw − tax_unpaid_krw
assessed     == paid + unpaid
```

## 테스트

```bash
# contract 테스트 (기존 엔진 불필요)
python -m pytest tests/test_contracts.py -v

# oracle shadow 테스트 (기존 aftertaxi 레포 필요)
PYTHONPATH=/path/to/aftertaxi:src python -m pytest tests/test_oracle_shadow.py -v
```

## PR 로드맵

| PR | 내용 | 검증 |
|---|---|---|
| **1 (현재)** | contracts + facade + oracle 3개 + tiered shadow | 기존 엔진 숫자 일치 |
| 2 | minimal ledger + runner (C/O only) | oracle 3개 통과 |
| 3 | FULL rebalance + multi-account | oracle 확장 |
| 4 | Lane A loader | 실제 데이터 |
| 5 | Lane B adapter | A/B overlap calibration |
| 6 | Lane C bootstrap | 분포 리포트 |
| 7+ | Lane D / GUI | 나중 |

## Lane 구조

| Lane | 질문 | 데이터 |
|---|---|---|
| A | 현실에서 깨지나? | 실제 ETF, 경로 1개 |
| B | 장기 이론이 서나? | 합성 152년, 경로 1개 |
| C | 운이 나쁘면? | Block Bootstrap, 경로 10,000개 |
| D | 내가 못하면? | 실행 노이즈, 시뮬 1,000개 |
