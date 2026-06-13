"""UIA 控件遍历的超时保护。

在单独线程中运行 UIA 遍历，超时则终止。
Windows 没有 SIGALRM，只能用 threading + 超时放弃。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .windows_api import ElementInfo, _walk_controls

logger = logging.getLogger(__name__)


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

    def _worker():
        nonlocal thread_result
        local_result: list[ElementInfo] = []
        try:
            _walk_controls(win_control, local_result, 0, max_depth)
        except Exception as exc:
            logger.debug("UIA 遍历线程异常: %s", exc)
        thread_result = local_result
        done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t_start = time.monotonic()
    t.start()

    # 等待完成或超时
    finished = done.wait(timeout=max_seconds)
    elapsed = time.monotonic() - t_start

    if finished:
        result.extend(thread_result)
        logger.debug("UIA 遍历完成: %d 个控件 (%dms)", len(thread_result), int(elapsed * 1000))
    else:
        # 超时: 放弃等待，用已有结果
        # 线程还在后台跑，但不再等它
        logger.warning(
            "UIA 遍历超时 (%.1fs > %.1fs)，已收集 %d 个控件",
            elapsed, max_seconds, len(thread_result),
        )
        result.extend(thread_result)
