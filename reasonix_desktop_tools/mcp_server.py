"""MCP Server — 向 Agent 暴露桌面操控工具。

3 个工具:
  - get_snapshot() → 当前窗口信息 + 截图
  - click(x, y) → 在窗口相对坐标点击
  - type_text(text, x, y) → 在窗口相对坐标输入文字

注册到 Codex:
  claude mcp add --transport stdio --scope project desktop ^
    -- python -m reasonix_desktop_tools.mcp_server
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from .executor import (
    click as exec_click,
    type_text as exec_type_text,
    get_cursor_position,
)
from .screenshot import capture_window, capture_full_screen
from .windows_api import (
    get_active_window,
    find_element_by_name,
    list_active_window_elements,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def get_snapshot_text() -> str:
    """获取当前窗口的结构化信息文本（不含截图）。"""
    parts = []

    # 当前激活窗口
    win = get_active_window()
    if win is None:
        return "当前无激活窗口"

    parts.append(f"当前窗口: \"{win.title}\"")
    parts.append(f"进程: {win.process_name or 'unknown'}")
    parts.append(f"窗口位置: ({win.rect.left}, {win.rect.top})")
    parts.append(f"窗口大小: {win.rect.width} x {win.rect.height}")

    # accessibility 树
    elements = list_active_window_elements()
    if elements:
        parts.append(f"\n可交互控件 ({len(elements)} 个):")
        for i, e in enumerate(elements):
            parts.append(
                f"  [{i}] [{e.role}] \"{e.name}\" "
                f"@ ({e.rect.center_x - win.rect.left}, "
                f"{e.rect.center_y - win.rect.top})"
                f" {'[可用]' if e.is_enabled else '[不可用]'}"
            )
    else:
        parts.append("\n(该窗口未暴露可交互控件信息，请参考截图)")

    return "\n".join(parts)


def get_snapshot() -> str:
    """完整快照：窗口信息 + 截图。

    LLM 使用返回的截图和窗口信息来决定下一步操作。
    截图为 base64 格式，窗口位置用于计算窗口相对坐标。
    """
    win = get_active_window()
    if win is None:
        return "当前无激活窗口"

    # 结构化信息
    text = get_snapshot_text()

    # 截图（DXcam 优先，可截取被遮挡窗口）
    screenshot = capture_window(
        win.rect.left, win.rect.top,
        win.rect.right, win.rect.bottom
    )
    if screenshot:
        text += f"\n\n截图(base64): data:image/png;base64,{screenshot}"
    else:
        text += "\n\n截图失败"

    return text


def tool_click(x: int, y: int) -> str:
    """在窗口相对坐标 (x, y) 处点击。

    (0, 0) 是当前激活窗口左上角。
    x, y 值的范围取决于窗口大小，来自 get_snapshot 返回的窗口尺寸。
    """
    win = get_active_window()
    if win is None:
        return "❌ 当前无激活窗口"

    # 窗口相对坐标 → 屏幕绝对坐标
    screen_x = win.rect.left + x
    screen_y = win.rect.top + y

    result = exec_click(screen_x, screen_y)
    if not result.success:
        return f"❌ 点击失败: {result.message}"

    return f"✅ 已点击窗口相对坐标 ({x}, {y})"


def tool_type_text(text: str, x: int, y: int) -> str:
    """在窗口相对坐标 (x, y) 处输入文本。

    先点击该位置，再输入文字。
    """
    win = get_active_window()
    if win is None:
        return "❌ 当前无激活窗口"

    screen_x = win.rect.left + x
    screen_y = win.rect.top + y

    result = exec_type_text(screen_x, screen_y, text)
    if not result.success:
        return f"❌ 输入失败: {result.message}"

    return f"✅ 已在 ({x}, {y}) 输入「{text}」"


# ---------------------------------------------------------------------------
# MCP Server 启动
# ---------------------------------------------------------------------------

def main() -> None:
    """启动 MCP Server。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    try:
        from mcp.server import Server
        from mcp.server.models import InitializationOptions
        import mcp.server.stdio
        import mcp.types as types

        app = Server("desktop")

        @app.list_tools()
        async def list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="get_snapshot",
                    description=(
                        "获取当前激活窗口的完整快照。"
                        "返回窗口标题、位置、尺寸、可交互控件列表（如果有），"
                        "以及一张 base64 编码的窗口截图。"
                        "截图使用 D3D 后端，即使窗口被其他窗口遮挡也能截取。"
                        "Agent 拿到截图后自行分析界面布局，计算下一步操作的窗口相对坐标。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.Tool(
                    name="click",
                    description=(
                        "在窗口相对坐标 (x, y) 处点击左键。"
                        "(0, 0) 是当前激活窗口的左上角。"
                        "x 和 y 的取值范围取决于窗口尺寸，"
                        "来自 get_snapshot 返回的窗口大小信息。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {
                                "type": "integer",
                                "description": "相对于窗口左上角的 X 坐标",
                            },
                            "y": {
                                "type": "integer",
                                "description": "相对于窗口左上角的 Y 坐标",
                            },
                        },
                        "required": ["x", "y"],
                    },
                ),
                types.Tool(
                    name="type_text",
                    description=(
                        "在窗口相对坐标 (x, y) 处点击聚焦后输入文字。"
                        "适用于输入框等文本编辑控件。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "要输入的文本内容",
                            },
                            "x": {
                                "type": "integer",
                                "description": "相对于窗口左上角的 X 坐标",
                            },
                            "y": {
                                "type": "integer",
                                "description": "相对于窗口左上角的 Y 坐标",
                            },
                        },
                        "required": ["text", "x", "y"],
                    },
                ),
            ]

        @app.call_tool()
        async def call_tool(
            name: str,
            arguments: dict,
        ) -> list[types.TextContent]:
            if name == "get_snapshot":
                result = get_snapshot()
            elif name == "click":
                result = tool_click(arguments["x"], arguments["y"])
            elif name == "type_text":
                result = tool_type_text(
                    arguments["text"],
                    arguments["x"],
                    arguments["y"],
                )
            else:
                raise ValueError(f"未知工具: {name}")

            return [types.TextContent(type="text", text=result)]

        async def run():
            async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
                await app.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="desktop",
                        server_version="0.1.0",
                    ),
                )

        import asyncio
        asyncio.run(run())

    except ImportError as exc:
        logger.error("启动失败: 需要安装 mcp 库: pip install mcp")
        logger.error(str(exc))
        sys.exit(1)
    except Exception as exc:
        logger.error("MCP Server 异常退出: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
