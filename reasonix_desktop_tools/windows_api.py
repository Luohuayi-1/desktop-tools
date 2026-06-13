"""Windows UIAutomation 封装层。

提供三个核心能力：
  1. find_window → 找到目标窗口
  2. find_element_by_name → 在窗口内按名称找控件
  3. get_active_window → 获取当前激活窗口
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> int:
        return (self.left + self.right) // 2

    @property
    def center_y(self) -> int:
        return (self.top + self.bottom) // 2

    def __repr__(self) -> str:
        return f"Rect({self.left}, {self.top}, {self.right}, {self.bottom})"


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    rect: Rect
    is_active: bool = False


@dataclass
class ElementInfo:
    name: str
    role: str
    rect: Rect
    is_enabled: bool = True


# ---------------------------------------------------------------------------
# UIA 工具函数
# ---------------------------------------------------------------------------

def _import_uia() -> Optional[object]:
    """延迟导入 uiautomation，非 Windows 环境返回 None。"""
    try:
        import uiautomation as uia
        return uia
    except ImportError:
        logger.warning("uiautomation 不可用（仅 Windows 支持）")
        return None
    except Exception as exc:
        logger.warning("加载 uiautomation 失败: %s", exc)
        return None


def find_window(title_match: str | None = None,
                process_name: str | None = None) -> Optional[WindowInfo]:
    """按窗口标题或进程名查找窗口。

    参数:
        title_match: 窗口标题包含的子串（大小写不敏感）
        process_name: 进程名，如 "WeChat.exe"

    返回第一个匹配的窗口，未找到返回 None。
    """
    uia = _import_uia()
    if uia is None:
        return None

    for w in uia.GetRootControl().GetChildren():
        try:
            hwnd = w.NativeWindowHandle
            title = w.Name or ""
            rect = w.BoundingRectangle
            try:
                proc_name = w.GetProcessName() or ""
            except Exception:
                proc_name = ""

            if title_match and title_match.lower() not in title.lower():
                continue
            if process_name and process_name.lower() != proc_name.lower():
                continue

            return WindowInfo(
                hwnd=hwnd,
                title=title,
                process_name=proc_name,
                rect=Rect(
                    left=int(rect.left),
                    top=int(rect.top),
                    right=int(rect.right),
                    bottom=int(rect.bottom),
                ),
            )
        except Exception:
            continue

    return None


def get_active_window() -> Optional[WindowInfo]:
    """获取当前激活的窗口。"""
    uia = _import_uia()
    if uia is None:
        return None

    try:
        control = uia.GetFocusedControl()
        while control:
            try:
                hwnd = control.NativeWindowHandle
                if hwnd and hwnd > 0:
                    rect = control.BoundingRectangle
                    title = control.Name or ""
                    try:
                        proc_name = control.GetProcessName() or ""
                    except Exception:
                        proc_name = ""
                    return WindowInfo(
                        hwnd=hwnd,
                        title=title,
                        process_name=proc_name,
                        rect=Rect(
                            left=int(rect.left),
                            top=int(rect.top),
                            right=int(rect.right),
                            bottom=int(rect.bottom),
                        ),
                        is_active=True,
                    )
            except Exception:
                pass
            control = control.GetParentControl()
    except Exception:
        pass

    return None


def find_element_by_name(window_title: str | None,
                          element_name: str,
                          role: str | None = None) -> Optional[ElementInfo]:
    """在指定窗口中按名称查找 UIA 控件。

    参数:
        window_title: 窗口标题（传入 None 表示在当前激活窗口查找）
        element_name: 控件名称匹配子串
        role: 控件角色过滤，如 "Edit"、"Button"、"ListItem"

    返回第一个匹配的控件信息，未找到返回 None。
    """
    uia = _import_uia()
    if uia is None:
        return None

    # 角色类型对应的 int 值
    role_type_map = {
        "Edit": 50004,
        "Button": 50000,
        "ListItem": 50007,
        "List": 50008,
        "Document": 50036,
        "ComboBox": 50036,
        "TabItem": 50037,
        "MenuItem": 50043,
    }
    target_role = role_type_map.get(role) if role else None

    # 定位目标顶层窗口
    root = uia.GetRootControl()
    target_window = None
    if window_title:
        for child in root.GetChildren():
            try:
                if child.Name and window_title.lower() in child.Name.lower():
                    target_window = child
                    break
            except Exception:
                continue
    else:
        focused = uia.GetFocusedControl()
        target_window = _find_top_level_window(focused, root)

    if target_window is None:
        return None

    # 在窗口内按名称 + 角色遍历所有后代控件
    return _find_descendant(target_window, element_name, target_role, depth=0, max_depth=10)


def _find_descendant(control: object,
                     name_match: str,
                     role_type: int | None,
                     depth: int,
                     max_depth: int) -> Optional[ElementInfo]:
    """在控件树中递归搜索匹配的控件。"""
    if depth > max_depth:
        return None

    uia = _import_uia()
    if uia is None:
        return None

    try:
        name = control.Name or ""
    except Exception:
        name = ""

    # 检查当前控件
    if name and name_match.lower() in name.lower():
        if role_type is None:
            return _to_element_info(control, name)
        try:
            if control.ControlType == role_type:
                return _to_element_info(control, name)
        except Exception:
            pass

    # 遍历子控件
    try:
        children = control.GetChildren()
    except Exception:
        return None

    for child in children:
        result = _find_descendant(child, name_match, role_type, depth + 1, max_depth)
        if result is not None:
            return result

    return None


def _to_element_info(control: object, name: str) -> ElementInfo:
    """将 UIA 控件转为 ElementInfo。"""
    rect = control.BoundingRectangle
    try:
        is_enabled = control.IsEnabled
    except Exception:
        is_enabled = True
    try:
        role = control.ControlTypeName or ""
    except Exception:
        role = ""
    return ElementInfo(
        name=name,
        role=role,
        rect=Rect(
            left=int(rect.left),
            top=int(rect.top),
            right=int(rect.right),
            bottom=int(rect.bottom),
        ),
        is_enabled=is_enabled,
    )


def list_active_window_elements(
    win_control: object = None,
) -> list[ElementInfo]:
    """列出当前激活窗口内所有可交互控件。

    参数:
        win_control: 预获取的顶层窗口 UIA 控件。传入可避免重复 GetFocusedControl。

    返回元素列表。
    如果 UIA 遍历超过 2 秒则超时返回当前已收集的控件。
    """
    uia = _import_uia()
    if uia is None:
        return []

    if win_control is None:
        try:
            focused = uia.GetFocusedControl()
        except Exception:
            return []
        root = uia.GetRootControl()
        win_control = _find_top_level_window(focused, root)
        if win_control is None:
            return []

    try:
        hwnd = win_control.NativeWindowHandle
    except Exception:
        return []
    if not hwnd:
        return []

    from ._timeout import timeout_collect
    elements: list[ElementInfo] = []
    timeout_collect(hwnd, elements, max_depth=3, max_seconds=2.0)
    return elements


def _find_top_level_window(control: object, root: object) -> object | None:
    """从任意控件向上找到顶层窗口控件（根控件的直接子控件）。"""
    if control is None:
        return None

    # 方法1: 向上找到父级为根控件的控件
    current = control
    visited = set()
    while current is not None and current != root:
        try:
            parent = current.GetParentControl()
        except Exception:
            return None
        if parent == root:
            return current
        if id(parent) in visited:
            return None
        visited.add(id(parent))
        current = parent

    # 方法2: 遍历根的子控件的包围盒是否包含聚焦控件的中心
    try:
        focused_rect = control.BoundingRectangle
        cx = (focused_rect.left + focused_rect.right) // 2
        cy = (focused_rect.top + focused_rect.bottom) // 2
        for child in root.GetChildren():
            try:
                r = child.BoundingRectangle
                if r.left <= cx <= r.right and r.top <= cy <= r.bottom:
                    if child.Name:
                        return child
            except Exception:
                continue
    except Exception:
        pass

    return None


def _walk_controls(control: object,
                   result: list[ElementInfo],
                   depth: int,
                   max_depth: int) -> None:
    """递归遍历 UIA 控件树，收集可交互控件。"""
    if depth > max_depth:
        return

    uia = _import_uia()
    if uia is None:
        return

    try:
        children = control.GetChildren()
    except Exception:
        return

    PANE_TYPE = 50033
    GROUP_TYPE = 50026
    INTERACTIVE_TYPES = {
        50000,  # ButtonControl
        50004,  # EditControl
        50008,  # ListControl
        50007,  # ListItemControl
        50036,  # ComboBoxControl
        50037,  # TabItemControl
        50043,  # MenuItemControl
        50051,  # HyperlinkControl
        50055,  # CheckBoxControl
        50056,  # RadioButtonControl
    }

    for child in children:
        try:
            name = child.Name or ""
            ctrl_type = child.ControlType
            role_name = child.ControlTypeName or str(ctrl_type)

            # 跳过无名称的容器控件
            if not name and ctrl_type in (PANE_TYPE, GROUP_TYPE):
                _walk_controls(child, result, depth + 1, max_depth)
                continue

            # 只收集可交互控件类型
            if ctrl_type in INTERACTIVE_TYPES and name:
                rect = child.BoundingRectangle
                try:
                    is_enabled = child.IsEnabled
                except Exception:
                    is_enabled = True
                result.append(ElementInfo(
                    name=name,
                    role=role_name,
                    rect=Rect(
                        left=int(rect.left),
                        top=int(rect.top),
                        right=int(rect.right),
                        bottom=int(rect.bottom),
                    ),
                    is_enabled=is_enabled,
                ))

                _walk_controls(child, result, depth + 1, max_depth)

        except Exception:
            continue
