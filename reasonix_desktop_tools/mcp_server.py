"""MCP Server — 向 Agent 暴露桌面操控工具。

工具:
  - get_snapshot() → TextContent + ImageContent
  - click(x, y) → 窗口相对坐标点击
  - type_text(text, x, y) → 窗口相对坐标输入
  - press_key(key) → 发送键盘快捷键
  - switch_window(title) → 切换到指定窗口
  - list_windows() → 列出所有窗口标题
  - scroll(x, y, delta_x, delta_y) → 从坐标处滚动
  - wait(ms) → 异步等待
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Optional

import mcp.types as types

from .executor import (
    click as exec_click,
    double_click as exec_double_click,
    type_text as exec_type_text,
    press_key as exec_press_key,
    hold_key as exec_hold_key,
    release_key as exec_release_key,
    scroll as exec_scroll,
    move_to as exec_move_to,
)
from .screenshot import capture_window
from .windows_api import (
    get_active_window,
    find_window,
    list_active_window_elements,
)

logger = logging.getLogger(__name__)


def _get_window_context() -> tuple | None:
    """获取当前窗口上下文。返回 (win, screen_x_offset, screen_y_offset) 或 None。"""
    win = get_active_window()
    if win is None:
        return None
    return (win, win.rect.left, win.rect.top)


def _activate_window_by_title(title: str) -> bool:
    """激活标题包含指定文字的窗口。"""
    try:
        import uiautomation as uia
        for child in uia.GetRootControl().GetChildren():
            try:
                if child.Name and title.lower() in child.Name.lower():
                    child.SetActive()
                    child.SetFocus()
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def tool_get_snapshot() -> list[types.Content]:
    """快照：窗口信息 + accessibility 树 + 截图（ImageContent）。"""
    win = get_active_window()
    if win is None:
        return [types.TextContent(type="text", text="当前无激活窗口")]

    parts = []
    parts.append(f"当前窗口: \"{win.title}\"")
    parts.append(f"进程: {win.process_name or 'unknown'}")
    parts.append(f"窗口大小: {win.rect.width} x {win.rect.height}")

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

    text_content = types.TextContent(type="text", text="\n".join(parts))

    screenshot = capture_window(
        win.rect.left, win.rect.top,
        win.rect.right, win.rect.bottom
    )
    if screenshot:
        b64, mime = screenshot
        image_content = types.ImageContent(
            type="image", data=b64, mimeType=mime,
        )
        return [text_content, image_content]
    return [text_content]


def tool_click(x: int, y: int) -> list[types.TextContent]:
    """在窗口相对坐标点击。"""
    ctx = _get_window_context()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy = ctx
    result = exec_click(ox + x, oy + y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 点击失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已点击 ({x}, {y})")]


def tool_type_text(text: str, x: int, y: int) -> list[types.TextContent]:
    """在窗口相对坐标处输入文字。"""
    ctx = _get_window_context()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy = ctx
    result = exec_type_text(ox + x, oy + y, text)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 输入失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已在 ({x}, {y}) 输入「{text}」")]


def tool_press_key(key: str) -> list[types.TextContent]:
    """发送键盘按键或快捷键。"""
    result = exec_press_key(key)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 按键失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 按键: {key}")]


def tool_switch_window(title: str) -> list[types.TextContent]:
    """切换到标题包含指定文字的窗口。"""
    win = find_window(title_match=title)
    if win is None:
        return [types.TextContent(type="text", text=f"❌ 未找到窗口: {title}")]
    ok = _activate_window_by_title(title)
    if ok:
        return [types.TextContent(type="text", text=f"✅ 已切换到: {win.title}")]
    return [types.TextContent(type="text", text=f"❌ 无法激活窗口: {title}")]


def tool_list_windows(limit: int = 20) -> list[types.TextContent]:
    """列出所有顶层窗口标题。limit 控制最大返回数，默认 20。"""
    try:
        import uiautomation as uia
        titles = []
        for child in uia.GetRootControl().GetChildren():
            if len(titles) >= limit:
                break
            try:
                name = child.Name
                if name and name.strip():
                    titles.append(name)
            except Exception:
                continue
        text = f"当前窗口列表 (前 {len(titles)} 个):\n"
        text += "\n".join(f"  - \"{t}\"" for t in titles)
        return [types.TextContent(type="text", text=text)]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"❌ 获取窗口列表失败: {exc}")]


def tool_scroll(x: int, y: int,
                delta_x: int = 0, delta_y: int = 5) -> list[types.TextContent]:
    """从窗口相对坐标处滚动。delta_y>0 向下，<0 向上。"""
    ctx = _get_window_context()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy = ctx
    result = exec_scroll(ox + x, oy + y, delta_x, delta_y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 滚动失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已从 ({x},{y}) 滚动")]


async def tool_wait(ms: int) -> list[types.TextContent]:
    """等待指定毫秒数（异步非阻塞）。"""
    await asyncio.sleep(ms / 1000.0)
    return [types.TextContent(type="text", text=f"✅ 等待 {ms}ms")]


def tool_double_click(x: int, y: int) -> list[types.TextContent]:
    """在窗口相对坐标处双击。"""
    ctx = _get_window_context()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy = ctx
    result = exec_double_click(ox + x, oy + y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 双击失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已双击 ({x}, {y})")]


def tool_move_to(x: int, y: int) -> list[types.TextContent]:
    """移动鼠标到窗口相对坐标 (x,y) 处（不点击）。"""
    ctx = _get_window_context()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy = ctx
    result = exec_move_to(ox + x, oy + y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 移动失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已移动鼠标到 ({x}, {y})")]


def tool_hold_key(key: str) -> list[types.TextContent]:
    """按住一个键不放。需配合 click 等操作后调用 release_key 释放。"""
    result = exec_hold_key(key)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 按键失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已按住: {key}")]


def tool_release_key(key: str) -> list[types.TextContent]:
    """释放之前按住的键。"""
    result = exec_release_key(key)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 释放失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已释放: {key}")]


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
                    description="获取当前激活窗口完整快照。返回窗口信息 + 控件列表 + 截图（Agent可直接查看）。截图使用D3D后端，被遮挡也能截取。Agent根据截图和控件信息决定下一步操作的坐标。",
                    inputSchema={"type": "object", "properties": {}},
                ),
                types.Tool(
                    name="click",
                    description="在窗口相对坐标 (x,y) 处点击左键。(0,0)=窗口左上角。x/y范围来自 get_snapshot 返回的窗口尺寸。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
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
                            "text": {"type": "string"},
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                        },
                        "required": ["text", "x", "y"],
                    },
                ),
                types.Tool(
                    name="press_key",
                    description="发送键盘按键或快捷键。支持: Enter, Escape, Tab, ArrowUp/Down/Left/Right, ctrl+c/v/a/z, Alt+Tab, Shift+F10, F1-F12",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "按键名或组合，如 'Enter', 'ctrl+c', 'Alt+Tab'"}
                        },
                        "required": ["key"],
                    },
                ),
                types.Tool(
                    name="switch_window",
                    description="切换到标题包含指定文字的窗口。如 '微信'、'Chrome'、'记事本'。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"}
                        },
                        "required": ["title"],
                    },
                ),
                types.Tool(
                    name="list_windows",
                    description="列出当前所有顶层窗口标题。",
                    inputSchema={"type": "object", "properties": {}},
                ),
                types.Tool(
                    name="scroll",
                    description="从窗口相对坐标 (x,y) 处滚动滚轮。delta_y>0 向下翻，<0 向上翻。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "delta_x": {"type": "integer", "default": 0},
                            "delta_y": {"type": "integer", "default": 5},
                        },
                        "required": ["x", "y"],
                    },
                ),
                types.Tool(
                    name="wait",
                    description="等待指定毫秒数（异步，不阻塞其他请求）。用于等待界面加载或动画完成。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ms": {"type": "integer", "description": "毫秒，如 1000=1秒"}
                        },
                        "required": ["ms"],
                    },
                ),
                types.Tool(
                    name="double_click",
                    description="在窗口相对坐标 (x,y) 处双击。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                        },
                        "required": ["x", "y"],
                    },
                ),
                types.Tool(
                    name="move_to",
                    description="移动鼠标到窗口相对坐标 (x,y) 处（不点击）。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                        },
                        "required": ["x", "y"],
                    },
                ),
                types.Tool(
                    name="hold_key",
                    description="按住一个键不放（不释放）。之后需要调用 release_key 释放。用于 '按住 Ctrl 点击' 等组合操作。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "按键名，如 'Control'、'Shift'、'Alt'"}
                        },
                        "required": ["key"],
                    },
                ),
                types.Tool(
                    name="release_key",
                    description="释放之前用 hold_key 按住的键。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "按键名，与 hold_key 传入的一致"}
                        },
                        "required": ["key"],
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
                return tool_type_text(arguments["text"], arguments["x"], arguments["y"])
            elif name == "press_key":
                return tool_press_key(arguments["key"])
            elif name == "switch_window":
                return tool_switch_window(arguments["title"])
            elif name == "list_windows":
                return tool_list_windows()
            elif name == "scroll":
                return tool_scroll(
                    arguments["x"], arguments["y"],
                    arguments.get("delta_x", 0),
                    arguments.get("delta_y", 5),
                )
            elif name == "wait":
                return await tool_wait(arguments["ms"])
            elif name == "double_click":
                return tool_double_click(arguments["x"], arguments["y"])
            elif name == "move_to":
                return tool_move_to(arguments["x"], arguments["y"])
            elif name == "hold_key":
                return tool_hold_key(arguments["key"])
            elif name == "release_key":
                return tool_release_key(arguments["key"])
            else:
                raise ValueError(f"未知工具: {name}")

        async def run():
            async with mcp.server.stdio.stdio_server() as (rs, ws):
                await app.run(
                    rs, ws,
                    InitializationOptions(
                        server_name="desktop",
                        server_version="0.3.0",
                    ),
                )

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
