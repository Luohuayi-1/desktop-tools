# reasonix-desktop-tools

MCP Server for Windows desktop control. Works with **Claude Codex**, **Cline**, **Cursor**, **Windsurf**, and any MCP-compatible Agent.

## 安装

```bash
pip install reasonix-desktop-tools
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

## 工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `get_snapshot` | 无 | 获取当前窗口信息 + accessibility 树 + 截图（D3D 后端，可截取被遮挡窗口） |
| `click` | x: int, y: int | 窗口相对坐标点击 (0,0) = 窗口左上角 |
| `type_text` | text: str, x: int, y: int | 窗口相对坐标处输入文字 |

## 设计思路

Agent 通过 `get_snapshot` 获取截图和控件信息，自行分析界面布局，通过 `click` 和 `type_text` 在窗口相对坐标上操作。不依赖 VLM 定位，不维护持久标注。

截图使用 DXcam（DirectX 后端），即使窗口被其他窗口遮挡也能截取完整内容。

## 依赖

- Windows 10 1809+
- Python 3.10 ~ 3.12
