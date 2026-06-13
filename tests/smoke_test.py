"""Smoke test — 验证核心链路无崩溃。

运行方式:
  python tests/smoke_test.py

测试内容:
  1. 全模块导入
  2. get_snapshot 返回格式
  3. click 执行
  4. type_text 执行
  5. press_key 执行
  6. list_windows 返回
  7. 版本号一致性
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

errors = []


def check(desc: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  ✅ {desc}")
    else:
        print(f"  ❌ {desc}: {detail}")
        errors.append(desc)


print("=" * 50)
print("smoke test — reasonix-desktop-tools")
print("=" * 50)

# 1. 版本一致性
print("\n1. 版本号检查")
from reasonix_desktop_tools import __version__ as v_init
check("__init__.py 版本非空", bool(v_init))
check("版本格式 x.y.z", len(v_init.split(".")) == 3)

# 2. 模块导入
print("\n2. 模块导入")
from reasonix_desktop_tools.mcp_server import (
    tool_get_snapshot, tool_click, tool_type_text,
    tool_press_key, tool_list_windows, tool_switch_window,
)
check("所有工具函数导入成功", True)

from reasonix_desktop_tools.executor import (
    click, type_text, press_key, scroll, hold_key, release_key, bring_to_front,
)
check("所有执行器函数导入成功", True)

from reasonix_desktop_tools.screenshot import capture_window, capture_full_screen
check("截图模块导入成功", True)

from reasonix_desktop_tools.windows_api import (
    get_active_window, list_active_window_elements, find_window,
)
check("Windows API 导入成功", True)

# 3. 截图
print("\n3. 截图功能")
img = capture_full_screen(quality=85)
check("全屏截图返回非空", img is not None)
if img:
    b64, mime = img
    check("截图返回 (base64, mime)", bool(b64) and mime in ("image/jpeg", "image/png"))
    check(f"MIME 类型: {mime}", mime in ("image/jpeg", "image/png"))

# 4. get_snapshot 返回格式
print("\n4. get_snapshot 格式")
result = tool_get_snapshot()
check("返回 list", isinstance(result, list))
check("至少 1 个 content 块", len(result) >= 1)
if result:
    first = result[0]
    check("第一个 content 是 TextContent", first.type == "text")
    check("TextContent 非空", bool(first.text))
if len(result) >= 2:
    second = result[1]
    check("第二个 content 是 ImageContent", second.type == "image")

# 5. click 执行
print("\n5. click 执行")
r = click(100, 200)
check("click 应成功", r.success, r.message)

# 6. type_text 执行
print("\n6. type_text 执行")
r = type_text(200, 300, "test")
check("type_text 应成功", r.success, r.message)

# 7. press_key 执行
print("\n7. press_key 执行")
for key in ["Enter", "Escape", "ctrl+c"]:
    r = press_key(key)
    check(f"press_key({key})", r.success, r.message)

# 8. scroll 执行
print("\n8. scroll 执行")
r = scroll(100, 200, 0, 5)
check("scroll 应成功", r.success, r.message)

# 9. hold_key / release_key
print("\n9. hold_key / release_key")
r = hold_key("Control")
check("hold_key(Control)", r.success, r.message)
r = release_key("Control")
check("release_key(Control)", r.success, r.message)

# 10. list_windows
print("\n10. list_windows")
r = tool_list_windows(limit=3)
check("list_windows 返回文本", bool(r) and r[0].type == "text")

# 11. UIA (可能返回 0 控件，但不应崩溃)
print("\n11. UIA 窗口枚举")
elems = list_active_window_elements()
check("UIA 遍历不崩溃", True)

# 12. bring_to_front
print("\n12. bring_to_front")
try:
    win = get_active_window()
    if win:
        bring_to_front(win.hwnd)
        check("bring_to_front 不崩溃", True)
    else:
        check("bring_to_front 无激活窗口可测", True)
except Exception as e:
    check("bring_to_front 不崩溃", False, str(e))

# 汇总
print(f"\n{'=' * 50}")
if errors:
    print(f"❌ 失败: {len(errors)} 项")
    for e in errors:
        print(f"     - {e}")
    sys.exit(1)
else:
    print(f"✅ 全部通过 ({15 - len(errors)}/15)")
