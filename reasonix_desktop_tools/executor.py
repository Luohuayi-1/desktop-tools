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

# 获取屏幕尺寸（用于绝对坐标转换）
_SM_CXSCREEN = _user32.GetSystemMetrics(0)
_SM_CYSCREEN = _user32.GetSystemMetrics(1)


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
            _send_mouse_input(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_LEFTUP)
        elif button == "right":
            _send_mouse_input(MOUSEEVENTF_RIGHTDOWN | MOUSEEVENTF_RIGHTUP)
        else:
            return ActionResult(False, f"不支持的按键: {button}")

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
        for ch in text:
            _type_char(ch)
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
# 内部实现
# ---------------------------------------------------------------------------

def _move_to(x: int, y: int) -> None:
    """移动鼠标到绝对屏幕坐标。"""
    _SetCursorPos(x, y)


def _send_mouse_input(flags: int) -> None:
    """发送鼠标输入事件。"""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = 0
    inp.union.mi.dy = 0
    inp.union.mi.mouseData = 0
    inp.union.mi.dwFlags = flags
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))

    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _type_char(ch: str) -> None:
    """通过 SendInput 输入一个字符（Unicode 方式）。"""
    if ch == "\n":
        # Enter 键
        _send_keyboard_input(0x0D, 0, KEYEVENTF_KEYDOWN)
        _send_keyboard_input(0x0D, 0, KEYEVENTF_KEYUP)
        return

    # Unicode 输入
    scan = ord(ch)
    _send_keyboard_input(0, scan, KEYEVENTF_UNICODE | KEYEVENTF_KEYDOWN)
    _send_keyboard_input(0, scan, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


def _send_keyboard_input(wVk: int, wScan: int, flags: int) -> None:
    """发送键盘输入事件。"""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = wVk
    inp.union.ki.wScan = wScan
    inp.union.ki.dwFlags = flags
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))

    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
