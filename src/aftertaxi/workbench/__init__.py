# -*- coding: utf-8 -*-
"""Deprecated: use aftertaxi.analysis instead.

This module exists for backward compatibility only.
All new code should import from aftertaxi.analysis.
"""
from aftertaxi.analysis import *  # noqa: F401,F403
from aftertaxi.analysis import run_workbench_json  # noqa: F401

import warnings as _w
_w.warn("aftertaxi.workbench is deprecated. Use aftertaxi.analysis.", DeprecationWarning, stacklevel=2)
