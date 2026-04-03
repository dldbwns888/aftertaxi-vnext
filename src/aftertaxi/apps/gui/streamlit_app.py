# -*- coding: utf-8 -*-
"""
apps/gui/streamlit_app.py — Streamlit 대시보드
===============================================
metadata + draft + compile + engine + 비교 + 시각화.

기능:
  1. 전략 비교 대시보드 (2~3 전략 나란히)
  2. 고도화 차트 (투입원금, MDD, 세전/세후)
  3. 설정 저장/불러오기 (JSON)
  4. 연간 세금 타임라인

실행:
  streamlit run src/aftertaxi/apps/gui/streamlit_app.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import numpy as np
import pandas as pd
import streamlit as st

from aftertaxi.strategies.metadata import get_metadata, list_metadata, ParamSchema
from aftertaxi.apps.gui.draft_models import StrategyDraft, AccountDraft, BacktestDraft
from aftertaxi.strategies.compile import compile_backtest
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.attribution import build_attribution


# ══════════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════════

def _render_param(param: ParamSchema, prefix: str = "") -> object:
    key = f"{prefix}_{param.name}"
    if param.choices:
        return st.selectbox(param.label, param.choices, index=0, key=key)
    elif param.type == "int":
        return st.number_input(param.label, min_value=int(param.min_val or 1),
                               max_value=int(param.max_val or 120),
                               value=int(param.default or 1), step=1, key=key)
    elif param.type == "float":
        return st.number_input(param.label, min_value=float(param.min_val or 0),
                               max_value=float(param.max_val or 1),
                               value=float(param.default or 0), step=0.01, key=key)
    elif param.type == "str":
        return st.text_input(param.label, value=str(param.default or ""), key=key)
    elif param.type == "list":
        val = st.text_input(param.label, value=", ".join(param.default or []),
                            help=param.description, key=key)
        return [x.strip() for x in val.split(",") if x.strip()]
    elif param.type == "dict":
        val = st.text_input(param.label,
                            value=", ".join(f"{k}:{v}" for k, v in (param.default or {}).items()),
                            help=param.description, key=key)
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
    return st.text_input(param.label, value=str(param.default or ""), key=key)


def _load_data(data_source, assets, s):
    from aftertaxi.apps.data_provider import load_market_data
    if data_source == "synthetic":
        return load_market_data(assets, source="synthetic",
                                n_months=s["n_months"], annual_growth=s["growth"],
                                annual_vol=s["vol"], fx_rate=s["fx_rate"], seed=s["seed"])
    elif data_source == "yfinance":
        return load_market_data(assets, source="yfinance",
                                start=s["start_date"], fx_rate=s["fx_rate"])
    elif data_source == "yfinance_fx":
        return load_market_data(assets, source="yfinance_fx", start=s["start_date"])
    raise ValueError(f"Unknown: {data_source}")


# ══════════════════════════════════════════════
# 결과 렌더
# ══════════════════════════════════════════════

def _render_metrics(result, attribution, label=""):
    pre = f"{label} " if label else ""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{pre}세전 배수", f"{result.mult_pre_tax:.2f}x")
    c2.metric(f"{pre}세후 배수", f"{result.mult_after_tax:.2f}x")
    c3.metric(f"{pre}MDD", f"{result.mdd:.1%}")
    c4.metric(f"{pre}세금 drag", f"{attribution.tax_drag_pct:.1f}%")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("투입", f"${result.invested_usd:,.0f}")
    c6.metric("세전 PV", f"${result.gross_pv_usd:,.0f}")
    c7.metric("세후 PV", f"₩{result.net_pv_krw:,.0f}")
    c8.metric("기간", f"{result.n_months}개월")


def _render_enhanced_chart(result, total_monthly):
    """PV + 투입원금 + MDD."""
    mv = result.monthly_values
    n = len(mv)
    invested = np.arange(1, n + 1) * total_monthly

    chart_df = pd.DataFrame({
        "포트폴리오 가치 (USD)": mv,
        "투입 원금 (USD)": invested,
    }, index=range(1, n + 1))
    chart_df.index.name = "월"
    st.line_chart(chart_df, use_container_width=True)

    peak = np.maximum.accumulate(mv)
    dd = (mv / np.where(peak > 0, peak, 1.0) - 1.0) * 100
    mdd_df = pd.DataFrame({"MDD (%)": dd}, index=range(1, n + 1))
    mdd_df.index.name = "월"
    st.area_chart(mdd_df, color="#ff6b6b", use_container_width=True)


def _render_tax_timeline(result):
    """연간 세금 타임라인."""
    n_years = max(1, result.n_months // 12)
    cgt = sum(a.capital_gains_tax_krw for a in result.accounts)
    div = sum(a.dividend_tax_krw for a in result.accounts)
    hi = result.person.health_insurance_krw

    df = pd.DataFrame({
        "양도세 (₩)": [cgt / n_years] * n_years,
        "배당세 (₩)": [div / n_years] * n_years,
        "건보료 (₩)": [hi / n_years] * n_years,
    }, index=[f"{i+1}년차" for i in range(n_years)])
    st.bar_chart(df, use_container_width=True)
    st.caption(f"총 세금: ₩{cgt + div + hi:,.0f}")


def _render_comparison(r1, r2, l1, l2):
    """전략 비교."""
    from aftertaxi.workbench.compare import compare_strategies
    report = compare_strategies([r1, r2], [l1, l2])

    st.subheader(f"{l1} vs {l2}")
    table = report.rank_table()
    df = pd.DataFrame(table)
    df.columns = ["순위", "전략", "세전", "세후", "MDD", "세금drag%", "Sharpe"]
    st.dataframe(df, hide_index=True, use_container_width=True)

    # PV 비교
    mx = max(len(r1.monthly_values), len(r2.monthly_values))
    pv1 = np.pad(r1.monthly_values, (0, mx - len(r1.monthly_values)), constant_values=np.nan)
    pv2 = np.pad(r2.monthly_values, (0, mx - len(r2.monthly_values)), constant_values=np.nan)
    cdf = pd.DataFrame({l1: pv1, l2: pv2}, index=range(1, mx + 1))
    cdf.index.name = "월"
    st.line_chart(cdf, use_container_width=True)

    if report.pairwise_tests:
        with st.expander("통계 검정"):
            for t in report.pairwise_tests:
                sig = "✓" if t.significant else "✗"
                st.text(f"{t.test_name}: p={t.p_value:.4f} {sig} | {t.detail}")

    st.info(f"세후 우승: **{report.winner}**")

    # 해석 (#10)
    from aftertaxi.workbench.interpret import interpret_comparison
    st.markdown("---")
    st.markdown(interpret_comparison(r1, r2, l1, l2))

    # 해석 (#10)
    from aftertaxi.workbench.interpret import interpret_comparison
    st.markdown("---")
    st.markdown(interpret_comparison(r1, r2, l1, l2))


# ══════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════

def main():
    st.set_page_config(page_title="aftertaxi-vnext", layout="wide")
    st.title("aftertaxi-vnext")
    st.caption("세후 DCA 레버리지 ETF 백테스트 플랫폼")

    all_meta = list_metadata()
    strategy_options = {m.label: m.key for m in all_meta}

    with st.sidebar:
        st.header("전략")
        compare_mode = st.toggle("비교 모드")

        label1 = st.selectbox("전략 1", list(strategy_options.keys()), key="s1")
        key1 = strategy_options[label1]
        meta1 = get_metadata(key1)
        st.caption(meta1.description)
        params1 = {p.name: _render_param(p, f"a_{key1}") for p in meta1.params}

        key2, params2 = None, {}
        if compare_mode:
            st.divider()
            label2 = st.selectbox("전략 2", list(strategy_options.keys()), index=1, key="s2")
            key2 = strategy_options[label2]
            meta2 = get_metadata(key2)
            st.caption(meta2.description)
            params2 = {p.name: _render_param(p, f"b_{key2}") for p in meta2.params}

        st.divider()
        st.header("계좌")
        n_accts = st.radio("계좌 수", [1, 2], horizontal=True)
        accounts = []
        for i in range(n_accts):
            with st.expander(f"계좌 {i+1}", expanded=True):
                at = st.selectbox("타입", ["TAXABLE", "ISA"], key=f"at{i}")
                mo = st.number_input("월 납입 (USD)", min_value=0, value=1000, step=100, key=f"mo{i}")
                accounts.append(AccountDraft(type=at, monthly=float(mo), priority=i))

        st.divider()
        st.header("데이터")
        ds = st.selectbox("소스", ["synthetic", "yfinance", "yfinance_fx"],
                          format_func=lambda x: {"synthetic": "합성", "yfinance": "실제 ETF",
                                                  "yfinance_fx": "실제 ETF+FX"}[x])
        state = {"fx_rate": 1300.0, "seed": 42, "n_months": 240,
                 "growth": 0.08, "vol": 0.16, "start_date": "2006-06-01"}
        if ds == "synthetic":
            state["n_months"] = st.slider("기간 (월)", 12, 600, 240)
            state["fx_rate"] = st.number_input("환율", value=1300.0, step=10.0)
            state["growth"] = st.slider("연 성장률", 0.0, 0.20, 0.08)
            state["vol"] = st.slider("연 변동성", 0.05, 0.40, 0.16)
            state["seed"] = st.number_input("시드", value=42, step=1)
        else:
            state["start_date"] = st.text_input("시작일", "2006-06-01")
            if ds == "yfinance":
                state["fx_rate"] = st.number_input("고정 환율", value=1300.0, step=10.0)

        st.divider()
        st.header("저장/불러오기")
        uploaded = st.file_uploader("JSON 불러오기", type="json")

    # Draft
    draft1 = BacktestDraft(
        strategy=StrategyDraft(type=key1, params=params1),
        accounts=accounts, n_months=state.get("n_months"),
    )
    errors = draft1.validate()
    if errors:
        for e in errors:
            st.error(e)
        return

    # 경고 (#9)
    warnings = draft1.warn()
    for w in warnings:
        st.warning(w)

    # 불러오기
    if uploaded:
        try:
            loaded = json.load(uploaded)
            st.success("설정 불러옴")
            with st.expander("불러온 설정"):
                st.json(loaded)
        except Exception as e:
            st.error(f"JSON 실패: {e}")

    # 저장
    st.download_button("설정 저장 (JSON)", draft1.to_json(),
                       file_name="aftertaxi_config.json", mime="application/json")

    # ── 실행 ──
    if st.button("백테스트 실행", type="primary", use_container_width=True):
        cfg1 = compile_backtest(draft1.to_dict())
        all_assets = list(cfg1.strategy.weights.keys())

        cfg2 = None
        if compare_mode and key2:
            d2 = BacktestDraft(strategy=StrategyDraft(type=key2, params=params2),
                               accounts=accounts, n_months=state.get("n_months"))
            cfg2 = compile_backtest(d2.to_dict())
            all_assets = list(set(all_assets) | set(cfg2.strategy.weights.keys()))

        with st.spinner("실행 중..."):
            try:
                market = _load_data(ds, all_assets, state)
            except Exception as e:
                st.error(f"데이터 실패: {e}")
                return

            ret, pri, fx = market.returns, market.prices, market.fx
            st.info(f"📊 {market.source} | {market.n_months}개월 | "
                    f"{market.start_date:%Y-%m} ~ {market.end_date:%Y-%m}")

            r1 = run_backtest(cfg1, returns=ret, prices=pri, fx_rates=fx)
            a1 = build_attribution(r1)
            r2, a2 = None, None
            if cfg2:
                r2 = run_backtest(cfg2, returns=ret, prices=pri, fx_rates=fx)
                a2 = build_attribution(r2)

        total_mo = sum(a.monthly or 0 for a in accounts)

        if r2:
            t_cmp, t_s1, t_s2, t_tax = st.tabs([
                "비교", key1.upper(), key2.upper(), "세금 타임라인"])
            with t_cmp:
                _render_comparison(r1, r2, key1.upper(), key2.upper())
            with t_s1:
                _render_metrics(r1, a1, key1.upper())
                _render_enhanced_chart(r1, total_mo)
            with t_s2:
                _render_metrics(r2, a2, key2.upper())
                _render_enhanced_chart(r2, total_mo)
            with t_tax:
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**{key1.upper()}**")
                    _render_tax_timeline(r1)
                with c2:
                    st.write(f"**{key2.upper()}**")
                    _render_tax_timeline(r2)
        else:
            t_res, t_chart, t_tax, t_isa, t_sens, t_dbg = st.tabs(
                ["결과", "차트", "세금", "ISA 절세", "민감도", "디버그"])
            with t_res:
                _render_metrics(r1, a1)
                # 해석 텍스트 (#10)
                from aftertaxi.workbench.interpret import interpret_result
                st.markdown("---")
                st.markdown(interpret_result(r1, a1))

                st.subheader("세금 분해")
                tc = st.columns(3)
                tc[0].metric("양도세", f"₩{sum(a.capital_gains_tax_krw for a in r1.accounts):,.0f}")
                tc[1].metric("배당세", f"₩{sum(a.dividend_tax_krw for a in r1.accounts):,.0f}")
                tc[2].metric("건보료", f"₩{r1.person.health_insurance_krw:,.0f}")
                if r1.n_accounts > 1:
                    st.subheader("계좌별")
                    st.table([{"계좌": a.account_id, "타입": a.account_type,
                               "PV": f"${a.gross_pv_usd:,.0f}", "세금": f"₩{a.tax_assessed_krw:,.0f}"}
                              for a in r1.accounts])
            with t_chart:
                st.subheader("포트폴리오 가치 + 투입 원금 + MDD")
                _render_enhanced_chart(r1, total_mo)
            with t_tax:
                st.subheader("연간 세금 타임라인")
                _render_tax_timeline(r1)
            with t_isa:
                # ISA 절세 시뮬레이터 (#2)
                st.subheader("ISA 절세 시뮬레이터")
                st.caption("같은 전략, ISA 비중만 바꿔서 절세 효과를 비교합니다.")
                isa_ratio = st.slider("ISA 비중", 0.0, 0.8, 0.3, 0.1, key="isa_sim")
                if st.button("절세 시뮬레이션", key="isa_btn"):
                    with st.spinner("ISA 시뮬레이션..."):
                        from aftertaxi.workbench.tax_savings import simulate_tax_savings
                        ts = simulate_tax_savings(
                            strategy_payload={"type": key1},
                            total_monthly=total_mo,
                            isa_ratio=isa_ratio,
                            returns=ret, prices=pri, fx_rates=fx,
                        )
                    sc1, sc2 = st.columns(2)
                    sc1.metric("TAXABLE 100% 세금", f"₩{ts.taxable_only_tax:,.0f}")
                    sc2.metric(f"ISA {isa_ratio:.0%} 혼합 세금", f"₩{ts.mixed_tax:,.0f}")
                    st.metric("절세액", f"₩{ts.tax_savings_krw:,.0f}",
                              delta=f"{ts.mult_improvement:+.3f}x")
                    st.text(ts.summary_text())
            with t_sens:
                st.subheader("민감도 히트맵 (성장률 × 변동성)")
                st.caption("합성 데이터에서 시장 환경별 세후 배수 분포")
                if st.button("민감도 분석 실행", key="sens_btn"):
                    with st.spinner("25개 시나리오 실행 중..."):
                        from aftertaxi.workbench.sensitivity import run_sensitivity
                        grid = run_sensitivity(
                            strategy_payload={"type": key1},
                            n_months=state.get("n_months", 240),
                            fx_rate=state.get("fx_rate", 1300.0),
                            seed=state.get("seed", 42),
                        )
                    df = grid.to_dataframe()
                    st.dataframe(df.style.background_gradient(cmap="RdYlGn", axis=None),
                                 use_container_width=True)
                    st.text(grid.summary_text())
            with t_dbg:
                st.json(draft1.to_dict())


if __name__ == "__main__":
    main()
