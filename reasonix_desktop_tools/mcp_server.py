"""MCP Server — 向 Agent 暴露桌面操控工具。

工具:
  - get_snapshot() → TextContent + ImageContent
  - click(x, y) → 窗口相对坐标点击
  - type_text(text, x, y) → 窗口相对坐标输入
  - press_key(key) → 发送键盘快捷键
  - switch_window(title) → 切换到指定窗口
  - scroll(x, y, delta_x, delta_y) → 从坐标处滚动
  - wait(ms) → 等待指定毫秒数
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional

import mcp.types as types

from .executor import (
    click as exec_click,
    type_text as exec_type_text,
    press_key as exec_press_key,
    scroll as exec_scroll,
)
from .screenshot import capture_window
from .windows_api import (
    get_active_window,
    find_window,
    list_active_window_elements,
)

logger = logging.getLogger(__name__)

# 工具返回类型: list of TextContent | ImageContent
# call_tool 返回 list[types.TextContent | types.ImageContent]


def _get_window_context() -> tuple | None:
    """获取当前窗口上下文。返回 (win, screen_x_offset, screen_y_offset) 或 None。"""
    win = get_active_window()
    if win is None:
        return None
    return (win, win.rect.left, win.rect.top)


def tool_get_snapshot():
    """快照：窗口信息 + accessibility 树 + 截图（ImageContent）。"""
    win = get_active_window()
    if win is None:
        return [types.TextContent(type="text", text="当前无激活窗口")]

    # -- 文本部分 --
    parts = []
    parts.append(f"当前窗口: \"{win.title}\"")
    parts.append(f"进程: {win.process_name or 'unknown'}")
    parts.append(f"窗口大小: {win.rect.width} x {win.rect.height}")

    # accessibility 树（精简版，最多 15 个控件）
    elements = list_active_window_elements()
    if elements:
        parts.append(f"\n可交互控件 ({len(elements)} 个):")
        shown = elements[:15]
        for i, e in enumerate(shown):
            parts.append(
                f"  [{i}] [{e.role}] \"{e.name}\" "
                f"@ ({e.rect.center_x - win.rect.left}, "
                f"{e.rect.center_y - win.rect.top})"
                f" {'[可用]' if e.is_enabled else '[不可用]'}"
            )
        if len(elements) > 15:
            parts.append(f"  ... 还有 {len(elements) - 15} 个控件未显示")
    else:
        parts.append("\n(该窗口未暴露可交互控件信息，请查看截图自行判断)")

    text_content = types.TextContent(
        type="text", text="\n".join(parts)
    )

    # -- 截图部分（ImageContent）--
    screenshot = capture_window(
        win.rect.left, win.rect.top,
        win.rect.right, win.rect.bottom
    )
    if screenshot:
        image_content = types.ImageContent(
            type="image",
            data=screenshot,
            mimeType="image/png",
        )
        return [text_content, image_content]
    else:
        return [text_content]


def tool_click(x: int, y: int):
    """在窗口相对坐标点击。"""
    ctx = _get_window_context()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy = ctx
    result = exec_click(ox + x, oy + y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 点击失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已点击 ({x}, {y})")]


def tool_type_text(text: str, x: int, y: int):
    """在窗口相对坐标处输入文字。"""
    ctx = _get_window_context()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy = ctx
    result = exec_type_text(ox + x, oy + y, text)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 输入失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已在 ({x}, {y}) 输入「{text}」")]


def tool_press_key(key: str):
    """发送键盘按键或快捷键，如 'Enter', 'Escape', 'ctrl+c', 'Alt+Tab'。"""
    result = exec_press_key(key)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 按键失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 按键: {key}")]


def tool_switch_window(title: str):
    """切换到标题包含指定文字的窗口。"""
    win = find_window(title_match=title)
    if win is None:
        return [types.TextContent(type="text", text=f"❌ 未找到窗口: {title}")]
    try:
        import uiautomation as uia
        for child in uia.GetRootControl().GetChildren():
            try:
                if child.Name and title.lower() in child.Name.lower():
                    child.SetActive()
                    child.SetFocus()
                    time.sleep(0.3)
                    return [types.TextContent(type="text", text=f"✅ 已切换到: {win.title}")]
            except Exception:
                continue
    except Exception:
        pass
    return [types.TextContent(type="text", text=f"❌ 无法激活窗口: {title}")]


def tool_scroll(x: int, y: int, delta_x: int = 0, delta_y: int = 2):
    """从窗口相对坐标 (x,y) 处滚动。delta_y > 0 向下，< 0 向上。"""
    ctx = _get_window_context()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy = ctx
    result = exec_scroll(ox + x, oy + y, delta_x, delta_y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 滚动失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已从 ({x},{y}) 滚动")]


def tool_wait(ms: int):
    """等待指定毫秒数。"""
    time.sleep(ms / 1000.0)
    return [types.TextContent(type="text", text=f"✅ 等待 {ms}ms")]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    try:
        from mcp.server import Server
        from mcp.server.models import InitializationOptions
        import mcp.server.stdio
        app = Server("desktop")

        @app.list_tools()
        async def list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="get_snapshot",
                    description=(
                        "获取当前激活窗口的完整快照。"
                        "返回窗口信息 + 可交互控件列表（如果有） + 截图（Agent 可直接看到）。"
                        "截图使用 D3D 后端，即使窗口被遮挡也能截取。"
                        "Agent 根据截图和控件信息决定下一步操作的坐标。"
                    ),
                    inputSchema={"type": "object", "properties": {}},
                ),
                types.Tool(
                    name="click",
                    description=(
                        "在窗口相对坐标 (x, y) 处点击左键。"
                        "(0,0)=窗口左上角。x/y 范围取决于窗口大小（来自 get_snapshot）。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer", "description": "窗口相对 X 坐标"},
                            "y": {"type": "integer", "description": "窗口相对 Y 坐标"},
                        },
                        "required": ["x", "y"],
                    },
                ),
                types.Tool(
                    name="type_text",
                    description="在窗口相对坐标 (x,y) 处点击后输入文字。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "要输入的文本"},
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                        },
                        "required": ["text", "x", "y"],
                    },
                ),
                types.Tool(
                    name="press_key",
                    description=(
                        "发送键盘按键或快捷键。"
                        "支持: Enter, Escape, Tab, Backspace, Delete, "
                        "ArrowUp, ArrowDown, ArrowLeft, ArrowRight, "
                        "ctrl+c, ctrl+v, ctrl+a, ctrl+z, Alt+Tab, Shift+F10"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "按键名称或组合，如 'Enter'、'ctrl+c'、'Alt+Tab'"}
                        },
                        "required": ["key"],
                    },
                ),
                types.Tool(
                    name="switch_window",
                    description="切换到标题包含指定文字的窗口。如 '微信'、'Chrome'。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "窗口标题包含的文字"}
                        },
                        "required": ["title"],
                    },
                ),
                types.Tool(
                    name="scroll",
                    description="从窗口相对坐标 (x,y) 处滚动。delta_y>0 向下，<0 向上。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer", "description": "窗口相对 X 坐标"},
                            "y": {"type": "integer", "description": "窗口相对 Y 坐标"},
                            "delta_x": {"type": "integer", "description": "水平滚动量（正数向右）", "default": 0},
                            "delta_y": {"type": "integer", "description": "垂直滚动量（正数向下）", "default": 2},
                        },
                        "required": ["x", "y"],
                    },
                ),
                types.Tool(
                    name="wait",
                    description="等待指定毫秒数。用于等待界面加载、动画完成等。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ms": {"type": "integer", "description": "等待毫秒数，如 1000=1秒"}
                        },
                        "required": ["ms"],
                    },
                ),
            ]

        @app.call_tool()
        async def call_tool(name: str, arguments: dict) -> list:
            if name == "get_snapshot":
                return tool_get_snapshot()
            elif name == "click":
                return tool_click(arguments["x"], arguments["y"])
            elif name == "type_text":
                return tool_type_text(
                    arguments["text"], arguments["x"], arguments["y"]
                )
            elif name == "press_key":
                return tool_press_key(arguments["key"])
            elif name == "switch_window":
                return tool_switch_window(arguments["title"])
            elif name == "scroll":
                return tool_scroll(
                    arguments["x"], arguments["y"],
                    arguments.get("delta_x", 0),
                    arguments.get("delta_y", 2),
                )
            elif name == "wait":
                return tool_wait(arguments["ms"])
            else:
                raise ValueError(f"未知工具: {name}")

        async def run():
            async with mcp.server.stdio.stdio_server() as (rs, ws):
                await app.run(
                    rs, ws,
                    InitializationOptions(
                        server_name="desktop",
                        server_version="0.2.0",
                    ),
                )

        import asyncio
        asyncio.run(run())

    except ImportError as exc:
        logger.error("启动失败: pip install mcp")
        logger.error(str(exc))
        sys.exit(1)
    except Exception as exc:
        logger.error("MCP Server 异常退出: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
