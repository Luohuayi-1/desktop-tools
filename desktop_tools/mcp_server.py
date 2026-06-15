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
    drag as exec_drag,
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

_last_target_hwnd = 0  # 上次 switch_window/find_by_name 的目标窗口
_ctx = None  # (win, ox, oy, hwnd, win_control)，每次 _get_ctx 重新计算不跨请求缓存


def _get_ctx():
    """获取窗口上下文。优先用 _last_target_hwnd，前台窗口未变时缓存复用。"""
    global _ctx
    # 检测前台窗口
    try:
        import ctypes
        foreground = ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        foreground = 0

    hwnd = _last_target_hwnd or foreground

    # 缓存命中：同一 hwnd 且 1 秒内的缓存
    if _ctx and _ctx[3] == hwnd:
        return _ctx

    win = get_active_window()
    if win is None:
        _ctx = None
        return None

    from .windows_api import get_client_rect
    cr = get_client_rect(hwnd)
    if cr:
        ox, oy = cr['client_left'], cr['client_top']
    else:
        ox, oy = win.rect.left, win.rect.top

    # UIA 控件引用
    uia = _import_uia()
    win_control = None
    if uia:
        try:
            if hwnd:
                win_control = uia.ControlFromHandle(hwnd)
            if win_control is None:
                focused = uia.GetFocusedControl()
                root = uia.GetRootControl()
                win_control = _find_top_level_window(focused, root)
        except Exception:
            pass
    # 自洽性检查：目标窗口与前台是否一致
    focused_hwnd = foreground
    ctx_mismatch = (hwnd != focused_hwnd and hwnd == _last_target_hwnd)

    ctx = (win, ox, oy, hwnd, win_control, ctx_mismatch)
    _ctx = ctx
    return ctx

def _bring_target_front(hwnd: int) -> bool:
    """前置目标窗口。返回窗口是否有效（未被销毁）。"""
    if not hwnd:
        return False
    if not ctypes.windll.user32.IsWindow(hwnd):
        return False
    bring_to_front(hwnd)
    # 闪烁 TopMost 绕过 Windows 前台窗口防抖
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), HWND_TOPMOST,
        0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), HWND_NOTOPMOST,
        0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    # 高亮描边显示当前操作的窗口
    _highlight_window(hwnd)
    return True


def _highlight_window(hwnd: int, color: int = 0x0000FF, thickness: int = 4, duration: float = 1.5) -> None:
    """在目标窗口四周绘制红色高亮边框（overlay 分层窗口），duration 秒后自动销毁。"""
    try:
        import threading
        import ctypes
        from ctypes import wintypes

        frame = wintypes.RECT()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(hwnd), 9,
            ctypes.byref(frame), ctypes.sizeof(frame)
        )
        l, t, r, b = frame.left, frame.top, frame.right, frame.bottom
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return

        cls_name = "DTHighlight"
        mod = ctypes.windll.kernel32.GetModuleHandleW(None)
        try:
            ctypes.windll.user32.RegisterClassW(
                wintypes.WNDCLASS(
                    style=0, lpfnWndProc=ctypes.WINFUNCTYPE(
                        ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p
                    )(lambda *a: 0),
                    hInstance=mod, lpszClassName=cls_name
                )
            )
        except Exception:
            pass

        overlay = ctypes.windll.user32.CreateWindowExW(
            0x800A8,  # WS_EX_LAYERED|TRANSPARENT|TOOLWINDOW|NOACTIVATE
            cls_name, None, 0x80000000,
            l, t, w, h, None, None, mod, None
        )
        if not overlay:
            return

        ctypes.windll.user32.SetLayeredWindowAttributes(overlay, 0, 200, 2)
        ctypes.windll.user32.ShowWindow(overlay, 1)

        hdc = ctypes.windll.user32.GetDC(overlay)
        pen = ctypes.windll.gdi32.CreatePen(0, thickness, color)
        old_pen = ctypes.windll.gdi32.SelectObject(hdc, pen)
        brush = ctypes.windll.gdi32.GetStockObject(5)
        old_brush = ctypes.windll.gdi32.SelectObject(hdc, brush)
        ctypes.windll.gdi32.Rectangle(hdc, 0, 0, w, h)
        ctypes.windll.gdi32.SelectObject(hdc, old_pen)
        ctypes.windll.gdi32.SelectObject(hdc, old_brush)
        ctypes.windll.gdi32.DeleteObject(pen)
        ctypes.windll.user32.ReleaseDC(overlay, hdc)

        def _clear():
            import time
            time.sleep(duration)
            try:
                ctypes.windll.user32.PostMessageW(overlay, 0x0010, 0, 0)  # WM_CLOSE
            except Exception:
                pass

        threading.Thread(target=_clear, daemon=True).start()
        logger.debug("highlight_window(%d) overlay %dx%d %.1fs", hwnd, w, h, duration)
    except Exception as exc:
        logger.debug("highlight_window 失败: %s", exc)


def show_layout_bounds(hwnd: int, duration: float = 3.0) -> None:
    """在目标窗口上绘制所有 UIA 控件的边界框（类似 Android 显示布局边界），duration 秒后自动销毁。"""
    try:
        import threading, ctypes
        from ctypes import wintypes
        from .windows_api import get_client_rect, list_active_window_elements, ElementInfo

        cr = get_client_rect(hwnd)
        if not cr:
            return
        ox, oy = cr['client_left'], cr['client_top']
        cw, ch = cr['client_width'], cr['client_height']
        if cw <= 0 or ch <= 0:
            return

        elements = list_active_window_elements()
        if not elements:
            return

        cls_name = 'DTHLayout'
        mod = ctypes.windll.kernel32.GetModuleHandleW(None)
        try:
            ctypes.windll.user32.RegisterClassW(
                wintypes.WNDCLASS(style=0,
                    lpfnWndProc=ctypes.WINFUNCTYPE(
                        ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p
                    )(lambda *a: 0),
                    hInstance=mod, lpszClassName=cls_name)
            )
        except Exception:
            pass

        overlay = ctypes.windll.user32.CreateWindowExW(
            0x800A8, cls_name, None, 0x80000000,
            ox, oy, cw, ch, None, None, mod, None
        )
        if not overlay:
            return

        ctypes.windll.user32.SetLayeredWindowAttributes(overlay, 0, 160, 2)
        ctypes.windll.user32.ShowWindow(overlay, 1)
        hdc = ctypes.windll.user32.GetDC(overlay)

        colors = [0xFF0000, 0x00FF00, 0x0000FF, 0xFF00FF, 0x00FFFF, 0xFFFF00, 0xFF8800, 0x88FF00, 0x0088FF]
        for i, elem in enumerate(elements):
            color = colors[i % len(colors)]
            rx = elem.rect.center_x - ox - elem.rect.width // 2
            ry = elem.rect.center_y - oy - elem.rect.height // 2
            rw, rh = elem.rect.width, elem.rect.height
            if rw <= 0 or rh <= 0:
                continue
            pen = ctypes.windll.gdi32.CreatePen(0, 2, color)
            ctypes.windll.gdi32.SelectObject(hdc, pen)
            brush = ctypes.windll.gdi32.GetStockObject(5)
            ctypes.windll.gdi32.SelectObject(hdc, brush)
            ctypes.windll.gdi32.Rectangle(hdc, rx, ry, rx + rw, ry + rh)
            ctypes.windll.gdi32.DeleteObject(pen)
            try:
                ctypes.windll.gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
                ctypes.windll.user32.TextOutW(hdc, rx, ry - 14, f'{i}:{elem.name}', len(f'{i}:{elem.name}'))
            except Exception:
                pass

        ctypes.windll.user32.ReleaseDC(overlay, hdc)

        def _clear():
            import time
            time.sleep(duration)
            try:
                ctypes.windll.user32.PostMessageW(overlay, 0x0010, 0, 0)
            except Exception:
                pass
        threading.Thread(target=_clear, daemon=True).start()
    except Exception as exc:
        logger.debug('show_layout_bounds 失败: %s', exc)


def _scale_coords(hwnd: int, x: int, y: int) -> tuple[int, int]:
    """坐标透传。"""
    return (x, y)


def tool_get_snapshot() -> list[types.Content]:
    """快照：窗口信息 + 控件树 + 截图。目标与前台不一致时同时展示两者。"""
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="当前无激活窗口")]
    win, ox, oy, hwnd, win_control, ctx_mismatch = ctx

    from .windows_api import get_client_rect, get_active_window
    fg = get_active_window()
    fg_name = fg.title if fg else "?"
    parts = []
    parts.append(f"目标窗口: \"{win.title}\" (句柄 0x{hwnd:X})")
    parts.append(f"进程: {win.process_name or 'unknown'}")
    if ctx_mismatch:
        parts.append(f"⚠️ 前台窗口为「{fg_name}」，与目标不同！以下内容基于目标窗口，非前台。")
    else:
        parts.append(f"前台窗口: \"{fg_name}\"")
    _cr = get_client_rect(hwnd)
    if _cr:
        parts.append(f"窗口: {win.rect.width}x{win.rect.height}")
        parts.append(f"客户区: {_cr['client_width']}x{_cr['client_height']}  (0,0)=客户区左上角")
    else:
        parts.append(f"窗口大小: {win.rect.width} x {win.rect.height}")
    elements = list_active_window_elements(win_control=win_control)
    if elements:
        parts.append(f"\n控件 ({len(elements)} 个，可用 click_element 索引点击):")
        for i, e in enumerate(elements[:15]):
            parts.append(f"  [{i}] [{e.role}] \"{e.name}\" @ ({e.rect.center_x-ox}, {e.rect.center_y-oy})")
        if len(elements) > 15:
            parts.append(f"  ... {len(elements)-15} 个")
    else:
        parts.append("\n(无 UIA 控件，请用截图坐标估算)")
    txt = types.TextContent(type="text", text="\n".join(parts))

    cr = get_client_rect(hwnd)
    sw = cr['client_width'] if cr else win.rect.width
    sh = cr['client_height'] if cr else win.rect.height
    shot = capture_window(ox, oy, ox+sw, oy+sh, hwnd=hwnd)
    result = [txt]
    if shot:
        b, m = shot
        result.append(types.ImageContent(type="image", data=b, mimeType=m))
    if ctx_mismatch and fg and fg.hwnd:
        fcr = get_client_rect(fg.hwnd)
        if fcr:
            fshot = capture_window(fcr['client_left'], fcr['client_top'],
                                   fcr['client_left']+fcr['client_width'],
                                   fcr['client_top']+fcr['client_height'], hwnd=fg.hwnd)
            if fshot:
                bf, mf = fshot
                result.append(types.TextContent(type="text", text=f"【对比】前台「{fg_name}」截图:"))
                result.append(types.ImageContent(type="image", data=bf, mimeType=mf))
    return result


def tool_capture_screen() -> list[types.Content]:
    """截取全屏（不依赖窗口上下文）。Agent 可用此工具查看整个桌面布局，定位图标后切换到目标窗口。"""
    from .screenshot import capture_full_screen
    shot = capture_full_screen()
    if shot:
        b, m = shot
        return [types.TextContent(type="text", text="全屏截图:"), types.ImageContent(type="image", data=b, mimeType=m)]
    return [types.TextContent(type="text", text="截图失败")]


def _do_click(x: int, y: int, label: str = "点击") -> list[types.TextContent]:
    """通用点击操作（按 hwnd DPI 缩放后执行）。"""
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _, _ = ctx
    _bring_target_front(hwnd)
    sx, sy = _scale_coords(hwnd, ox + x, oy + y)
    result = exec_click(sx, sy)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ {label}失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已{label} ({x}, {y})")]


def tool_click(x: int, y: int) -> list[types.TextContent]:
    return _do_click(x, y, "点击")


def tool_click_element(index: int) -> list[types.TextContent]:
    """通过无障碍树索引点击控件（无需计算坐标）。"""
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _ = ctx
    elements = list_active_window_elements()
    if index < 0 or index >= len(elements):
        return [types.TextContent(type="text", text=f"❌ 索引 {index} 超出范围 (0-{len(elements)-1})")]
    elem = elements[index]
    sx, sy = _scale_coords(hwnd, elem.rect.center_x, elem.rect.center_y)
    result = exec_click(sx, sy)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 点击控件[{index}]失败: {result.message}")]
    name = elem.name
    return [types.TextContent(type="text", text=f"✅ 已点击[{index}] [{elem.role}] '{name}' @ ({elem.rect.center_x - ox}, {elem.rect.center_y - oy})")]


def tool_double_click(x: int, y: int) -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _, _ = ctx
    _bring_target_front(hwnd)
    sx, sy = _scale_coords(hwnd, ox + x, oy + y)
    result = exec_double_click(sx, sy)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 双击失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已双击 ({x}, {y})")]


def tool_move_to(x: int, y: int) -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _, _ = ctx
    _bring_target_front(hwnd)
    sx, sy = _scale_coords(hwnd, ox + x, oy + y)
    result = exec_move_to(sx, sy)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 移动失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已移动鼠标到 ({x}, {y})")]


def tool_type_text(text: str, x: int, y: int) -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _, _ = ctx
    _bring_target_front(hwnd)
    sx, sy = _scale_coords(hwnd, ox + x, oy + y)
    result = exec_type_text(sx, sy, text)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 输入失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已在 ({x}, {y}) 输入「{text}」")]


def tool_scroll(x: int, y: int,
                delta_x: int = 0, delta_y: int = 5) -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _, _ = ctx
    _bring_target_front(hwnd)
    sx, sy = _scale_coords(hwnd, ox + x, oy + y)
    result = exec_scroll(sx, sy, delta_x, delta_y)
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
    global _last_target_hwnd
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
            _last_target_hwnd = child.NativeWindowHandle
            child.SetActive()
            child.SetFocus()
            return [types.TextContent(type="text", text=f"✅ 已切换到: {name}")]
        # 多个候选
        names = [m[0] for m in matches]
        msg = (f"找到 {len(matches)} 个匹配窗口，请从以下标题中选一个:\n"
               + "\n".join(f"  - \"{n}\"" for n in names))
        return [types.TextContent(type="text", text=msg)]
    except Exception as exc:
        # EnumWindows 后备
        try:
            import ctypes
            from ctypes import wintypes
            results = []
            def enum_cb(hwnd, _):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                        if title.lower() in buf.value.lower():
                            results.append((buf.value, hwnd))
                return True
            ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_int)
            ctypes.windll.user32.EnumWindows(ENUMPROC(enum_cb), 0)
            if results:
                name, hw = results[0]
                _last_target_hwnd = hw
                ctypes.windll.user32.SetForegroundWindow(hw)
                return [types.TextContent(type="text", text=f"✅ 已切换到(后备): {name}")]
        except Exception:
            pass
        return [types.TextContent(type="text", text=f"❌ 切换失败: {exc}")]


def tool_launch_app(path: str, timeout: int = 10) -> list[types.TextContent]:
    """启动应用，轮询等待窗口出现。"""
    import subprocess
    import time
    try:
        proc = subprocess.Popen(path, shell=True)
        app_name = path.split(chr(92))[-1].replace('.exe', '').lower()
        for _ in range(timeout * 2):
            time.sleep(0.5)
            try:
                import uiautomation as uia
                for child in uia.GetRootControl().GetChildren():
                    try:
                        pid = child.ProcessId
                        title = child.Name or ''
                        if pid == proc.pid and title.strip():
                            global _last_target_hwnd
                            _last_target_hwnd = child.NativeWindowHandle
                            return [types.TextContent(type="text", text=f"✅ 已启动: {path}")]
                    except Exception:
                        continue
            except Exception:
                pass
        return [types.TextContent(type="text", text=f"⚠️ 已启动但未检测到窗口: {path}")]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"❌ 启动失败: {exc}")]


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


def tool_drag(from_x: int, from_y: int, to_x: int, to_y: int) -> list[types.TextContent]:
    """从窗口相对坐标拖拽到另一个坐标。"""
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 当前无激活窗口")]
    win, ox, oy, hwnd, _, _ = ctx
    _bring_target_front(hwnd)
    sx1, sy1 = _scale_coords(hwnd, ox + from_x, oy + from_y)
    sx2, sy2 = _scale_coords(hwnd, ox + to_x, oy + to_y)
    result = exec_drag(sx1, sy1, sx2, sy2)
    if not result.success:
        return [types.TextContent(type="text", text=f"❌ 拖拽失败: {result.message}")]
    return [types.TextContent(type="text", text=f"✅ 已拖拽 ({from_x},{from_y}) → ({to_x},{to_y})")]


def _show_layout() -> list[types.TextContent]:
    ctx = _get_ctx()
    if ctx is None:
        return [types.TextContent(type="text", text="❌ 无激活窗口")]
    win, ox, oy, hwnd, _, _ = ctx
    show_layout_bounds(hwnd)
    return [types.TextContent(type="text", text="✅ 布局边界已显示 (3s)")]


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
        ret = ctypes.windll.user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT, VK_K)
        if not ret:
            logger.warning("紧急终止快捷键注册失败（返回值=%d，可能被其他程序占用）", ret)
            return
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
        from mcp.server.models import InitializationOptions, ServerCapabilities
        import mcp.server.stdio
        app = Server("desktop")

        @app.list_tools()
        async def list_tools() -> list[types.Tool]:
            return [
                types.Tool(name="capture_screen", description="截取整个桌面屏幕截图，用于查看全局布局。返回 PNG 全屏截图。", inputSchema={"type":"object","properties":{}}),
                types.Tool(name="get_snapshot", description="获取当前窗口完整快照。返回含客户区尺寸和窗口尺寸的文本描述，以及JPEG截图。坐标(0,0)=客户区左上角（不含标题栏/边框）。截图已缩放到50%尺寸，点击坐标需按客户区尺寸等比换算。", inputSchema={"type":"object","properties":{}}),
                types.Tool(name="click", description="在窗口相对坐标(x,y)处点击左键。(0,0)=窗口左上角。", inputSchema={"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"}},"required":["x","y"]}),
                types.Tool(name="double_click", description="在窗口相对坐标(x,y)处双击。", inputSchema={"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"}},"required":["x","y"]}),
                types.Tool(name="move_to", description="移动鼠标到窗口相对坐标(x,y)处（不点击）。", inputSchema={"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"}},"required":["x","y"]}),
                types.Tool(name="type_text", description="在窗口相对坐标(x,y)处点击后输入文字。", inputSchema={"type":"object","properties":{"text":{"type":"string"},"x":{"type":"integer"},"y":{"type":"integer"}},"required":["text","x","y"]}),
                types.Tool(name="press_key", description="发送键盘按键或快捷键。支持: Enter/Escape/Tab/方向键, ctrl+c/v/a/z, Alt+Tab, Shift+F10, F1-F12", inputSchema={"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}),
                types.Tool(name="hold_key", description="按住一个键不放。之后需调用release_key释放。用于Ctrl+点击等组合操作。", inputSchema={"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}),
                types.Tool(name="release_key", description="释放之前按住的键。", inputSchema={"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}),
                types.Tool(name="show_layout", description="在当前窗口上绘制所有可交互控件的彩色边界框（持续3秒自动消失），用于调试控件识别准确度。", inputSchema={"type":"object","properties":{}}),
                types.Tool(name="switch_window", description="切换到标题包含指定文字的窗口。如'微信'、'Chrome'。多候选时返回列表。", inputSchema={"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}),
                types.Tool(name="list_windows", description="列出当前所有顶层窗口标题。", inputSchema={"type":"object","properties":{}}),
                types.Tool(name="launch_app", description="启动应用并等待窗口出现。参数path为exe路径或开始菜单名，timeout为等待秒数。", inputSchema={"type":"object","properties":{"path":{"type":"string"},"timeout":{"type":"integer","default":10}},"required":["path"]}),
                types.Tool(name="scroll", description="从窗口相对坐标(x,y)处滚动。delta_y>0向下,<0向上。", inputSchema={"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"},"delta_x":{"type":"integer","default":0},"delta_y":{"type":"integer","default":5}},"required":["x","y"]}),
                types.Tool(name="drag", description="从窗口相对坐标(from_x,from_y)拖拽到(to_x,to_y)。用于拖动文件/滑块/滚动条。", inputSchema={"type":"object","properties":{"from_x":{"type":"integer"},"from_y":{"type":"integer"},"to_x":{"type":"integer"},"to_y":{"type":"integer"}},"required":["from_x","from_y","to_x","to_y"]}),
                types.Tool(name="find_by_name", description="按名称在当前窗口查找控件，返回窗口相对坐标(x,y)和角色。", inputSchema={"type":"object","properties":{"name":{"type":"string"},"role":{"type":"string","default":""}},"required":["name"]}),
                types.Tool(name="click_element", description="通过无障碍树索引点击控件（get_snapshot 返回的 [0] [1] 编号）。无需手动计算坐标。", inputSchema={"type":"object","properties":{"index":{"type":"integer"}},"required":["index"]}),
                types.Tool(name="wait", description="异步等待指定毫秒数。", inputSchema={"type":"object","properties":{"ms":{"type":"integer"}},"required":["ms"]}),
            ]

        @app.call_tool()
        async def call_tool(name: str, arguments: dict) -> list:
            _log_call(name, arguments, "started")
            fns = {
                "capture_screen": lambda: tool_capture_screen(),
                "get_snapshot": lambda: tool_get_snapshot(),
                "click": lambda: tool_click(arguments["x"], arguments["y"]),
                "double_click": lambda: tool_double_click(arguments["x"], arguments["y"]),
                "move_to": lambda: tool_move_to(arguments["x"], arguments["y"]),
                "type_text": lambda: tool_type_text(arguments["text"], arguments["x"], arguments["y"]),
                "press_key": lambda: tool_press_key(arguments["key"]),
                "hold_key": lambda: tool_hold_key(arguments["key"]),
                "release_key": lambda: tool_release_key(arguments["key"]),
                "show_layout": lambda: _show_layout(),
                "switch_window": lambda: tool_switch_window(arguments["title"]),
                "list_windows": lambda: tool_list_windows(),
                "launch_app": lambda: tool_launch_app(arguments["path"], arguments.get("timeout", 10)),
                "scroll": lambda: tool_scroll(arguments["x"], arguments["y"], arguments.get("delta_x", 0), arguments.get("delta_y", 5)),
                "drag": lambda: tool_drag(arguments["from_x"], arguments["from_y"], arguments["to_x"], arguments["to_y"]),
                "click_element": lambda: tool_click_element(arguments["index"]),
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
                    capabilities=ServerCapabilities(),
                ))

        asyncio.run(run())
    except ImportError as exc:
        logger.error("启动失败: pip install mcp"); sys.exit(1)
    except Exception as exc:
        logger.error("MCP Server 异常退出: %s", exc); sys.exit(1)


if __name__ == "__main__":
    main()
