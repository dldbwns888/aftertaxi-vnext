# -*- coding: utf-8 -*-
"""
core/constants.py — 엔진 전역 상수
====================================
매직 넘버를 이름과 의미가 있는 상수로 정의.

이 상수들은 부동소수점 비교에서 "0인지 아닌지"를 판단하는 epsilon.
값을 변경하면 세금 계산, 거래 실행, 배당 처리 전체에 영향.

사용 규칙:
  - 수량(qty) 비교: QTY_EPSILON
  - USD 금액 비교: AMOUNT_EPSILON_USD
  - KRW 금액 비교: AMOUNT_EPSILON_KRW
  - 포트폴리오 대비 최소 거래: DUST_PCT
"""

# ── 수량 epsilon ──
# 1주의 1조분의 1. fractional share 시뮬레이션에서 0으로 간주하는 최소 수량.
# Position.avg_cost, buy, sell, liquidate, mark_to_market에서 사용.
QTY_EPSILON = 1e-12

# ── 금액 epsilon (USD) ──
# USD 0.00000001. 현금 부족 판단, 배당 존재 여부, 건보료/세금 납부 임계값.
# 매우 작은 양도 "존재"로 볼 수 있으므로 1e-8로 설정.
AMOUNT_EPSILON_USD = 1e-8

# ── 금액 epsilon (KRW) ──
# KRW 0.000001. 이월결손금 유효성, 세금 반올림 판단.
# KRW는 원 단위 정수이므로 1e-6이면 실질적으로 0.
AMOUNT_EPSILON_KRW = 1e-6

# ── 최소 거래 비율 ──
# 포트폴리오 가치 대비 이 비율 미만인 거래는 무시 (0.1%).
# 리밸런싱 시 먼지 거래 방지.
DUST_PCT = 0.001
