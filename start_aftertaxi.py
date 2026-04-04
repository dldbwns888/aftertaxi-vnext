#!/usr/bin/env python3
"""
start_aftertaxi.py — 원클릭 런처
=================================
더블클릭하면 가상환경 생성 + 의존성 설치 + Streamlit 실행.

사용법:
  python start_aftertaxi.py
  또는 더블클릭 (Windows에서 .py가 Python에 연결돼 있으면)
"""
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent
VENV = ROOT / ".venv"
APP = ROOT / "src" / "aftertaxi" / "apps" / "gui" / "streamlit_app.py"


def run(cmd, **kwargs):
    print(f"  → {' '.join(cmd)}")
    return subprocess.run(cmd, **kwargs)


def main():
    print("=" * 50)
    print("  aftertaxi-vnext 실행기")
    print("=" * 50)

    # 1. 가상환경
    if not VENV.exists():
        print("\n[1/3] 가상환경 생성...")
        run([sys.executable, "-m", "venv", str(VENV)])
    else:
        print("\n[1/3] 가상환경 확인 ✓")

    # pip/streamlit 경로
    if os.name == "nt":
        pip = str(VENV / "Scripts" / "pip")
        streamlit = str(VENV / "Scripts" / "streamlit")
        python = str(VENV / "Scripts" / "python")
    else:
        pip = str(VENV / "bin" / "pip")
        streamlit = str(VENV / "bin" / "streamlit")
        python = str(VENV / "bin" / "python")

    # 2. 의존성
    print("\n[2/3] 의존성 설치...")
    result = run([pip, "install", "-e", ".[gui,data]"], cwd=str(ROOT))
    if result.returncode != 0:
        print("\n❌ 의존성 설치 실패. Python 3.10+ 필요.")
        input("아무 키나 누르세요...")
        return

    # 3. 실행
    print("\n[3/3] Streamlit 실행 중...")
    print(f"  브라우저에서 http://localhost:8501 열림\n")

    try:
        run([streamlit, "run", str(APP)], cwd=str(ROOT))
    except KeyboardInterrupt:
        print("\n종료.")


if __name__ == "__main__":
    main()
