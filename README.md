# reasonix-desktop-tools v0.3

MCP Server for Windows desktop control. Works with **Claude Codex**, **Cline**, **Cursor**, **Windsurf**, and any MCP-compatible Agent.

## 安装

```bash
pip install git+https://github.com/Luohuayi-1/desktop-tools.git
```

## 注册到 Codex

```bash
claude mcp add --transport stdio --scope project desktop ^
  -- python -m reasonix_desktop_tools.mcp_server
```

## 注册到 Cline

在 `cline.json` 中添加：

```json
{
  "mcpServers": {
    "desktop": {
      "command": "python",
      "args": ["-m", "reasonix_desktop_tools.mcp_server"]
    }
  }
}
```

## 工具（12 个）

| 工具 | 参数 | 说明 |
|---|---|---|
| `get_snapshot` | 无 | 窗口信息 + 控件树 + 截图（D3D 后端，被遮挡也能截取） |
| `click` | x, y | 窗口相对坐标左键点击 (0,0)=窗口左上角 |
| `double_click` | x, y | 窗口相对坐标双击 |
| `move_to` | x, y | 移动鼠标到窗口相对坐标 |
| `type_text` | text, x, y | 点击目标坐标后输入文字 |
| `press_key` | key | 键盘快捷键：Enter, Escape, ctrl+c, Alt+Tab 等 |
| `hold_key` | key | 按住键不放（配合 click 实现 Ctrl+点击等多选操作） |
| `release_key` | key | 释放之前按住的键 |
| `switch_window` | title | 切换到标题包含指定文字的窗口（多候选时返回列表） |
| `list_windows` | 无 | 列出所有顶层窗口标题（自动去重） |
| `scroll` | x, y, dx, dy | 从窗口相对坐标处滚动滚轮 |
| `wait` | ms | 异步等待（不阻塞其他请求） |

## 安全

- **紧急终止**: 按 `Ctrl+Alt+K` 立即终止 MCP Server
- **操作日志**: 所有工具调用记录在 `desktop.ops` 日志中
- **窗口激活**: 点击/输入前自动激活目标窗口

## 启动自检

启动时打印系统环境信息：

```
+------------------------------------------
| reasonix-desktop-tools v0.3
| DPI: 144 (150%)
| 显示器: 2
| 虚拟桌面: (0,0) 3840x2160
| UIA: 可用
| DXcam: 可用
| 紧急终止: Ctrl+Alt+K
+------------------------------------------
```

## 设计思路

Agent 通过 `get_snapshot` 获取截图和控件信息，自行分析界面布局，通过 `click` 和 `type_text` 在窗口相对坐标上操作。

- 截图使用 DXcam（DirectX 后端），即使窗口被遮挡也能截取
- UIA 控件信息自动采集，遍历超时 2 秒
- 每次点击/输入前自动激活目标窗口
- `click` 使用 SendInput ABSOLUTE 模式一次性完成移动+点击

## 依赖

- Windows 10 1809+
- Python 3.10 ~ 3.12
