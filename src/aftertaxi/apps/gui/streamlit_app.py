# -*- coding: utf-8 -*-
"""
apps/gui/streamlit_app.py — aftertaxi 연구 대시보드
===================================================
초보자 모드: 템플릿 → 실행 → 요약 → Advisor → 다음 실험
고급 모드:   전체 파라미터 + 비교 + 세금/ISA/민감도

실행: streamlit run src/aftertaxi/apps/gui/streamlit_app.py
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


def _load_data(source, assets, s):
    from aftertaxi.apps.data_provider import load_market_data
    if source == "synthetic":
        return load_market_data(assets, source="synthetic",
                                n_months=s["n_months"], annual_growth=s["growth"],
                                annual_vol=s["vol"], fx_rate=s["fx_rate"], seed=s["seed"])
    elif source == "yfinance":
        return load_market_data(assets, source="yfinance",
                                start=s["start_date"], fx_rate=s["fx_rate"])
    elif source == "yfinance_fx":
        return load_market_data(assets, source="yfinance_fx", start=s["start_date"])
    raise ValueError(f"Unknown: {source}")


# ══════════════════════════════════════════════
# Advisor 카드
# ══════════════════════════════════════════════

def _render_advisor_card(result, attribution, config, baseline_result=None):
    """Advisor 진단 + 제안 + 원클릭 다음 실험 버튼."""
    from aftertaxi.advisor.builder import build_advisor_input
    from aftertaxi.advisor.rules import run_advisor

    inp = build_advisor_input(result, attribution, config,
                              baseline_result=baseline_result)
    report = run_advisor(inp)

    if report.n_critical > 0:
        st.error(f"⚠ {report.summary}")
    elif report.diagnoses:
        st.warning(f"△ {report.summary}")
    else:
        st.success(f"✓ {report.summary}")

    if report.diagnoses:
        for d in report.diagnoses:
            icon = "🔴" if d.severity == "critical" else "🟡"
            st.markdown(f"{icon} **{d.code}**: {d.message}")

    if report.suggestions:
        st.markdown("---")
        st.subheader("💡 개선 제안")
        for i, s in enumerate(report.suggestions):
            st.markdown(f"💡 **{s.kind}**: {s.message}")
            if s.patch and s.patch.get("_action") != "compare":
                if st.button(f"▶ {s.kind} 적용해서 재실행", key=f"adv_run_{i}",
                             use_container_width=True):
                    st.session_state["pending_patch"] = s.patch
                    st.session_state["pending_patch_label"] = s.kind
                    st.rerun()


# ══════════════════════════════════════════════
# 결과 렌더
# ══════════════════════════════════════════════

def _render_summary(result, attribution):
    """요약 지표 카드 (초보자/고급 공용)."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("세후 배수", f"{result.mult_after_tax:.2f}x")
    c2.metric("최대 낙폭", f"{result.mdd:.1%}")
    c3.metric("세금 drag", f"{attribution.tax_drag_pct:.1f}%")
    c4.metric("기간", f"{result.n_months // 12}년 {result.n_months % 12}월")

    c5, c6 = st.columns(2)
    c5.metric("투입", f"${result.invested_usd:,.0f}")
    c6.metric("세후 PV", f"₩{result.net_pv_krw:,.0f}")


def _render_enhanced_chart(result, total_monthly):
    mv = result.monthly_values
    n = len(mv)
    invested = np.arange(1, n + 1) * total_monthly
    chart_df = pd.DataFrame({"포트폴리오 (USD)": mv, "투입 원금 (USD)": invested},
                            index=range(1, n + 1))
    chart_df.index.name = "월"
    st.line_chart(chart_df, use_container_width=True)

    peak = np.maximum.accumulate(mv)
    dd = (mv / np.where(peak > 0, peak, 1.0) - 1.0) * 100
    st.area_chart(pd.DataFrame({"MDD (%)": dd}, index=range(1, n + 1)),
                  color="#ff6b6b", use_container_width=True)


def _render_tax_timeline(result):
    """연도별 세금 분해 — 실제 데이터."""
    history = result.annual_tax_history
    if not history:
        st.caption("세금 정산 기록이 없습니다 (1년 미만이거나 세금 0).")
        return

    df = pd.DataFrame(history)
    df = df.set_index("year")
    chart_df = df[["cgt_krw", "dividend_tax_krw", "health_insurance_krw"]].copy()
    chart_df.columns = ["양도세", "배당세", "건보료"]
    chart_df.index = [f"{y}년" for y in chart_df.index]

    st.bar_chart(chart_df, use_container_width=True)

    total = df["total_krw"].sum()
    peak_year = df["total_krw"].idxmax() if len(df) > 0 else "?"
    peak_val = df["total_krw"].max() if len(df) > 0 else 0
    st.caption(f"총 세금: ₩{total:,.0f} / 최고 부담 연도: {peak_year}년 (₩{peak_val:,.0f})")


def _render_comparison(r1, r2, l1, l2):
    from aftertaxi.workbench.compare import compare_strategies
    report = compare_strategies([r1, r2], [l1, l2])
    st.subheader(f"{l1} vs {l2}")
    table = report.rank_table()
    df = pd.DataFrame(table)
    df.columns = ["순위", "전략", "세전", "세후", "MDD", "drag%", "Sharpe"]
    st.dataframe(df, hide_index=True, use_container_width=True)

    mx = max(len(r1.monthly_values), len(r2.monthly_values))
    pv1 = np.pad(r1.monthly_values, (0, mx - len(r1.monthly_values)), constant_values=np.nan)
    pv2 = np.pad(r2.monthly_values, (0, mx - len(r2.monthly_values)), constant_values=np.nan)
    st.line_chart(pd.DataFrame({l1: pv1, l2: pv2}, index=range(1, mx + 1)),
                  use_container_width=True)
    st.info(f"세후 우승: **{report.winner}**")


# ══════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════

def main():
    st.set_page_config(page_title="aftertaxi", layout="wide")
    st.title("aftertaxi")

    all_meta = list_metadata()
    strategy_options = {m.label: m.key for m in all_meta}

    with st.sidebar:
        # 모드 선택
        mode = st.radio("모드", ["초보자", "고급"], horizontal=True)
        is_beginner = mode == "초보자"

        st.header("전략")

        if is_beginner:
            # 초보자: 템플릿만
            templates = {
                "SPY 100% (미국 대형주)": "spy_bnh",
                "QQQ+SSO 6:4 (나스닥 레버리지)": "q60s40",
            }
            # metadata에 있는 것만 필터
            valid_templates = {k: v for k, v in templates.items()
                               if v in strategy_options.values()}
            if not valid_templates:
                valid_templates = {list(strategy_options.keys())[0]:
                                   list(strategy_options.values())[0]}
            label1 = st.selectbox("전략 템플릿", list(valid_templates.keys()))
            key1 = valid_templates[label1]
            params1 = {}
            compare_mode = False
            key2, params2 = None, {}
        else:
            # 고급: 전체 기능
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

        if is_beginner:
            use_isa = st.checkbox("ISA 계좌 사용 (절세 효과)", value=True)
            monthly = st.number_input("월 납입 (USD)", min_value=100, value=1000, step=100)
            if use_isa:
                accounts = [
                    AccountDraft(type="ISA", monthly=float(monthly), priority=0),
                    AccountDraft(type="TAXABLE", monthly=0, priority=1),
                ]
                st.caption("💡 ISA에 전액 납입합니다 (연 한도 ₩2,000만). "
                           "한도 초과분 자동 overflow는 고급 모드에서 2계좌 설정으로 가능합니다.")
            else:
                accounts = [AccountDraft(type="TAXABLE", monthly=float(monthly), priority=0)]
        else:
            n_accts = st.radio("계좌 수", [1, 2], horizontal=True)
            accounts = []
            for i in range(n_accts):
                with st.expander(f"계좌 {i+1}", expanded=True):
                    at = st.selectbox("타입", ["TAXABLE", "ISA"], key=f"at{i}")
                    mo = st.number_input("월 납입 (USD)", min_value=0, value=1000,
                                         step=100, key=f"mo{i}")
                    accounts.append(AccountDraft(type=at, monthly=float(mo), priority=i))

        st.divider()
        st.header("데이터")

        if is_beginner:
            ds = "synthetic"
            state = {"n_months": 240, "fx_rate": 1300.0, "growth": 0.08,
                     "vol": 0.16, "seed": 42}
            state["n_months"] = st.slider("기간 (년)", 5, 30, 20) * 12
        else:
            ds_labels = {
                "synthetic": "합성 (빠른 아이디어 검토)",
                "yfinance": "실제 ETF (환율 고정)",
                "yfinance_fx": "실제 ETF + 실제 환율",
            }
            ds = st.selectbox("소스", list(ds_labels.keys()),
                              format_func=lambda x: ds_labels[x])
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

        if not is_beginner:
            st.divider()
            st.header("저장/불러오기")
            uploaded = st.file_uploader("JSON 불러오기", type="json")
            if uploaded:
                try:
                    loaded = json.load(uploaded)
                    st.success("설정 불러옴")
                    with st.expander("불러온 설정"):
                        st.json(loaded)
                except Exception as e:
                    st.error(f"JSON 파싱 실패: {e}")

    # Draft
    draft1 = BacktestDraft(
        strategy=StrategyDraft(type=key1, params=params1),
        accounts=accounts, n_months=state.get("n_months"),
    )
    errors = draft1.validate()
    if errors:
        for e in errors:
            st.error(f"❌ {e}")
        return

    warnings = draft1.warn()
    for w in warnings:
        st.warning(w)

    if not is_beginner:
        st.download_button("설정 저장 (JSON)", draft1.to_json(),
                           file_name="aftertaxi_config.json", mime="application/json")

    # ── 실행 ──
    run_triggered = st.button("백테스트 실행", type="primary", use_container_width=True)
    pending_patch = st.session_state.pop("pending_patch", None)
    pending_label = st.session_state.pop("pending_patch_label", "")

    if run_triggered or pending_patch is not None:
        from aftertaxi.strategies.compile import compile_backtest_with_trace

        payload = draft1.to_dict()

        # pending_patch가 있으면 적용
        if pending_patch is not None:
            from aftertaxi.strategies.compile import apply_suggestion_patch
            payload = apply_suggestion_patch(payload, pending_patch)
            st.info(f"💡 **{pending_label}** 제안이 적용되었습니다.")

        cfg1, trace1 = compile_backtest_with_trace(payload)
        all_assets = list(cfg1.strategy.weights.keys())

        cfg2 = None
        if compare_mode and key2:
            d2 = BacktestDraft(strategy=StrategyDraft(type=key2, params=params2),
                               accounts=accounts, n_months=state.get("n_months"))
            cfg2 = compile_backtest(d2.to_dict())
            all_assets = list(set(all_assets) | set(cfg2.strategy.weights.keys()))

        # CompileTrace 카드 — "이렇게 이해했습니다"
        with st.expander("📋 이렇게 이해했습니다", expanded=is_beginner):
            for d in trace1.decisions:
                st.markdown(f"**{d.field}**: {d.value}")

        with st.spinner("실행 중..."):
            try:
                market = _load_data(ds, all_assets, state)
            except Exception as e:
                st.error(f"❌ 데이터 로드 실패: {e}\n\n티커명을 확인하세요.")
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

            # baseline 자동 비교 (SPY B&H)
            r_baseline, a_baseline = None, None
            if key1 != "spy_bnh":
                try:
                    from aftertaxi.core.contracts import (
                        AccountConfig, AccountType, BacktestConfig as BTC,
                        StrategyConfig as SC,
                    )
                    baseline_cfg = BTC(
                        accounts=[AccountConfig("bl", AccountType.TAXABLE,
                                                sum(a.monthly_contribution for a in cfg1.accounts))],
                        strategy=SC("spy_bnh", {"SPY": 1.0}),
                    )
                    if "SPY" in pri.columns:
                        r_baseline = run_backtest(baseline_cfg, returns=ret, prices=pri, fx_rates=fx)
                        a_baseline = build_attribution(r_baseline)
                except Exception:
                    pass  # baseline 실패해도 메인 결과는 표시

        total_mo = sum(a.monthly or 0 for a in accounts)

        # 실행 기록 저장
        try:
            from aftertaxi.apps.memory import ResearchMemory
            from aftertaxi.advisor.builder import build_advisor_input
            from aftertaxi.advisor.rules import run_advisor

            memory = ResearchMemory()
            adv_inp = build_advisor_input(r1, a1, cfg1)
            adv_report = run_advisor(adv_inp)

            memory.record(
                config_json=draft1.to_json(),
                gross_pv_usd=r1.gross_pv_usd,
                net_pv_krw=r1.net_pv_krw,
                tax_assessed_krw=r1.tax.total_assessed_krw,
                mdd=r1.mdd,
                n_months=r1.n_months,
                name=f"{key1} {r1.n_months//12}yr",
                advisor_summary=adv_report.summary,
            )
        except Exception:
            pass  # 기록 실패해도 결과 표시는 진행

        # ══════════════════════════════════════
        # 결과 표시
        # ══════════════════════════════════════

        if r2:
            # ── 비교 모드 ──
            t_cmp, t_s1, t_s2, t_tax = st.tabs([
                "비교", key1.upper(), key2.upper(), "세금"])
            with t_cmp:
                _render_comparison(r1, r2, key1.upper(), key2.upper())
            with t_s1:
                _render_summary(r1, a1)
                _render_advisor_card(r1, a1, cfg1, baseline_result=r_baseline)
                _render_enhanced_chart(r1, total_mo)
            with t_s2:
                _render_summary(r2, a2)
                _render_advisor_card(r2, a2, cfg2, baseline_result=r_baseline)
                _render_enhanced_chart(r2, total_mo)
            with t_tax:
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**{key1.upper()}**")
                    _render_tax_timeline(r1)
                with c2:
                    st.write(f"**{key2.upper()}**")
                    _render_tax_timeline(r2)

        elif is_beginner:
            # ── 초보자 모드: 요약 → baseline → Advisor → 차트 ──
            _render_summary(r1, a1)

            # baseline 대비 판정
            if r_baseline:
                gap = r1.mult_after_tax - r_baseline.mult_after_tax
                if gap > 0.05:
                    st.success(f"📈 SPY 단순 적립 대비 **+{gap:.2f}x** 우위")
                elif gap < -0.05:
                    st.warning(f"📉 SPY 단순 적립 대비 **{gap:.2f}x** 열위. 복잡도 대비 이득 확인 필요.")
                else:
                    st.info(f"📊 SPY 단순 적립과 유사한 성과 (차이 {gap:+.2f}x)")

            # 해석 한 줄
            from aftertaxi.workbench.interpret import interpret_result
            st.markdown(interpret_result(r1, a1))

            st.divider()
            # Advisor 카드 (baseline 전달)
            _render_advisor_card(r1, a1, cfg1, baseline_result=r_baseline)

            st.divider()
            st.subheader("포트폴리오 성장")
            _render_enhanced_chart(r1, total_mo)

        else:
            # ── 고급 모드: 탭 전체 ──
            t_res, t_chart, t_tax, t_isa, t_sens, t_dbg = st.tabs(
                ["결과", "차트", "세금", "ISA 절세", "민감도", "디버그"])
            with t_res:
                _render_summary(r1, a1)
                st.divider()
                _render_advisor_card(r1, a1, cfg1, baseline_result=r_baseline)
                st.divider()
                from aftertaxi.workbench.interpret import interpret_result
                st.markdown(interpret_result(r1, a1))
                st.subheader("세금 분해")
                tc = st.columns(3)
                tc[0].metric("양도세", f"₩{sum(a.capital_gains_tax_krw for a in r1.accounts):,.0f}")
                tc[1].metric("배당세", f"₩{sum(a.dividend_tax_krw for a in r1.accounts):,.0f}")
                tc[2].metric("건보료", f"₩{r1.person.health_insurance_krw:,.0f}")
                if r1.n_accounts > 1:
                    st.subheader("계좌별")
                    st.table([{"계좌": a.account_id, "타입": a.account_type,
                               "PV": f"${a.gross_pv_usd:,.0f}",
                               "세금": f"₩{a.tax_assessed_krw:,.0f}"}
                              for a in r1.accounts])
            with t_chart:
                _render_enhanced_chart(r1, total_mo)
            with t_tax:
                _render_tax_timeline(r1)
            with t_isa:
                st.subheader("ISA 절세 시뮬레이터")
                st.caption("같은 전략, ISA 비중만 바꿔서 절세 효과를 비교합니다.")
                isa_ratio = st.slider("ISA 비중", 0.0, 0.8, 0.3, 0.1, key="isa_sim")
                if st.button("절세 시뮬레이션", key="isa_btn"):
                    with st.spinner("ISA 시뮬레이션..."):
                        from aftertaxi.workbench.tax_savings import simulate_tax_savings
                        ts = simulate_tax_savings(
                            strategy_payload={"type": key1},
                            total_monthly=total_mo, isa_ratio=isa_ratio,
                            returns=ret, prices=pri, fx_rates=fx)
                    sc1, sc2 = st.columns(2)
                    sc1.metric("TAXABLE 100%", f"₩{ts.taxable_only_tax:,.0f}")
                    sc2.metric(f"ISA {isa_ratio:.0%} 혼합", f"₩{ts.mixed_tax:,.0f}")
                    st.metric("절세액", f"₩{ts.tax_savings_krw:,.0f}",
                              delta=f"{ts.mult_improvement:+.3f}x")
            with t_sens:
                st.subheader("민감도 히트맵")
                if st.button("민감도 분석", key="sens_btn"):
                    with st.spinner("25개 시나리오..."):
                        from aftertaxi.workbench.sensitivity import run_sensitivity
                        grid = run_sensitivity(
                            strategy_payload={"type": key1},
                            n_months=state.get("n_months", 240),
                            fx_rate=state.get("fx_rate", 1300.0),
                            seed=state.get("seed", 42))
                    df = grid.to_dataframe()
                    st.dataframe(df.style.background_gradient(cmap="RdYlGn", axis=None),
                                 use_container_width=True)
                    st.text(grid.summary_text())
            with t_dbg:
                st.json(draft1.to_dict())

    # ══════════════════════════════════════
    # 최근 실행 기록 (항상 표시)
    # ══════════════════════════════════════
    try:
        from aftertaxi.apps.memory import ResearchMemory
        memory = ResearchMemory()
        recent = memory.list_runs(limit=10)
        if recent:
            st.divider()
            with st.expander(f"📜 최근 실행 ({len(recent)}건)", expanded=False):
                for i, rec in enumerate(recent):
                    mult = f"{rec.net_pv_krw / max(1, rec.n_months * 1000 * 1300):.2f}x" if rec.n_months > 0 else "-"
                    mdd = f"{rec.mdd:.0%}" if rec.mdd != 0 else "-"
                    col_info, col_btn = st.columns([5, 1])
                    with col_info:
                        st.markdown(
                            f"**{rec.name}** · {rec.timestamp[:10]} · "
                            f"{mult} · MDD {mdd} · "
                            f"{rec.advisor_summary[:25] if rec.advisor_summary else ''}"
                        )
                    with col_btn:
                        st.download_button(
                            "📋", rec.config_json,
                            file_name=f"{rec.name}.json",
                            mime="application/json",
                            key=f"replay_{i}",
                            help="설정 다운로드 → '불러오기'로 재실행",
                        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
