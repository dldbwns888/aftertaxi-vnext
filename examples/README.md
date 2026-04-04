# aftertaxi examples

실행: `aftertaxi examples/01_spy_basic.json`

| 파일 | 설명 |
|---|---|
| 01_spy_basic.json | SPY 100% B&H, TAXABLE, 20년 |
| 02_q60s40_isa.json | QQQ+SSO 6:4, ISA 우선 + TAXABLE |
| 03_progressive_tax.json | 종합과세 누진 적용 |
| 04_band_rebalance.json | BAND 5% 리밸런싱 |
| 05_full_setup.json | ISA+TAXABLE+누진+BAND 전체 조합 |

## 빠른 시작

```bash
# 기본 백테스트
aftertaxi examples/01_spy_basic.json

# 민감도 분석 포함
aftertaxi examples/02_q60s40_isa.json --sensitivity

# Lane D 생존성
aftertaxi examples/04_band_rebalance.json --lane-d --lane-d-paths 30 --lane-d-years 50
```
