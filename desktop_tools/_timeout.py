"""UIA 控件遍历的超时保护。

在线程中遍历 UIA 控件，超时则放弃等待。
传入 hwnd (int) 而非 UIA 控件对象——每个线程在自己的 STA 中获取控件，
避免跨线程 COM 封送问题。
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Any

from .windows_api import ElementInfo, _walk_controls

logger = logging.getLogger(__name__)

COINIT_APARTMENTTHREADED = 2  # STA


def _init_com_sta() -> None:
    try:
        ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except Exception:
        pass


def _uninit_com() -> None:
    try:
        ctypes.windll.ole32.CoUninitialize()
    except Exception:
        pass


def timeout_collect(
    win_hwnd: int,
    result: list[ElementInfo],
    max_depth: int = 3,
    max_seconds: float = 2.0,
) -> None:
    """在超时保护下收集 UIA 控件。

    传入 hwnd (int) 而非 UIA 控件对象——worker 线程在自己的 STA 中
    通过 hwnd 获取控件，避免跨线程 COM 封送。

    参数:
        win_hwnd: 窗口句柄 (int, 跨线程安全)
        result: 输出列表
        max_depth: UIA 遍历深度
        max_seconds: 超时秒数
    """
    done = threading.Event()
    thread_result: list[ElementInfo] = []

    def _worker():
        _init_com_sta()
        local_result: list[ElementInfo] = []
        try:
            # 在线程自己的 STA 中获取 UIA 控件
            import uiautomation as uia
            control = uia.ControlFromHandle(win_hwnd)
            if control is not None:
                _walk_controls(control, local_result, 0, max_depth)
        except Exception as exc:
            logger.debug("UIA 遍历线程异常: %s", exc)
        thread_result.extend(local_result)
        done.set()
        _uninit_com()

    t = threading.Thread(target=_worker, daemon=True)
    t_start = time.monotonic()
    t.start()

    finished = done.wait(timeout=max_seconds)
    elapsed = time.monotonic() - t_start

    if finished:
        result.extend(thread_result)
        logger.debug(
            "UIA 遍历完成: %d 个控件 (%dms)",
            len(thread_result), int(elapsed * 1000),
        )
    else:
        logger.warning(
            "UIA 遍历超时 (%.1fs > %.1fs)，返回 %d 个控件",
            elapsed, max_seconds, len(thread_result),
        )
        result.extend(thread_result)
