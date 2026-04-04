# -*- coding: utf-8 -*-
"""
apps/cli.py — CLI 백테스트 실행기
=================================
JSON 설정 파일 하나로 터미널에서 백테스트를 실행.

사용법:
  python -m aftertaxi.apps.cli config.json
  python -m aftertaxi.apps.cli config.json --months 120 --fx 1300
  echo '{"strategy":{"type":"q60s40"}}' | python -m aftertaxi.apps.cli -

입력:
  JSON payload (compile.py 형식)
  + 선택: --months, --fx, --growth (합성 데이터 파라미터)

출력:
  전략 요약, 계좌별 결과, 세금 분석, attribution
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _generate_synthetic_data(
    assets: list,
    n_months: int = 240,
    annual_growth: float = 0.08,
    annual_vol: float = 0.16,
    fx_rate: float = 1300.0,
    seed: int = 42,
):
    """테스트/데모용 합성 시장 데이터."""
    rng = np.random.default_rng(seed)
    monthly_mu = annual_growth / 12
    monthly_sigma = annual_vol / np.sqrt(12)

    idx = pd.date_range("2005-01-31", periods=n_months, freq="ME")
    data = {}
    for asset in assets:
        # 자산별 약간 다른 시드
        r = rng.normal(monthly_mu, monthly_sigma, n_months)
        data[asset] = r

    returns = pd.DataFrame(data, index=idx)
    prices = 100.0 * (1 + returns).cumprod()
    fx = pd.Series(fx_rate, index=idx)
    return returns, prices, fx


def _print_result(result, attribution=None):
    """EngineResult → 터미널 출력."""
    print(f"\n{'═' * 60}")
    print(f"  세후 DCA 백테스트 결과")
    print(f"{'═' * 60}")
    print(f"  기간: {result.n_months}개월 ({result.n_months / 12:.1f}년)")
    print(f"  계좌: {result.n_accounts}개")
    print()
    print(f"  투입:     ${result.invested_usd:>12,.0f}")
    print(f"  세전 PV:  ${result.gross_pv_usd:>12,.0f}  ({result.mult_pre_tax:.2f}x)")
    print(f"  세후 PV:  ₩{result.net_pv_krw:>12,.0f}  ({result.mult_after_tax:.2f}x)")
    print(f"  MDD:      {result.mdd:>12.1%}")
    print()
    print(f"  세금 총 assessed: ₩{result.tax.total_assessed_krw:>10,.0f}")
    print(f"  세금 paid:        ₩{result.tax.total_paid_krw:>10,.0f}")
    print(f"  세금 unpaid:      ₩{result.tax.total_unpaid_krw:>10,.0f}")

    if result.person.health_insurance_krw > 0:
        print(f"  건보료 (person):  ₩{result.person.health_insurance_krw:>10,.0f}")

    if len(result.accounts) > 1:
        print(f"\n  {'─' * 56}")
        print(f"  계좌별:")
        for a in result.accounts:
            print(f"    [{a.account_id}] {a.account_type}")
            print(f"      PV ${a.gross_pv_usd:,.0f}, 세금 ₩{a.tax_assessed_krw:,.0f}")

    if attribution:
        print(f"\n  {'─' * 56}")
        print(f"  Attribution:")
        print(f"    거래비용:   ${attribution.total_transaction_cost_usd:,.2f}")
        print(f"    세금 drag:  {attribution.tax_drag_pct:.2f}%")
        if attribution.total_dividend_gross_usd > 0:
            print(f"    배당 총액:  ${attribution.total_dividend_gross_usd:,.2f}")
            print(f"    원천징수:   ${attribution.total_dividend_withholding_usd:,.2f}")

    print(f"{'═' * 60}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="aftertaxi-vnext CLI 백테스트 실행기",
    )
    parser.add_argument(
        "config", type=str,
        help="JSON 설정 파일 경로 또는 '-' (stdin)",
    )
    parser.add_argument("--months", type=int, default=None, help="백테스트 기간 (월)")
    parser.add_argument("--fx", type=float, default=1300.0, help="고정 환율")
    parser.add_argument("--growth", type=float, default=0.08, help="합성 데이터 연간 성장률")
    parser.add_argument("--vol", type=float, default=0.16, help="합성 데이터 연간 변동성")
    parser.add_argument("--json", action="store_true", help="JSON 출력 (workbench 형식)")
    parser.add_argument("--seed", type=int, default=42, help="합성 데이터 시드")

    # Lane D
    parser.add_argument("--lane-d", action="store_true", help="Lane D 합성 생존 시뮬레이션")
    parser.add_argument("--lane-d-compare", action="store_true", help="Lane D DCA vs Lump Sum 비교")
    parser.add_argument("--lane-d-paths", type=int, default=50, help="Lane D 경로 수")
    parser.add_argument("--lane-d-years", type=int, default=100, help="Lane D 경로 길이 (년)")
    parser.add_argument("--lane-d-jobs", type=int, default=1, help="Lane D 병렬 워커 수")
    parser.add_argument("--lane-d-mode", type=str, default="sign_flip",
                        choices=["sign_flip", "hmm_regime"],
                        help="Lane D 경로 생성 모드")

    # 추가 분석
    parser.add_argument("--sensitivity", action="store_true", help="민감도 히트맵 (growth × vol)")
    parser.add_argument("--watch", action="store_true", help="파일 변경 감지 → 자동 재실행")
    parser.add_argument("--compare", nargs="+", metavar="JSON",
                        help="비교할 추가 config (예: --compare b.json c.json)")

    args = parser.parse_args(argv)

    # 1. JSON 읽기
    if args.config == "-":
        payload = json.load(sys.stdin)
    else:
        with open(args.config) as f:
            payload = json.load(f)

    # 2. Compile
    from aftertaxi.strategies.compile import compile_backtest
    config = compile_backtest(payload)

    # months override
    n_months = args.months or config.n_months or 240

    # 3. 합성 데이터 생성
    assets = list(config.strategy.weights.keys())

    # compare configs (있으면)
    compare_configs = []
    compare_labels = [Path(args.config).stem]
    if args.compare:
        for cp in args.compare:
            with open(cp) as f:
                cp_payload = json.load(f)
            cp_cfg = compile_backtest(cp_payload)
            compare_configs.append(cp_cfg)
            compare_labels.append(Path(cp).stem)
            assets = list(set(assets) | set(cp_cfg.strategy.weights.keys()))

    returns, prices, fx = _generate_synthetic_data(
        assets, n_months=n_months,
        annual_growth=args.growth, annual_vol=args.vol,
        fx_rate=args.fx, seed=args.seed,
    )

    # 4. 실행
    from aftertaxi.core.facade import run_backtest
    result = run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

    # 5. 출력
    if args.json:
        from aftertaxi.workbench import run_workbench_json
        print(run_workbench_json(
            [payload], returns=returns, prices=prices, fx_rates=fx,
        ))
    else:
        from aftertaxi.core.attribution import build_attribution
        attribution = build_attribution(result)
        _print_result(result, attribution)

    # 5.5 멀티 전략 비교 (--compare)
    if compare_configs:
        from aftertaxi.core.attribution import build_attribution as ba
        from aftertaxi.workbench.compare import compare_strategies
        results = [result]
        for cc in compare_configs:
            r = run_backtest(cc, returns=returns, prices=prices, fx_rates=fx)
            results.append(r)

        report = compare_strategies(results, compare_labels)
        print("\n" + "=" * 60)
        print("  전략 비교")
        print("=" * 60)
        table = report.rank_table()
        # 헤더
        print(f"  {'순위':<4} {'전략':<20} {'세전':>8} {'세후':>10} {'MDD':>8} {'drag':>6}")
        print("  " + "-" * 56)
        for row in table:
            print(f"  {row['rank']:<4} {row['name']:<20} "
                  f"{row['mult_pre_tax']:>7.2f}x {row['mult_after_tax']:>9.2f}x "
                  f"{row['mdd']:>7.1%} {row['tax_drag']:>5.1f}%")
        print(f"\n  세후 우승: {report.winner}")
        print()

    # 6. Lane D (optional)
    if args.lane_d_compare or args.lane_d:
        from aftertaxi.lanes.lane_d.synthetic import SyntheticMarketConfig

        synth_config = SyntheticMarketConfig(
            n_paths=args.lane_d_paths,
            path_length_months=args.lane_d_years * 12,
            seed=args.seed,
            base_fx_rate=args.fx,
            mode=args.lane_d_mode,
        )

        if args.lane_d_compare:
            # compare가 survival을 포함하는 상위 출력
            from aftertaxi.lanes.lane_d.compare import run_lane_d_comparison
            compare_report = run_lane_d_comparison(
                source_returns=returns,
                backtest_config=config,
                synthetic_config=synth_config,
                n_jobs=args.lane_d_jobs,
            )
            print(compare_report.summary_text())
            print()
        else:
            # 기존 survival only
            from aftertaxi.lanes.lane_d.run import run_lane_d
            lane_d_report = run_lane_d(
                source_returns=returns,
                backtest_config=config,
                synthetic_config=synth_config,
                actual_result=result,
                n_jobs=args.lane_d_jobs,
            )
            print(lane_d_report.summary_text())
            print()

    # 7. 민감도 (optional)
    if args.sensitivity:
        from aftertaxi.workbench.sensitivity import run_sensitivity
        print("민감도 분석 실행 중...")
        grid = run_sensitivity(
            strategy_payload=payload.get("strategy", {"type": "spy_bnh"}),
            n_months=n_months,
            fx_rate=args.fx,
            seed=args.seed,
        )
        print(grid.summary_text())
        print()
        df = grid.to_dataframe()
        print("  성장률 →")
        print(f"  변동성↓  {df.to_string()}")
        print()

    return result


def _run_once(argv):
    """한 번 실행. watch 모드용."""
    try:
        main(argv)
    except SystemExit:
        pass
    except Exception as e:
        print(f"실행 오류: {e}")


def entry_point():
    """패키지 엔트리포인트."""
    import sys as _sys
    argv = _sys.argv[1:]

    # --watch 모드
    if "--watch" in argv:
        watch_argv = [a for a in argv if a != "--watch"]
        config_path = watch_argv[0] if watch_argv else None
        if not config_path or config_path == "-":
            print("--watch는 파일 경로가 필요합니다 (stdin 불가)")
            return

        import os, time
        print(f"👁 Watch 모드: {config_path} 변경 감지 중... (Ctrl+C로 종료)")
        last_mtime = 0.0
        try:
            while True:
                try:
                    mtime = os.path.getmtime(config_path)
                except OSError:
                    time.sleep(1)
                    continue
                if mtime > last_mtime:
                    if last_mtime > 0:
                        print(f"\n{'═' * 60}")
                        print(f"  파일 변경 감지: {config_path}")
                        print(f"{'═' * 60}\n")
                    _run_once(watch_argv)
                    last_mtime = mtime
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nWatch 종료.")
    else:
        main()


if __name__ == "__main__":
    main()
