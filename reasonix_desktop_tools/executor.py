"""Windows 桌面动作执行层。

封装鼠标点击和键盘输入的实际操作系统调用。
平台限制: Windows only。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    success: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Windows API 类型定义
# ---------------------------------------------------------------------------

# 鼠标事件标志
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800

# 按键事件标志
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# SendInput 相关类型
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]


# ---------------------------------------------------------------------------
# user32.dll 函数绑定
# ---------------------------------------------------------------------------

_user32 = ctypes.windll.user32

_SetCursorPos = _user32.SetCursorPos
_SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_SetCursorPos.restype = ctypes.c_bool

_GetCursorPos = _user32.GetCursorPos
_GetCursorPos.argtypes = [ctypes.POINTER(ctypes.wintypes.POINT)]
_GetCursorPos.restype = ctypes.c_bool

_SendInput = _user32.SendInput
_SendInput.argtypes = [
    ctypes.c_uint,
    ctypes.POINTER(INPUT),
    ctypes.c_int,
]
_SendInput.restype = ctypes.c_uint

# 虚拟屏幕尺寸（多显示器聚合）
# SystemMetrics indices
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_VIRTUAL_LEFT = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
_VIRTUAL_TOP = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
_VIRTUAL_WIDTH = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
_VIRTUAL_HEIGHT = _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def click(x: int, y: int, button: str = "left") -> ActionResult:
    """移动鼠标到指定坐标并点击。

    参数:
        x, y: 屏幕坐标
        button: "left" / "right"
    """
    try:
        _move_to(x, y)
        time.sleep(0.05)

        if button == "left":
            ok = _send_mouse_input(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_LEFTUP)
        elif button == "right":
            ok = _send_mouse_input(MOUSEEVENTF_RIGHTDOWN | MOUSEEVENTF_RIGHTUP)
        else:
            return ActionResult(False, f"不支持的按键: {button}")

        if not ok:
            return ActionResult(False, "SendInput 失败（事件被拦截或权限不足）")

        logger.debug("click(%d, %d) %s", x, y, button)
        return ActionResult(True)
    except Exception as exc:
        logger.error("click 失败: %s", exc)
        return ActionResult(False, str(exc))


def double_click(x: int, y: int) -> ActionResult:
    """双击。"""
    for _ in range(2):
        result = click(x, y)
        if not result.success:
            return result
        time.sleep(0.03)
    return ActionResult(True)


def type_text(x: int, y: int, text: str) -> ActionResult:
    """点击指定位置后输入文本。"""
    try:
        # 先点击定位输入框
        click_result = click(x, y)
        if not click_result.success:
            return click_result

        time.sleep(0.1)

        # 逐个字符输入
        for i, ch in enumerate(text):
            if not _type_char(ch):
                logger.error("type_text 第 %d 个字符输入失败: %r", i, ch)
                return ActionResult(False, f"第 {i+1} 个字符输入失败")
            time.sleep(0.02)

        logger.debug("type_text(%d, %d, %s)", x, y, repr(text))
        return ActionResult(True)
    except Exception as exc:
        logger.error("type_text 失败: %s", exc)
        return ActionResult(False, str(exc))


def move_to(x: int, y: int) -> ActionResult:
    """仅移动鼠标到坐标。"""
    try:
        _move_to(x, y)
        return ActionResult(True)
    except Exception as exc:
        return ActionResult(False, str(exc))


def get_cursor_position() -> tuple[int, int]:
    """获取当前鼠标坐标。"""
    point = ctypes.wintypes.POINT()
    if _GetCursorPos(ctypes.byref(point)):
        return (point.x, point.y)
    return (0, 0)


# ---------------------------------------------------------------------------
# 新增: 键盘快捷键
# ---------------------------------------------------------------------------

# 按键名称 → 虚拟键码映射
_KEY_MAP = {
    "Enter": 0x0D,
    "Return": 0x0D,
    "Escape": 0x1B,
    "Esc": 0x1B,
    "Tab": 0x09,
    "Backspace": 0x08,
    "Delete": 0x2E,
    "Del": 0x2E,
    "Insert": 0x2D,
    "Home": 0x24,
    "End": 0x23,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "Space": 0x20,
    "ArrowUp": 0x26,
    "Up": 0x26,
    "ArrowDown": 0x28,
    "Down": 0x28,
    "ArrowLeft": 0x25,
    "Left": 0x25,
    "ArrowRight": 0x27,
    "Right": 0x27,
    "Shift": 0x10,
    "Control": 0x11,
    "Ctrl": 0x11,
    "ctrl": 0x11,
    "Alt": 0x12,
    "Menu": 0x12,
    "alt": 0x12,
    "Shift": 0x10,
    "shift": 0x10,
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}

# 单个字符 → vk 映射（用于 ctrl+c 等组合中的字母）
def _char_to_vk(ch: str) -> int:
    if len(ch) != 1:
        return _KEY_MAP.get(ch, 0)
    if 'a' <= ch <= 'z':
        return ord(ch.upper())
    if 'A' <= ch <= 'Z':
        return ord(ch)
    if '0' <= ch <= '9':
        return ord(ch)
    return _KEY_MAP.get(ch, 0)


def hold_key(key: str) -> ActionResult:
    """按住一个键不放（不释放）。用于组合操作如 ctrl+click。

    之后必须调用 release_key() 释放。
    """
    try:
        vk = _char_to_vk(key)
        if vk == 0:
            vk = _KEY_MAP.get(key, 0)
        if vk == 0:
            return ActionResult(False, f"未知按键: {key}")
        if not _send_keyboard_input(vk, 0, 0):
            return ActionResult(False, "SendInput 按键失败")
        logger.debug("hold_key(%s)", key)
        return ActionResult(True)
    except Exception as exc:
        return ActionResult(False, str(exc))


def release_key(key: str) -> ActionResult:
    """释放一个之前按住的键。"""
    try:
        vk = _char_to_vk(key)
        if vk == 0:
            vk = _KEY_MAP.get(key, 0)
        if vk == 0:
            return ActionResult(False, f"未知按键: {key}")
        if not _send_keyboard_input(vk, 0, KEYEVENTF_KEYUP):
            return ActionResult(False, "SendInput 释放失败")
        logger.debug("release_key(%s)", key)
        return ActionResult(True)
    except Exception as exc:
        return ActionResult(False, str(exc))


def press_key(key: str) -> ActionResult:
    """发送键盘按键或快捷键。

    支持格式:
      - 单键: "Enter", "Escape", "Tab", "F5"
      - 组合: "ctrl+c", "Alt+Tab", "shift+F10", "ctrl+shift+Esc"
    """
    try:
        parts = key.split("+")
        mods = []
        main_key = ""

        for p in parts:
            p = p.strip()
            lower = p.lower()
            if lower in ("ctrl", "control"):
                mods.append(0x11)
            elif lower in ("alt", "menu"):
                mods.append(0x12)
            elif lower in ("shift",):
                mods.append(0x10)
            elif lower in ("win", "windows", "meta"):
                mods.append(0x5B)
            else:
                main_key = p

        if main_key:
            vk = _char_to_vk(main_key)
            if vk == 0:
                # 尝试查找特殊键
                vk = _KEY_MAP.get(main_key, 0)
                if vk == 0:
                    return ActionResult(False, f"未知按键: {main_key}")
        else:
            # 纯修饰键
            vk = 0

        # 按下全部修饰键
        for mod in mods:
            if not _send_keyboard_input(mod, 0, 0):
                return ActionResult(False, f"修饰键 {mod:#x} 按下失败")

        if vk:
            if not _send_keyboard_input(vk, 0, 0):
                return ActionResult(False, f"主键 {vk:#x} 按下失败")
            time.sleep(0.03)
            if not _send_keyboard_input(vk, 0, KEYEVENTF_KEYUP):
                return ActionResult(False, f"主键 {vk:#x} 释放失败")

        # 释放全部修饰键
        for mod in reversed(mods):
            _send_keyboard_input(mod, 0, KEYEVENTF_KEYUP)  # 释放失败不阻断

        logger.debug("press_key(%s)", key)
        return ActionResult(True)
    except Exception as exc:
        logger.error("press_key 失败: %s", exc)
        return ActionResult(False, str(exc))


# ---------------------------------------------------------------------------
# 新增: 滚动
# ---------------------------------------------------------------------------

def scroll(x: int, y: int, delta_x: int = 0, delta_y: int = 2) -> ActionResult:
    """从指定坐标处滚动鼠标滚轮。

    参数:
        x, y: 屏幕坐标
        delta_x: 水平滚动（正数向右），单位"咔哒"
        delta_y: 垂直滚动（正数向下），单位"咔哒"
    """
    try:
        _move_to(x, y)
        time.sleep(0.05)

        if delta_y:
            # 垂直滚轮: WHEEL_DELTA = 120，一个咔哒 = 120
            amount = -delta_y * 120  # 负号: 向下为正
            _send_mouse_wheel(amount)

        if delta_x:
            amount_x = delta_x * 120
            _send_mouse_hwheel(amount_x)

        logger.debug("scroll(%d, %d, dx=%d, dy=%d)", x, y, delta_x, delta_y)
        return ActionResult(True)
    except Exception as exc:
        logger.error("scroll 失败: %s", exc)
        return ActionResult(False, str(exc))


def _send_mouse_wheel(amount: int) -> bool:
    """发送垂直滚轮事件。返回是否成功。"""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = 0
    inp.union.mi.dy = 0
    inp.union.mi.mouseData = amount
    inp.union.mi.dwFlags = MOUSEEVENTF_WHEEL
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    result = _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    return result == 1


def _send_mouse_hwheel(amount: int) -> bool:
    """发送水平滚轮事件。返回是否成功。"""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = 0
    inp.union.mi.dy = 0
    inp.union.mi.mouseData = amount
    inp.union.mi.dwFlags = 0x1000  # MOUSEEVENTF_HWHEEL
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    result = _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    return result == 1


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------

def _move_to(x: int, y: int) -> None:
    """移动鼠标到绝对屏幕坐标。"""
    _SetCursorPos(x, y)


def _send_mouse_input(flags: int) -> bool:
    """发送鼠标输入事件。返回是否成功 (True=插入1个事件)。"""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = 0
    inp.union.mi.dy = 0
    inp.union.mi.mouseData = 0
    inp.union.mi.dwFlags = flags
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))

    result = _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    return result == 1


def _type_char(ch: str) -> bool:
    """通过 SendInput 输入一个字符。返回是否成功。"""
    if ch == "\n":
        ok1 = _send_keyboard_input(0x0D, 0, KEYEVENTF_KEYDOWN)
        ok2 = _send_keyboard_input(0x0D, 0, KEYEVENTF_KEYUP)
        return ok1 and ok2

    scan = ord(ch)
    ok1 = _send_keyboard_input(0, scan, KEYEVENTF_UNICODE | KEYEVENTF_KEYDOWN)
    ok2 = _send_keyboard_input(0, scan, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
    return ok1 and ok2


def _send_keyboard_input(wVk: int, wScan: int, flags: int) -> bool:
    """发送键盘输入事件。返回是否成功。"""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = wVk
    inp.union.ki.wScan = wScan
    inp.union.ki.dwFlags = flags
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))

    result = _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    return result == 1
