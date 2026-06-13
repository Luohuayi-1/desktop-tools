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
  - double_click(x, y) → 双击
  - move_to(x, y) → 移动鼠标
  - hold_key(key) → 按住键
  - release_key(key) → 释放键
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import sys

import mcp.types as types

from . import __version__
from .executor import (
    click as exec_click,
    double_click as exec_double_click,
    type_text as exec_type_text,
    press_key as exec_press_key,
    hold_key as exec_hold_key,
    release_key as exec_release_key,
    scroll as exec_scroll,
    move_to as exec_move_to,
    bring_to_front,
)
from .screenshot import capture_window
from .windows_api import (
    get_active_window,
    list_active_window_elements,
    _find_top_level_window,
    _import_uia,
)

logger = logging.getLogger(__name__)

_WIN_CACHE = None  # (win, ox, oy, hwnd, win_control)


def _get_ctx():
    """获取当前窗口上下文。缓存避免重复调用 UIA。"""
    global _WIN_CACHE
    win = get_active_window()
    if win is None:
        _WIN_CACHE = None
        return None
    # 使用客户区坐标（不含标题栏+边框）
    from .windows_api import get_client_rect
    cr = get_client_rect(win.hwnd)
    if cr:
        ox, oy = cr['client_left'], cr['client_top']
    else:
        ox, oy = win.rect.left, win.rect.top
    # 获取 UIA 控件引用供 list_active_window_elements 复用
    uia = _import_uia()
    win_control = None
    if uia:
        try:
            focused = uia.GetFocusedControl()
            root = uia.GetRootControl()
            win_control = _find_top_level_window(focused, root)
        except Exception:
            pass
    ctx = (win, ox, oy, win.hwnd, win_control)
    _WIN_CACHE = ctx
    return ctx


def _bring_target_front(hwnd: int) -> bool:
    """前置目标窗口。返回窗口是否有效（未被销毁）。"""
    if not hwnd:
        return False
    if not ctypes.windll.user32.IsWindow(hwnd):
        return False
    bring_to_front(hwnd)
    return True


def tool_get_snapshot() -> list[types.Content]:
    """快照：窗口信息 + accessibility 树 + 截图（ImageContent）。"""
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="当前无激活窗口")]
    win, ox, oy, hwnd, win_control = ctx

    parts = []
    parts.append(f"当前窗口: \"{win.title}\"")
    parts.append(f"进程: {win.process_name or 'unknown'}")
    parts.append(f"窗口大小: {win.rect.width} x {win.rect.height}")

    # 复用 win_control，避免再次 GetFocusedControl
    elements = list_active_window_elements(win_control=win_control)
    if elements:
        parts.append(f"\n可交互控件 ({len(elements)} 个):")
        shown = elements[:15]
        for i, e in enumerate(shown):
            parts.append(
                f"  [{i}] [{e.role}] \"{e.name}\" "
                f"@ ({e.rect.center_x - ox}, "
                f"{e.rect.center_y - oy})"
                f" {'[可用]' if e.is_enabled else '[不可用]'}"
            )
        if len(elements) > 15:
            parts.append(f"  ... 还有 {len(elements) - 15} 个控件未显示")
    else:
        parts.append("\n(该窗口未暴露可交互控件信息，请查看截图自行判断)")

    text_content = types.TextContent(type="text", text="\n".join(parts))
    screenshot = capture_window(ox, oy, ox + win.rect.width, oy + win.rect.height, hwnd=hwnd)
    if screenshot:
        b64, mime = screenshot
        return [text_content, types.ImageContent(type="image", data=b64, mimeType=mime)]
    return [text_content]


def _do_click(x: int, y: int, label: str = "点击") -> list[types.TextContent]:
    """通用点击操作（优化2: 先激活窗口）。"""
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _ = ctx
    _bring_target_front(hwnd)
    result = exec_click(ox + x, oy + y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ {label}失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已{label} ({x}, {y})")]


def tool_click(x: int, y: int) -> list[types.TextContent]:
    return _do_click(x, y, "点击")


def tool_double_click(x: int, y: int) -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _ = ctx
    _bring_target_front(hwnd)
    result = exec_double_click(ox + x, oy + y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 双击失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已双击 ({x}, {y})")]


def tool_move_to(x: int, y: int) -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _ = ctx
    _bring_target_front(hwnd)
    result = exec_move_to(ox + x, oy + y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 移动失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已移动鼠标到 ({x}, {y})")]


def tool_type_text(text: str, x: int, y: int) -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _ = ctx
    _bring_target_front(hwnd)
    result = exec_type_text(ox + x, oy + y, text)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 输入失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已在 ({x}, {y}) 输入「{text}」")]


def tool_scroll(x: int, y: int,
                delta_x: int = 0, delta_y: int = 5) -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _ = ctx
    _bring_target_front(hwnd)
    result = exec_scroll(ox + x, oy + y, delta_x, delta_y)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 滚动失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已从 ({x},{y}) 滚动")]


def tool_press_key(key: str) -> list[types.TextContent]:
    result = exec_press_key(key)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 按键失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 按键: {key}")]


def tool_switch_window(title: str) -> list[types.TextContent]:
    """切换到标题包含指定文字的窗口。多候选时返回列表让 Agent 选。"""
    try:
        import uiautomation as uia
        matches = []
        for child in uia.GetRootControl().GetChildren():
            try:
                name = child.Name
                if name and title.lower() in name.lower():
                    matches.append((name, child))
            except Exception:
                continue
        if not matches:
            return [types.TextContent(type="text", text=f"❌ 未找到窗口: {title}")]
        if len(matches) == 1:
            name, child = matches[0]
            child.SetActive()
            child.SetFocus()
            return [types.TextContent(type="text", text=f"✅ 已切换到: {name}")]
        # 多个候选
        names = [m[0] for m in matches]
        msg = (f"找到 {len(matches)} 个匹配窗口，请从以下标题中选一个:\n"
               + "\n".join(f"  - \"{n}\"" for n in names))
        return [types.TextContent(type="text", text=msg)]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"❌ 切换失败: {exc}")]


def tool_list_windows(limit: int = 20) -> list[types.TextContent]:
    try:
        import uiautomation as uia
        seen = set()
        titles = []
        for child in uia.GetRootControl().GetChildren():
            try:
                name = child.Name
                if name and name.strip() and name not in seen:
                    seen.add(name)
                    titles.append(name)
            except Exception:
                continue
            if len(titles) >= limit:
                break
        text = f"当前窗口列表 (前 {len(titles)} 个):\n"
        text += "\n".join(f"  - \"{t}\"" for t in titles)
        return [types.TextContent(type="text", text=text)]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"❌ 获取窗口列表失败: {exc}")]


async def tool_wait(ms: int) -> list[types.TextContent]:
    await asyncio.sleep(ms / 1000.0)
    return [types.TextContent(type="text", text=f"✅ 等待 {ms}ms")]


def tool_hold_key(key: str) -> list[types.TextContent]:
    result = exec_hold_key(key)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 按键失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已按住: {key}")]


def tool_release_key(key: str) -> list[types.TextContent]:
    result = exec_release_key(key)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 释放失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已释放: {key}")]


# ---------------------------------------------------------------------------
# 操作日志
# ---------------------------------------------------------------------------

_OP_LOG = logging.getLogger("desktop.ops")
_OP_LOG.setLevel(logging.INFO)
if not _OP_LOG.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s | %(name)s | %(message)s"))
    _OP_LOG.addHandler(_h)


def _log_call(tool_name: str, args: dict, result: str) -> None:
    """记录每次工具调用。"""
    arg_preview = ", ".join(f"{k}={v}" for k, v in args.items())
    _OP_LOG.info("[%s] %s → %s", tool_name, arg_preview, result[:60])


# ---------------------------------------------------------------------------
# 紧急终止快捷键（Ctrl+Alt+K）
# ---------------------------------------------------------------------------

def _register_kill_switch() -> None:
    """注册全局热键 Ctrl+Alt+K 紧急终止 MCP Server。"""
    try:
        import ctypes
        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002
        VK_K = 0x4B  # K 键
        ctypes.windll.user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT, VK_K)
        _run_kill_listener()
    except Exception as exc:
        logger.warning("紧急终止快捷键注册失败: %s", exc)


def _run_kill_listener() -> None:
    """在后台线程监听热键消息。"""
    import threading
    def _listen():
        try:
            import ctypes
            import time
            msg = ctypes.wintypes.MSG()
            while True:
                # PeekMessageW 非阻塞，每 50ms 轮询
                ret = ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
                if ret:
                    if msg.message == 0x0312:  # WM_HOTKEY
                        logger.warning("⚠️ 紧急终止: Ctrl+Alt+K 触发")
                        from .executor import _cleanup_held_keys
                        _cleanup_held_keys()
                        import sys
                        sys.stdout.flush()
                        import os
                        os._exit(0)
                    ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                    ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.05)
        except Exception:
            pass
    t = threading.Thread(target=_listen, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# 启动自检
# ---------------------------------------------------------------------------

def _startup_checks() -> None:
    """打印当前系统环境信息，帮助排查问题。"""
    info = []
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetDesktopWindow()
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        info.append(f"DPI: {dpi} ({dpi / 96.0:.0%})")
    except Exception:
        info.append("DPI: unknown")

    try:
        monitor_count = ctypes.windll.user32.GetSystemMetrics(80)  # SM_CMONITORS
        info.append(f"显示器: {monitor_count}")
    except Exception:
        info.append("显示器: unknown")

    import ctypes
    VIRTUAL_LEFT = ctypes.windll.user32.GetSystemMetrics(76)
    VIRTUAL_TOP = ctypes.windll.user32.GetSystemMetrics(77)
    VIRTUAL_WIDTH = ctypes.windll.user32.GetSystemMetrics(78)
    VIRTUAL_HEIGHT = ctypes.windll.user32.GetSystemMetrics(79)
    info.append(f"虚拟桌面: ({VIRTUAL_LEFT},{VIRTUAL_TOP}) {VIRTUAL_WIDTH}x{VIRTUAL_HEIGHT}")

    uia_ok = _import_uia() is not None
    info.append(f"UIA: {'可用' if uia_ok else '不可用'}")

    dxcam_ok = True
    try:
        import dxcam
    except Exception:
        dxcam_ok = False
    info.append(f"DXcam: {'可用' if dxcam_ok else '不可用'}")

    print(f"+------------------------------------------")
    print(f"| desktop-tools v{__version__}")
    for line in info:
        print(f"| {line}")
    print(f"| 紧急终止: Ctrl+Alt+K")
    print(f"+------------------------------------------")
    logger.info("启动自检完成: %s", "; ".join(info))


# ---------------------------------------------------------------------------
# find_by_name 工具
# ---------------------------------------------------------------------------

def tool_find_by_name(name: str, role: str = "") -> list[types.TextContent]:
    """在当前窗口按名称查找控件，返回窗口相对坐标（以客户区为原点）。"""
    from .windows_api import find_element_by_name, get_client_rect, get_active_window
    win = get_active_window()
    if win is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    cr = get_client_rect(win.hwnd)
    ox = cr['client_left'] if cr else win.rect.left
    oy = cr['client_top'] if cr else win.rect.top
    elem = find_element_by_name(win.title, name, role or None)
    if elem is None:
        return [types.TextContent(type="text", text=f"❌ 未找到控件: {name}")]
    rx = elem.rect.center_x - ox
    ry = elem.rect.center_y - oy
    return [types.TextContent(
        type="text",
        text=f"✅ 找到 [{elem.role}] \"{elem.name}\" @ 窗口相对坐标 ({rx}, {ry})"
    )]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    _startup_checks()
    _register_kill_switch()
    try:
        from mcp.server import Server
        from mcp.server.models import InitializationOptions
        import mcp.server.stdio
        app = Server("desktop")

        @app.list_tools()
        async def list_tools() -> list[types.Tool]:
            return [
                types.Tool(name="get_snapshot", description="获取当前激活窗口完整快照。返回窗口信息+控件列表+截图（Agent可直接查看）。截图使用D3D后端，被遮挡也能截取。Agent根据截图和控件信息决定下一步操作的坐标。", inputSchema={"type":"object","properties":{}}),
                types.Tool(name="click", description="在窗口相对坐标(x,y)处点击左键。(0,0)=窗口左上角。", inputSchema={"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"}},"required":["x","y"]}),
                types.Tool(name="double_click", description="在窗口相对坐标(x,y)处双击。", inputSchema={"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"}},"required":["x","y"]}),
                types.Tool(name="move_to", description="移动鼠标到窗口相对坐标(x,y)处（不点击）。", inputSchema={"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"}},"required":["x","y"]}),
                types.Tool(name="type_text", description="在窗口相对坐标(x,y)处点击后输入文字。", inputSchema={"type":"object","properties":{"text":{"type":"string"},"x":{"type":"integer"},"y":{"type":"integer"}},"required":["text","x","y"]}),
                types.Tool(name="press_key", description="发送键盘按键或快捷键。支持: Enter/Escape/Tab/方向键, ctrl+c/v/a/z, Alt+Tab, Shift+F10, F1-F12", inputSchema={"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}),
                types.Tool(name="hold_key", description="按住一个键不放。之后需调用release_key释放。用于Ctrl+点击等组合操作。", inputSchema={"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}),
                types.Tool(name="release_key", description="释放之前按住的键。", inputSchema={"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}),
                types.Tool(name="switch_window", description="切换到标题包含指定文字的窗口。如'微信'、'Chrome'。多候选时返回列表。", inputSchema={"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}),
                types.Tool(name="list_windows", description="列出当前所有顶层窗口标题。", inputSchema={"type":"object","properties":{}}),
                types.Tool(name="scroll", description="从窗口相对坐标(x,y)处滚动。delta_y>0向下,<0向上。", inputSchema={"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"},"delta_x":{"type":"integer","default":0},"delta_y":{"type":"integer","default":5}},"required":["x","y"]}),
                types.Tool(name="find_by_name", description="按名称在当前窗口查找控件，返回窗口相对坐标(x,y)和角色，配合click使用。仅对暴露UIA的应用有效。", inputSchema={"type":"object","properties":{"name":{"type":"string"},"role":{"type":"string","default":""}},"required":["name"]}),
                types.Tool(name="wait", description="异步等待指定毫秒数。", inputSchema={"type":"object","properties":{"ms":{"type":"integer"}},"required":["ms"]}),
            ]

        @app.call_tool()
        async def call_tool(name: str, arguments: dict) -> list:
            _log_call(name, arguments, "started")
            fns = {
                "get_snapshot": lambda: tool_get_snapshot(),
                "click": lambda: tool_click(arguments["x"], arguments["y"]),
                "double_click": lambda: tool_double_click(arguments["x"], arguments["y"]),
                "move_to": lambda: tool_move_to(arguments["x"], arguments["y"]),
                "type_text": lambda: tool_type_text(arguments["text"], arguments["x"], arguments["y"]),
                "press_key": lambda: tool_press_key(arguments["key"]),
                "hold_key": lambda: tool_hold_key(arguments["key"]),
                "release_key": lambda: tool_release_key(arguments["key"]),
                "switch_window": lambda: tool_switch_window(arguments["title"]),
                "list_windows": lambda: tool_list_windows(),
                "scroll": lambda: tool_scroll(arguments["x"], arguments["y"], arguments.get("delta_x", 0), arguments.get("delta_y", 5)),
                "find_by_name": lambda: tool_find_by_name(arguments["name"], arguments.get("role", "")),
                "wait": lambda: tool_wait(arguments["ms"]),
            }
            fn = fns.get(name)
            if fn is None:
                raise ValueError(f"未知工具: {name}")
            r = fn()
            if name == "wait":
                r = await r
            # 记录完成状态
            result_text = r[0].text[:80] if r and hasattr(r[0], 'text') else str(r)[:80]
            _log_call(name, arguments, result_text)
            return r

        async def run():
            async with mcp.server.stdio.stdio_server() as (rs, ws):
                await app.run(rs, ws, InitializationOptions(
                    server_name="desktop", server_version=__version__,
                ))

        asyncio.run(run())
    except ImportError as exc:
        logger.error("启动失败: pip install mcp"); sys.exit(1)
    except Exception as exc:
        logger.error("MCP Server 异常退出: %s", exc); sys.exit(1)


if __name__ == "__main__":
    main()
