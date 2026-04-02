# -*- coding: utf-8 -*-
"""
strategies/ — 전략 등록소
=========================
전략 추가 = builders.py에 함수 하나 + @registry.register("key")

사용법:
  from aftertaxi.strategies import registry

  registry.available()           # ['q60s40', 'spy_bnh', '6040', ...]
  spec = registry.build("q60s40")
  config = spec.to_config()      # → StrategyConfig (엔진 입력)

  # JSON에서
  spec = registry.build_from_dict({"type": "q60s40"})

  # 여러 개
  specs = registry.build_many([{"type": "q60s40"}, {"type": "spy_bnh"}])
"""
# builders를 import하면 @registry.register가 실행되어 빌더가 등록됨
from aftertaxi.strategies.registry import registry
from aftertaxi.strategies.spec import StrategySpec
from aftertaxi.strategies.compile import compile_strategy, compile_backtest
import aftertaxi.strategies.builders  # noqa: F401 — 등록 트리거
