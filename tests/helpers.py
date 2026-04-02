# -*- coding: utf-8 -*-
"""
tests/helpers.py — 테스트 공통 헬퍼
====================================
EngineResult 수동 생성을 한 곳에서 관리.
계약 변경 시 여기만 수정하면 됨.
"""
import numpy as np

from aftertaxi.core.contracts import (
    AccountSummary, EngineResult, PersonSummary, TaxSummary,
)


def make_engine_result(
    gross_pv_usd: float = 10000.0,
    invested_usd: float = 5000.0,
    fx: float = 1300.0,
    tax_assessed: float = 0.0,
    tax_unpaid: float = 0.0,
    mdd: float = -0.1,
    n_months: int = 24,
    accounts=None,
    health_insurance_krw: float = 0.0,
) -> EngineResult:
    """테스트용 EngineResult 빠른 생성.

    계약 변경 시 이 함수만 수정.
    """
    if accounts is None:
        accounts = [AccountSummary(
            account_id="test",
            account_type="TAXABLE",
            gross_pv_usd=gross_pv_usd,
            invested_usd=invested_usd,
            tax_assessed_krw=tax_assessed,
            tax_unpaid_krw=tax_unpaid,
            mdd=mdd,
            n_months=n_months,
            health_insurance_krw=health_insurance_krw,
        )]

    return EngineResult(
        gross_pv_usd=gross_pv_usd,
        invested_usd=invested_usd,
        gross_pv_krw=gross_pv_usd * fx,
        net_pv_krw=gross_pv_usd * fx - tax_unpaid,
        reporting_fx_rate=fx,
        mdd=mdd,
        n_months=n_months,
        n_accounts=len(accounts),
        tax=TaxSummary(
            total_assessed_krw=tax_assessed,
            total_unpaid_krw=tax_unpaid,
            total_paid_krw=tax_assessed - tax_unpaid,
        ),
        accounts=accounts,
        person=PersonSummary(
            health_insurance_krw=sum(a.health_insurance_krw for a in accounts),
        ),
        monthly_values=np.ones(n_months) * gross_pv_usd,
    )
