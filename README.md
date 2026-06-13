# desktop-tools v0.3

让 Agent 操控 Windows 桌面的 MCP Server。  
兼容 **Claude Codex**、**Cline**、**Cursor**、**Windsurf** 等所有支持 MCP 协议的 Agent。

## 目录

- [快速开始](#快速开始)
- [工具参考](#工具参考)
- [使用教程](#使用教程)
- [安全](#安全)
- [排障](#排障)
- [设计思路](#设计思路)
- [依赖](#依赖)

---

## 快速开始

### 安装

```bash
pip install git+https://github.com/Luohuayi-1/desktop-tools.git
```

### 启动验证

```bash
# 直接启动看自检信息
python -m reasonix_desktop_tools.mcp_server

# 输出示例:
# +------------------------------------------
# | reasonix-desktop-tools v0.3
# | DPI: 144 (150%)
# | 显示器: 2
# | 虚拟桌面: (0,0) 3840x2160
# | UIA: 可用
# | DXcam: 可用
# | 紧急终止: Ctrl+Alt+K
# +------------------------------------------
```

看到自检信息后按 Ctrl+C 退出。接下来注册到你的 Agent。

### 注册到 Claude Codex

```bash
claude mcp add --transport stdio --scope project desktop ^
  -- python -m reasonix_desktop_tools.mcp_server
```

然后在 Codex 中测试：

```
> 看一下我当前的桌面
```

### 注册到 Cline

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

### 验证是否注册成功

在 Agent 中输入：

```
> 列出当前所有窗口
```

如果返回了窗口列表（如"微信"、"Chrome"等），说明注册成功。

> **提示**：第一次使用建议先打开记事本测试——`get_snapshot` 看内容，`click` 点一下编辑区，`type_text` 输入文字，熟悉后再操作微信等复杂应用。

---

## 工具参考

### 完整工具列表

| 工具 | 参数 | Agent 拿到什么 | 典型用途 |
|---|---|---|---|
| `get_snapshot` | 无 | 窗口标题/大小 + 控件列表 + 截图（Agent 可直接看图） | Agent "看"当前界面 |
| `click` | x, y | 成功/失败消息 | 点击按钮、输入框、图标 |
| `double_click` | x, y | 成功/失败消息 | 打开文件/文件夹 |
| `move_to` | x, y | 成功/失败消息 | 触发 hover 效果 |
| `type_text` | text, x, y | 成功/失败消息 | 在输入框中打字 |
| `press_key` | key | 成功/失败消息 | 按 Enter/Escape/快捷键 |
| `hold_key` | key | 成功/失败消息 | 按住 Ctrl 准备多选 |
| `release_key` | key | 成功/失败消息 | 释放 Ctrl |
| `switch_window` | title | 成功/候选窗口列表 | 切换到微信/Chrome |
| `list_windows` | 无 | 窗口列表（自动去重） | 查看当前开了什么 |
| `scroll` | x, y, dx, dy | 成功/失败消息 | 滚动页面 |
| `wait` | ms | 成功消息 | 等待界面加载 |

### 坐标系说明

所有坐标都是 **窗口相对坐标**：

```
(0,0) = 窗口左上角
x 向右增加，y 向下增加
取值范围 = 窗口的宽度 x 高度（来自 get_snapshot 返回的窗口大小）
```

点击/输入前会自动激活目标窗口，不需要手动切换。

### press_key 支持的按键

| 分类 | 示例 |
|---|---|
| 单键 | `Enter`, `Escape`, `Tab`, `Space`, `Backspace`, `Delete` |
| 方向键 | `ArrowUp`, `ArrowDown`, `ArrowLeft`, `ArrowRight` |
| 功能键 | `F1`~`F12` |
| 修饰键+字母 | `ctrl+c`, `ctrl+v`, `ctrl+a`, `ctrl+z`, `ctrl+s` |
| 修饰键组合 | `Alt+Tab`, `Shift+F10`, `ctrl+shift+Esc` |

---

## 使用教程

### 教程 1：在记事本中输入文字

这个教程验证核心链路（截图→点击→输入）是否正常。

```
第 1 步：打开记事本（手动）
  打开 Windows 记事本，确保它在最前。

第 2 步：Agent 看界面
  → get_snapshot()
  ← 返回: 窗口标题"记事本"，大小 800x600，截图

第 3 步：Agent 点编辑区
  Agent 从截图上判断编辑区大约在 (100, 200) 处
  → click(100, 200)
  ← ✅ 已点击 (100, 200)

第 4 步：Agent 输入文字
  → type_text("Hello from AI!", 100, 200)
  ← ✅ 已输入

第 5 步：Agent 保存
  → press_key("ctrl+s")
  ← ✅ 按键: ctrl+s
```

> **预期结果**：记事本中出现文字，弹出保存对话框。如果文字没出现，说明点击坐标不准确——调整坐标后重试。

### 教程 2：用微信发消息

```
第 1 步：了解当前桌面
  → get_snapshot()
  ← 窗口信息 + 截图
  Agent 从截图中看到微信图标在右下角

第 2 步：打开微信
  → double_click(1750, 950)
  ← ✅ 已双击

第 3 步：等微信加载
  → wait(2000)
  ← ✅ 等待 2000ms

第 4 步：看微信窗口
  → get_snapshot()
  ← 截图显示微信主界面
  Agent 看到搜索框在顶部 (350, 50)，聊天列表在左侧

第 5 步：搜索联系人
  → click(350, 50)
  → type_text("张三", 350, 50)
  ← ✅ 已输入

第 6 步：等搜索结果
  → wait(1000)

第 7 步：看搜索结果
  → get_snapshot()
  截图显示"张三"出现在 (350, 150)

第 8 步：点击联系人
  → click(350, 150)

第 9 步：等聊天窗口打开
  → wait(1000)

第 10 步：看聊天窗口
  → get_snapshot()
  截图显示输入框在 (400, 650)，发送按钮在 (750, 680)

第 11 步：输入并发送
  → type_text("明天下午三点开会", 400, 650)
  → click(750, 680)
  ← ✅ 消息已发送
```

> **提示**：微信的 UIA 控件不可见，Agent 完全靠截图判断位置。比记事本更需要精确坐标。如果点歪了，让 Agent 根据截图调整后重试。

### 教程 3：在 Chrome 中搜索

```
第 1 步：切换到 Chrome
  → switch_window("Chrome")
  ← ✅ 已切换到

第 2 步：看地址栏位置
  → get_snapshot()
  截图中地址栏在窗口顶部 (200, 30)

第 3 步：点地址栏并输入
  → click(200, 30)
  → type_text("github.com", 200, 30)
  → press_key("Enter")
  ← ✅ 已打开 GitHub

第 4 步：等待加载
  → wait(3000)

第 5 步：看搜索结果
  → get_snapshot()
  Agent 看到页面已加载，可以继续操作
```

### 教程 4：文件管理器多选操作

```
第 1 步：打开文件管理器 → 看界面
  → switch_window("Program Manager")
  → get_snapshot()
  桌面上有多个文件图标

第 2 步：按住 Ctrl → 逐个点击 → 释放 Ctrl
  → hold_key("Control")
  → click(100, 200)    ← 点第一个文件
  → click(100, 300)    ← 点第二个文件
  → click(100, 400)    ← 点第三个文件
  → release_key("Control")
  ← 三个文件被选中

第 3 步：右键打开菜单
  → press_key("Shift+F10")
  ← 弹出右键菜单
```

> **hold_key + click + release_key 模式**是实现"Ctrl+点击多选"的正确方式。不要用 press_key("ctrl")——它按了就松。

---

## 安全

### 紧急终止

任何时候按 **Ctrl+Alt+K** 立即终止 MCP Server。

这是在 Agent 失控时（比如鼠标乱飞、不停打字）的安全底线。MCP Server 终止后，Agent 将无法继续操控桌面。

### 操作日志

所有工具调用记录在 `desktop.ops` 日志中。排查问题时查看：

```
# 设置日志级别为 DEBUG 查看更多信息
set LOG_LEVEL=DEBUG
python -m reasonix_desktop_tools.mcp_server
```

日志输出示例：

```
INFO | desktop.ops | [click] x=350, y=50 → ✅ 已点击 (350, 50)
INFO | desktop.ops | [type_text] text=张三, x=350, y=50 → ✅ 已在输入
WARN | desktop.ops | [click] x=100, y=200 → ❌ 当前无激活窗口
```

### 坐标预览（手动调试）

在投入 Agent 使用前，可以用 smoke test 验证点击坐标是否准确：

```bash
python tests/smoke_test.py
```

如果 `click()` 测试通过但鼠标没动，可能是：

- MCP Server 权限不足（以普通用户运行但目标窗口需要管理员权限）
- 安全软件拦截了 SendInput
- DPI 缩放导致坐标错位（检查启动自检中的 DPI 值）

---

## 排障

### MCP Server 启动报错

```
错误: No module named 'dxcam'
解决: pip install dxcam
```

```
错误: No module named 'mcp'
解决: pip install mcp
```

### Agent 说"找不到工具"

```
原因: MCP Server 未正确注册
解决: 
  1. 在终端中直接运行 python -m reasonix_desktop_tools.mcp_server 看是否报错
  2. 确认 Agent 的 MCP 配置路径正确
  3. 重启 Agent
```

### 截图为空 / 黑屏

```
原因 1: DXcam 坐标超出物理屏幕范围
  检查启动自检中的"虚拟桌面"范围，确保窗口在屏幕内

原因 2: 窗口在 150% DPI 下坐标计算错误
  检查启动自检中的 DPI 值，如果 >100% 且截图偏移，尝试调整 DPI 缩放

原因 3: DXcam 不支持当前显卡
  get_snapshot 会自动 fallback 到 PIL 截图，虽然不能截遮挡窗口但基本功能可用
```

### 点击偏了 / 点不到正确位置

```
原因 1: 多显示器场景窗口坐标计算错误
  检查启动自检中的"显示器"数量，如果是 2+ 个显示器，
  确保被操作的窗口在主屏上

原因 2: DPI 缩放导致 UI 元素实际位置和截图不一致
  Windows 设置 → 显示 → 缩放 → 设置为 100% 可消除此问题

原因 3: 窗口被其他窗口遮挡
  click 前先 switch_window 确保目标在最前
```

### UIA 控件列表为空

```
原因: 当前应用（如微信、Chrome、Electron 应用）不暴露 UIA 控件
影响: Agent 无法通过控件名定位，只能靠截图自己判断位置
解决: 这是正常的，Agent 会看截图做决定
```

---

## 设计思路

### 核心原则

**工具只提供信息，Agent 自己决策。**

```
get_snapshot → 原始信息（截图 + 控件树）
click / type_text → 执行
                 ↓
Agent 自己看截图、自己算坐标、自己决定下一步
```

### 和 Computer Use 的区别

| 维度 | Claude Computer Use | reasonix-desktop-tools |
|---|---|---|
| 截图 | Windows.Graphics.Capture | DXcam（D3D） |
| 坐标 | 窗口相对坐标 | 窗口相对坐标 |
| Agent 兼容性 | 仅 Codex | 所有 MCP Agent |
| 截图缓存 | 无 | 操作日志、启动自检 |
| 紧急终止 | 无 | Ctrl+Alt+K |

### 技术栈

- **截图**: DXcam（DirectX 后端），被遮挡也能截取
- **定位**: UIAutomation + accessibility 树（有则返回，无则留空）
- **输入**: SendInput（Windows 原生输入模拟）
- **协议**: MCP（Model Context Protocol）

---

## 依赖

- Windows 10 1809+
- Python 3.10 ~ 3.12
- pip 包：mcp, dxcam, Pillow, comtypes
