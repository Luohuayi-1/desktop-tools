"""预设加载器 — 从本地预设文件获取控件坐标。

MCP Server 在 _get_ctx 中调用此模块，
如果当前窗口有匹配的预设，直接用百分比坐标计算位置，
无需走 VLM/截图定位。
"""

from __future__ import annotations

import json
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 预设搜索路径
PRESETS_DIRS = [
    os.path.join(os.path.expanduser("~"), ".desktop-tools", "presets"),
    os.path.join(os.path.dirname(__file__), "..", "presets"),
]


def find_element(app_name: str, element_name: str,
                 client_width: int, client_height: int,
                 process_name: str = "") -> Optional[tuple[int, int]]:
    """从预设中查找控件坐标。

    参数:
        app_name: 应用名，如 "wechat"
        element_name: 控件名，如 "搜索框"
        client_width / client_height: 当前窗口客户区尺寸
        process_name: 进程名（可选，用于匹配）

    返回 (x, y) 屏幕坐标，未找到返回 None。
    """
    preset = _load_best_preset(app_name, process_name)
    if preset is None:
        return None

    elements = preset.get("elements", {})
    elem = elements.get(element_name)
    if elem is None:
        # 尝试模糊匹配
        for key, val in elements.items():
            if element_name in key or key in element_name:
                elem = val
                break
    if elem is None:
        return None

    x = int(elem["x_pct"] * client_width)
    y = int(elem["y_pct"] * client_height)
    logger.debug("预设命中: %s/%s → (%d, %d)", app_name, element_name, x, y)
    return (x, y)


def _load_best_preset(app_name: str, process_name: str = "") -> Optional[dict]:
    """从所有预设路径加载最佳匹配的预设。"""
    for base_dir in PRESETS_DIRS:
        if not os.path.isdir(base_dir):
            continue
        for fname in os.listdir(base_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(base_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    preset = json.load(f)
            except Exception:
                continue

            p_app = preset.get("app", "").lower()
            p_proc = preset.get("process_name", "").lower()

            # 匹配应用名
            if app_name.lower() != p_app:
                continue
            # 匹配进程名（如果预设中有且当前进程有）
            if process_name and p_proc and process_name.lower() != p_proc:
                continue

            return preset

    return None


def list_available_presets() -> list[dict]:
    """列出所有可用的预设摘要。"""
    results = []
    for base_dir in PRESETS_DIRS:
        if not os.path.isdir(base_dir):
            continue
        for fname in os.listdir(base_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(base_dir, fname), "r", encoding="utf-8") as f:
                    preset = json.load(f)
                results.append({
                    "file": fname,
                    "app": preset.get("app", "?"),
                    "version": preset.get("version", "?"),
                    "elements": len(preset.get("elements", {})),
                })
            except Exception:
                pass
    return results
