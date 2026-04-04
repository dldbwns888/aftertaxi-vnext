# -*- coding: utf-8 -*-
"""
apps/gui/streamlit_app.py — aftertaxi 연구 대시보드
===================================================
초보자 모드: 전략 빌더 wizard → 실행 → 요약 → Advisor → 다음 실험
고급 모드:   전체 파라미터 + 비교 + 세금/ISA/민감도

실행: streamlit run src/aftertaxi/apps/gui/streamlit_app.py
(사전에 pip install -e . 필요)
"""
import json

import numpy as np
import pandas as pd
import streamlit as st

from aftertaxi.strategies.metadata import get_metadata, list_metadata, ParamSchema
from aftertaxi.apps.gui.draft_models import StrategyDraft, AccountDraft, BacktestDraft


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

def _render_advisor_card(report):
    """Advisor 진단 + 제안 + 원클릭 다음 실험 버튼.

    Parameters
    ----------
    report : AdvisorReport
        service.run_strategy()가 반환한 RunOutput.advisor_report를 그대로 전달.
        GUI는 렌더링만 한다. advisor를 직접 실행하지 않는다.
    """

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


def _render_asset_contribution(weights, prices, invested_usd):
    """자산별 기여 분해 차트."""
    from aftertaxi.analysis.analytics import build_asset_contribution
    contribs = build_asset_contribution(weights, prices, invested_usd)
    if not contribs:
        return

    st.subheader("자산별 기여")
    for c in contribs:
        pct_str = f"{c.contribution_pct:+.0f}%"
        ret_str = f"{c.cumulative_return:+.0%}"
        dollar_str = f"${c.dollar_contribution:+,.0f}" if c.dollar_contribution != 0 else ""
        st.markdown(f"**{c.asset}** ({c.target_weight:.0%}) — 수익률 {ret_str}, 기여 {pct_str} {dollar_str}")


def _render_underwater(monthly_values):
    """Underwater (drawdown) 차트."""
    from aftertaxi.analysis.analytics import build_underwater
    uw = build_underwater(monthly_values)
    if len(uw.drawdown) == 0:
        return

    dd_df = pd.DataFrame({"낙폭 (%)": uw.drawdown * 100}, index=range(1, len(uw.drawdown) + 1))
    dd_df.index.name = "월"
    st.area_chart(dd_df, color="#ff6b6b", use_container_width=True)
    st.caption(f"최대 낙폭: {uw.max_drawdown:.1%} / 최장 회복: {uw.max_recovery_months}개월")


def _render_comparison(compare_output):
    """비교 결과 렌더링. service.compare_strategies() 반환값을 그대로 사용.

    GUI는 렌더링만. 비교 계산은 service가 소유.
    """
    report = compare_output.comparison_report
    outputs = compare_output.outputs
    labels = [row["name"] for row in compare_output.rank_table]

    l1, l2 = labels[0] if len(labels) > 0 else "A", labels[1] if len(labels) > 1 else "B"
    # rank_table에서 이미 정렬돼있을 수 있으므로 원본 순서 복원
    l1 = outputs[0].config.strategy.name if hasattr(outputs[0].config.strategy, "name") else "전략1"
    l2 = outputs[1].config.strategy.name if hasattr(outputs[1].config.strategy, "name") else "전략2"

    st.subheader(f"{l1} vs {l2}")
    table = report.rank_table()
    df = pd.DataFrame(table)
    df.columns = ["순위", "전략", "세전", "세후", "MDD", "drag%", "Sharpe"]
    st.dataframe(df, hide_index=True, use_container_width=True)

    r1 = outputs[0].result
    r2 = outputs[1].result
    mx = max(len(r1.monthly_values), len(r2.monthly_values))
    pv1 = np.pad(r1.monthly_values, (0, mx - len(r1.monthly_values)), constant_values=np.nan)
    pv2 = np.pad(r2.monthly_values, (0, mx - len(r2.monthly_values)), constant_values=np.nan)
    st.line_chart(pd.DataFrame({l1: pv1, l2: pv2}, index=range(1, mx + 1)),
                  use_container_width=True)
    st.info(f"세후 우승: **{compare_output.winner}**")


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
            # ── 전략 빌더 Wizard ──

            # Step 1: 투자 스타일
            style = st.radio("투자 스타일",
                             ["🛡 안전형", "⚖ 균형형", "🚀 공격형", "🔧 직접 구성"],
                             horizontal=True)

            # Step 2: 전략 매칭
            if style == "🛡 안전형":
                key1 = "spy_bnh"
                st.caption("SPY 100% — 미국 대형주 장기 적립. 가장 단순하고 검증된 전략.")
            elif style == "⚖ 균형형":
                key1 = "6040"
                st.caption("SPY 60% + TLT 40% — 주식+채권 전통 배분. 변동성 완화.")
            elif style == "🚀 공격형":
                key1 = "q60s40"
                st.caption("QQQ 60% + SSO 40% — 나스닥+레버리지. 높은 성장, 높은 변동성.")
            else:
                # 직접 구성: 2자산
                st.caption("자산 2개를 골라 비중을 정합니다.")
                asset_options = ["SPY", "QQQ", "SSO", "TLT", "VXUS", "GLDM"]
                c1, c2 = st.columns(2)
                a1 = c1.selectbox("자산 1", asset_options, index=0, key="ba1")
                a2 = c2.selectbox("자산 2", asset_options, index=1, key="ba2")
                w1 = st.slider(f"{a1} 비중", 10, 90, 60, 10, key="bw1")
                key1 = "custom"
                params1 = {"weights": {a1: w1 / 100, a2: (100 - w1) / 100}}

            if style != "🔧 직접 구성":
                params1 = {}

            compare_mode = False
            key2, params2 = None, {}

            st.divider()

            # Step 3: 계좌
            acct_rule = st.radio("계좌 규칙",
                                 ["ISA 우선 (절세 최적)", "일반계좌만", "ISA/일반 분배"],
                                 horizontal=False)
            monthly = st.number_input("월 납입 (USD)", min_value=100, value=1000, step=100)

            if acct_rule == "ISA 우선 (절세 최적)":
                accounts = [
                    AccountDraft(type="ISA", monthly=float(monthly), priority=0),
                    AccountDraft(type="TAXABLE", monthly=0, priority=1),
                ]
                st.caption("💡 ISA에 전액 납입 (연 한도 ₩2,000만). "
                           "초과분은 고급 모드에서 분배 설정 가능.")
            elif acct_rule == "일반계좌만":
                accounts = [AccountDraft(type="TAXABLE", monthly=float(monthly), priority=0)]
            else:
                isa_pct = st.slider("ISA 비중", 10, 90, 50, 10, key="isa_split")
                isa_mo = float(monthly) * isa_pct / 100
                tax_mo = float(monthly) - isa_mo
                accounts = [
                    AccountDraft(type="ISA", monthly=isa_mo, priority=0),
                    AccountDraft(type="TAXABLE", monthly=tax_mo, priority=1),
                ]
                st.caption(f"ISA ${isa_mo:,.0f}/월 + 일반 ${tax_mo:,.0f}/월")

            st.divider()

            # Step 4: 리밸런싱
            rebal = st.radio("리밸런싱",
                             ["적립만 (매도 없음)", "괴리 클 때만 (BAND 5%)", "매월 전체"],
                             horizontal=False)
            if rebal == "괴리 클 때만 (BAND 5%)":
                for a in accounts:
                    a.rebalance_mode = "BAND"
            elif rebal == "매월 전체":
                for a in accounts:
                    a.rebalance_mode = "FULL"

            st.divider()

            # Step 5: 기간
            years = st.slider("투자 기간 (년)", 5, 30, 20)
            state = {"n_months": years * 12, "fx_rate": 1300.0, "growth": 0.08,
                     "vol": 0.16, "seed": 42}
            ds = "synthetic"
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

        if not is_beginner:
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

        if not is_beginner:
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
        from aftertaxi.apps.service import run_strategy

        payload = draft1.to_dict()

        # pending_patch 적용
        if pending_patch is not None:
            from aftertaxi.strategies.compile import apply_suggestion_patch
            payload = apply_suggestion_patch(payload, pending_patch)
            st.info(f"💡 **{pending_label}** 제안이 적용되었습니다.")

        # 데이터 로드
        all_assets = list(payload.get("strategy", {}).get("weights", {"SPY": 1}).keys())

        # compare용 추가 자산
        compare_output = None
        payload2 = None
        if compare_mode and key2:
            d2 = BacktestDraft(strategy=StrategyDraft(type=key2, params=params2),
                               accounts=accounts, n_months=state.get("n_months"))
            payload2 = d2.to_dict()
            # 자산셋 합치기 (데이터 로드 전에 필요)
            assets2 = list(payload2.get("strategy", {}).get("weights", {}).keys())
            all_assets = list(set(all_assets) | set(assets2))

        with st.spinner("실행 중..."):
            try:
                market = _load_data(ds, all_assets, state)
            except Exception as e:
                st.error(f"❌ 데이터 로드 실패: {e}\n\n티커명을 확인하세요.")
                return

            ret, pri, fx = market.returns, market.prices, market.fx
            st.info(f"📊 {market.source} | {market.n_months}개월 | "
                    f"{market.start_date:%Y-%m} ~ {market.end_date:%Y-%m}")
            if ds == "synthetic":
                st.warning("⚠ **합성 데이터**로 실행. 실제 시장과 다를 수 있습니다. "
                           "실전 판단 전 실제 ETF 데이터(yfinance)로 재검증하세요.")

            # 메인 실행 (서비스 레이어)
            if compare_mode and payload2:
                # 비교 모드: service.compare_strategies 경유
                from aftertaxi.apps.service import compare_strategies as svc_compare
                compare_output = svc_compare(
                    [payload, payload2],
                    [key1.upper(), key2.upper()],
                    ret, pri, fx, data_source=ds,
                )
                out = compare_output.outputs[0]
            else:
                out = run_strategy(payload, ret, pri, fx, data_source=ds)

        # CompileTrace 카드
        with st.expander("📋 이렇게 이해했습니다", expanded=is_beginner):
            for d in out.trace.decisions:
                st.markdown(f"**{d.field}**: {d.value}")

        # 결과 꺼내기
        r1, a1, cfg1 = out.result, out.attribution, out.config
        r_baseline = out.baseline_result
        total_mo = sum(a.monthly or 0 for a in accounts)

        # ══════════════════════════════════════
        # 결과 표시
        # ══════════════════════════════════════

        if compare_output:
            # ── 비교 모드 ── (service.compare_strategies 경유)
            out1_cmp = compare_output.outputs[0]
            out2_cmp = compare_output.outputs[1]
            r2 = out2_cmp.result
            a2 = out2_cmp.attribution

            t_cmp, t_s1, t_s2, t_tax = st.tabs([
                "비교", key1.upper(), key2.upper(), "세금"])
            with t_cmp:
                _render_comparison(compare_output)
            with t_s1:
                _render_summary(r1, a1)
                _render_advisor_card(out1_cmp.advisor_report)
                _render_enhanced_chart(r1, total_mo)
            with t_s2:
                _render_summary(r2, a2)
                _render_advisor_card(out2_cmp.advisor_report)
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
            if out.interpretation_text:
                st.markdown(out.interpretation_text)

            st.divider()
            # Advisor 카드 (baseline 전달)
            _render_advisor_card(out.advisor_report)

            st.divider()
            st.subheader("포트폴리오 성장")
            _render_enhanced_chart(r1, total_mo)
            _render_underwater(r1.monthly_values)
            _render_asset_contribution(cfg1.strategy.weights, pri, r1.invested_usd)

        else:
            # ── 고급 모드: 탭 전체 ──
            t_res, t_chart, t_tax, t_isa, t_sens, t_dbg = st.tabs(
                ["결과", "차트", "세금", "ISA 절세", "민감도", "디버그"])
            with t_res:
                _render_summary(r1, a1)
                st.divider()
                _render_advisor_card(out.advisor_report)
                st.divider()
                if out.interpretation_text:
                    st.markdown(out.interpretation_text)
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
                _render_underwater(r1.monthly_values)
                _render_asset_contribution(cfg1.strategy.weights, pri, r1.invested_usd)
            with t_tax:
                _render_tax_timeline(r1)
            with t_isa:
                st.subheader("ISA 절세 시뮬레이터")
                st.caption("같은 전략, ISA 비중만 바꿔서 절세 효과를 비교합니다.")
                isa_ratio = st.slider("ISA 비중", 0.0, 0.8, 0.3, 0.1, key="isa_sim")
                if st.button("절세 시뮬레이션", key="isa_btn"):
                    with st.spinner("ISA 시뮬레이션..."):
                        from aftertaxi.apps.service import run_tax_savings
                        ts = run_tax_savings(
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
                        from aftertaxi.apps.service import run_sensitivity as svc_sensitivity
                        grid = svc_sensitivity(
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
