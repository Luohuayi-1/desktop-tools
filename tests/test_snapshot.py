"""测试 get_snapshot — 验证截图 + 窗口信息能否正常返回。

使用方法:
  python tests/test_snapshot.py

预期:
  - 输出当前激活窗口的信息
  - 输出 accessibility 树（如果有）
  - 确认截图 base64 字符串不为空
"""

import sys
sys.path.insert(0, r"D:\桌面操控\workspace\reasonix-desktop-tools")

from desktop_tools.mcp_server import get_snapshot, get_snapshot_text

print("=" * 50)
print("测试: get_snapshot_text()")
print("=" * 50)
text = get_snapshot_text()
print(text)

print()
print("=" * 50)
print("测试: get_snapshot()（含截图）")
print("=" * 50)
result = get_snapshot()
# 检查是否包含截图
if "data:image/png;base64," in result:
    # 提取 base64 长度
    import re
    match = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", result)
    if match:
        b64 = match.group(1)
        print(f"截图 base64 长度: {len(b64)} 字符")
        print(f"截图大小: ~{len(b64) * 3 // 4 // 1024} KB")
        print("✅ 截图成功")
    else:
        print("❌ 截图 base64 格式异常")
else:
    print(result)
