"""UIA 控件遍历的超时保护。

在单独线程中运行 UIA 遍历，超时则放弃等待。
对 COM STA 模型正确初始化。
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Any

from .windows_api import ElementInfo, _walk_controls

logger = logging.getLogger(__name__)

# COM 初始化常量
COINIT_APARTMENTTHREADED = 2  # STA


def _init_com_sta() -> None:
    """在当前线程初始化 COM STA。"""
    try:
        ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except Exception:
        pass


def _uninit_com() -> None:
    """释放当前线程的 COM。"""
    try:
        ctypes.windll.ole32.CoUninitialize()
    except Exception:
        pass


def timeout_collect(
    win_control: object,
    result: list[ElementInfo],
    max_depth: int = 3,
    max_seconds: float = 2.0,
) -> None:
    """在超时保护下收集 UIA 控件。超时后返回当前已收集的结果。

    参数:
        win_control: 顶层窗口 UIA 控件
        result: 输出列表
        max_depth: UIA 遍历深度
        max_seconds: 超时秒数
    """
    done = threading.Event()
    thread_result: list[ElementInfo] = []
    lock = threading.Lock()

    def _worker():
        _init_com_sta()
        local_result: list[ElementInfo] = []
        try:
            _walk_controls(win_control, local_result, 0, max_depth)
        except Exception as exc:
            logger.debug("UIA 遍历线程异常: %s", exc)
        with lock:
            thread_result.extend(local_result)
        done.set()
        _uninit_com()

    t = threading.Thread(target=_worker, daemon=True)
    t_start = time.monotonic()
    t.start()

    finished = done.wait(timeout=max_seconds)
    elapsed = time.monotonic() - t_start

    with lock:
        if finished:
            result.extend(thread_result)
            logger.debug(
                "UIA 遍历完成: %d 个控件 (%dms)",
                len(thread_result), int(elapsed * 1000),
            )
        else:
            logger.warning(
                "UIA 遍历超时 (%.1fs > %.1fs)，已收集 %d 个控件",
                elapsed, max_seconds, len(thread_result),
            )
            result.extend(thread_result)
