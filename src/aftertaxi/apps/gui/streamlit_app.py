# -*- coding: utf-8 -*-
"""
apps/gui/streamlit_app.py — Streamlit 프로토타입
================================================
metadata + draft + compile + engine + 결과 표시.

실행:
  PYTHONPATH=src:../aftertaxi streamlit run src/aftertaxi/apps/gui/streamlit_app.py
"""
import sys
import os

# path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import numpy as np
import pandas as pd
import streamlit as st

from aftertaxi.strategies.metadata import (
    get_metadata, list_metadata, categories, ParamSchema,
)
from aftertaxi.apps.gui.draft_models import (
    StrategyDraft, AccountDraft, BacktestDraft,
)
from aftertaxi.strategies.compile import compile_backtest
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.attribution import build_attribution


# ══════════════════════════════════════════════
# 파라미터 폼 렌더 (metadata 기반)
# ══════════════════════════════════════════════

def _render_param(param: ParamSchema, prefix: str = "") -> object:
    """ParamSchema → Streamlit 위젯. 값 반환."""
    key = f"{prefix}_{param.name}"

    if param.choices:
        return st.selectbox(param.label, param.choices, index=0, key=key)
    elif param.type == "int":
        return st.number_input(
            param.label, min_value=int(param.min_val or 1),
            max_value=int(param.max_val or 120),
            value=int(param.default or 1), step=1, key=key,
        )
    elif param.type == "float":
        return st.number_input(
            param.label, min_value=float(param.min_val or 0),
            max_value=float(param.max_val or 1),
            value=float(param.default or 0), step=0.01, key=key,
        )
    elif param.type == "str":
        return st.text_input(param.label, value=str(param.default or ""), key=key)
    elif param.type == "list":
        val = st.text_input(
            param.label, value=", ".join(param.default or []),
            help=param.description, key=key,
        )
        return [x.strip() for x in val.split(",") if x.strip()]
    elif param.type == "dict":
        val = st.text_input(
            param.label,
            value=", ".join(f"{k}:{v}" for k, v in (param.default or {}).items()),
            help=param.description, key=key,
        )
        result = {}
        for pair in val.split(","):
            pair = pair.strip()
            if ":" in pair:
                k, v = pair.split(":", 1)
                try:
                    result[k.strip()] = float(v.strip())
                except ValueError:
                    pass
        return result
    else:
        return st.text_input(param.label, value=str(param.default or ""), key=key)


# ══════════════════════════════════════════════
# 메인 앱
# ══════════════════════════════════════════════

def main():
    st.set_page_config(page_title="aftertaxi-vnext", layout="wide")
    st.title("aftertaxi-vnext")
    st.caption("세후 DCA 레버리지 ETF 백테스트")

    # ── 사이드바: 전략 설정 ──
    with st.sidebar:
        st.header("전략 설정")

        # 전략 선택
        all_meta = list_metadata()
        strategy_options = {m.label: m.key for m in all_meta}
        selected_label = st.selectbox(
            "전략 타입",
            list(strategy_options.keys()),
        )
        selected_key = strategy_options[selected_label]
        meta = get_metadata(selected_key)

        st.caption(meta.description)

        # 메타데이터 기반 파라미터 폼
        params = {}
        if meta.params:
            st.subheader("파라미터")
            for p in meta.params:
                params[p.name] = _render_param(p, prefix=selected_key)

        st.divider()

        # ── 계좌 설정 ──
        st.header("계좌 설정")
        n_accounts = st.radio("계좌 수", [1, 2], horizontal=True)

        accounts = []
        for i in range(n_accounts):
            with st.expander(f"계좌 {i+1}", expanded=True):
                acct_type = st.selectbox(
                    "타입", ["TAXABLE", "ISA"], key=f"acct_type_{i}",
                )
                monthly = st.number_input(
                    "월 납입 (USD)", min_value=0, value=1000,
                    step=100, key=f"monthly_{i}",
                )
                accounts.append(AccountDraft(
                    type=acct_type,
                    monthly=float(monthly),
                    priority=i,
                ))

        st.divider()

        # ── 데이터 소스 ──
        st.header("데이터")
        data_source = st.selectbox(
            "데이터 소스",
            ["synthetic", "yfinance", "yfinance_fx"],
            format_func=lambda x: {
                "synthetic": "합성 데이터 (데모)",
                "yfinance": "실제 ETF (yfinance, FX 고정)",
                "yfinance_fx": "실제 ETF + 실제 FX (yfinance)",
            }[x],
        )

        # 소스별 옵션
        if data_source == "synthetic":
            n_months = st.slider("기간 (월)", 12, 600, 240)
            fx_rate = st.number_input("환율 (KRW/USD)", value=1300.0, step=10.0)
            growth = st.slider("연 성장률", 0.0, 0.20, 0.08)
            vol = st.slider("연 변동성", 0.05, 0.40, 0.16)
            seed = st.number_input("시드", value=42, step=1)
        else:
            start_date = st.text_input("시작일", "2006-06-01")
            fx_rate = 1300.0
            if data_source == "yfinance":
                fx_rate = st.number_input("고정 환율", value=1300.0, step=10.0)
            n_months = None  # 실제 데이터는 가용 기간만큼
            seed = 42

        # Lane D
        lane_d = st.checkbox("Lane D 생존 시뮬레이션")
        lane_d_compare = st.checkbox("DCA vs Lump Sum 비교")
        lane_d_paths = 20
        lane_d_years = 20
        if lane_d or lane_d_compare:
            lane_d_paths = st.number_input("경로 수", value=20, step=10, min_value=5)
            lane_d_years = st.number_input("경로 길이 (년)", value=20, step=5, min_value=5)

    # ── Draft 생성 ──
    strategy_draft = StrategyDraft(type=selected_key, params=params)
    draft = BacktestDraft(
        strategy=strategy_draft,
        accounts=accounts,
        n_months=n_months,
        lane_d=lane_d,
        lane_d_compare=lane_d_compare,
    )

    # 검증 표시
    errors = draft.validate()
    if errors:
        for e in errors:
            st.error(e)
        return

    # ── 실행 ──
    if st.button("백테스트 실행", type="primary", use_container_width=True):
        with st.spinner("데이터 로드 + 엔진 실행 중..."):
            config = compile_backtest(draft.to_dict())
            assets = list(config.strategy.weights.keys())

            from aftertaxi.apps.data_provider import load_market_data

            try:
                if data_source == "synthetic":
                    market = load_market_data(
                        assets, source="synthetic",
                        n_months=n_months, annual_growth=growth,
                        annual_vol=vol, fx_rate=fx_rate, seed=int(seed),
                    )
                elif data_source == "yfinance":
                    market = load_market_data(
                        assets, source="yfinance",
                        start=start_date, fx_rate=fx_rate,
                    )
                elif data_source == "yfinance_fx":
                    market = load_market_data(
                        assets, source="yfinance_fx",
                        start=start_date,
                    )
                else:
                    st.error(f"Unknown source: {data_source}")
                    return
            except Exception as e:
                st.error(f"데이터 로드 실패: {e}")
                return

            returns = market.returns
            prices = market.prices
            fx = market.fx

            st.info(f"📊 {market.source} | {market.n_months}개월 | "
                    f"{market.start_date:%Y-%m} ~ {market.end_date:%Y-%m}")

            result = run_backtest(config, returns=returns, prices=prices, fx_rates=fx)
            attribution = build_attribution(result)

        # ── 결과 표시 ──
        st.divider()
        st.header("결과")

        # 핵심 지표 카드
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("세전 배수", f"{result.mult_pre_tax:.2f}x")
        col2.metric("세후 배수", f"{result.mult_after_tax:.2f}x")
        col3.metric("MDD", f"{result.mdd:.1%}")
        col4.metric("세금 drag", f"{result.tax_drag:.1%}")

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("투입", f"${result.invested_usd:,.0f}")
        col6.metric("세전 PV", f"${result.gross_pv_usd:,.0f}")
        col7.metric("세후 PV", f"₩{result.net_pv_krw:,.0f}")
        col8.metric("기간", f"{result.n_months}개월")

        # 월별 PV 차트
        st.subheader("월별 포트폴리오 가치")
        chart_df = pd.DataFrame({
            "PV (USD)": result.monthly_values,
        })
        st.line_chart(chart_df)

        # 세금 분해
        st.subheader("세금 분해")
        tax_cols = st.columns(3)
        tax_cols[0].metric("양도세", f"₩{sum(a.capital_gains_tax_krw for a in result.accounts):,.0f}")
        tax_cols[1].metric("배당세", f"₩{sum(a.dividend_tax_krw for a in result.accounts):,.0f}")
        tax_cols[2].metric("건보료", f"₩{result.person.health_insurance_krw:,.0f}")

        # 계좌별
        if result.n_accounts > 1:
            st.subheader("계좌별 결과")
            acct_data = []
            for a in result.accounts:
                acct_data.append({
                    "계좌": a.account_id,
                    "타입": a.account_type,
                    "PV (USD)": f"${a.gross_pv_usd:,.0f}",
                    "세금 (KRW)": f"₩{a.tax_assessed_krw:,.0f}",
                })
            st.table(acct_data)

        # Lane D
        if lane_d_compare:
            st.divider()
            st.subheader("Lane D: DCA vs Lump Sum")
            with st.spinner(f"{lane_d_paths}개 경로 시뮬레이션..."):
                from aftertaxi.lanes.lane_d.synthetic import SyntheticMarketConfig
                from aftertaxi.lanes.lane_d.compare import run_lane_d_comparison

                synth_config = SyntheticMarketConfig(
                    n_paths=int(lane_d_paths),
                    path_length_months=int(lane_d_years) * 12,
                    seed=int(seed),
                    base_fx_rate=fx_rate,
                )
                compare = run_lane_d_comparison(
                    returns, config, synth_config, n_jobs=2,
                )

            dc, lc = st.columns(2)
            dc.metric("DCA 생존률", f"{compare.dca_report.survival_rate:.0%}")
            lc.metric("Lump Sum 생존률", f"{compare.ls_survival_rate:.0%}")

            st.metric("생존률 Delta", f"{compare.survival_delta:+.1%}p")
            st.text(compare.summary_text())

        elif lane_d:
            st.divider()
            st.subheader("Lane D: Synthetic Survival")
            with st.spinner(f"{lane_d_paths}개 경로 시뮬레이션..."):
                from aftertaxi.lanes.lane_d.synthetic import SyntheticMarketConfig
                from aftertaxi.lanes.lane_d.run import run_lane_d

                synth_config = SyntheticMarketConfig(
                    n_paths=int(lane_d_paths),
                    path_length_months=int(lane_d_years) * 12,
                    seed=int(seed),
                    base_fx_rate=fx_rate,
                )
                ld_report = run_lane_d(
                    returns, config, synth_config,
                    actual_result=result, n_jobs=2,
                )

            lc1, lc2, lc3 = st.columns(3)
            lc1.metric("생존률", f"{ld_report.survival_rate:.0%}")
            lc2.metric("중앙 배수", f"{ld_report.median_mult_after_tax:.2f}x")
            lc3.metric("Percentile", f"{ld_report.actual_percentile:.0f}%")
            st.text(ld_report.summary_text())

        # JSON payload (디버그)
        with st.expander("JSON payload (디버그)", expanded=False):
            st.json(draft.to_dict())


if __name__ == "__main__":
    main()
