"""桌面标注台 — 可视化标注应用的控件坐标，导出预设。

用法:
  python -m desktop_tools.annotator

流程:
  1. 选择目标窗口 → 截图
  2. 点击截图中的 UI 元素 → 命名
  3. 导出预设文件
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional

# 预设存储目录
PRESETS_DIR = os.path.join(os.path.expanduser("~"), ".desktop-tools", "presets")


class AnnotatorApp:
    """标注台主窗口。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("桌面标注台 — desktop-tools")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)

        # 窗口列表
        self.windows: list[dict] = []
        self.selected_hwnd: int = 0
        self.selected_title: str = ""
        self.process_name: str = ""

        # 截图相关
        self.screenshot = None
        self.tk_image = None
        self.canvas_image_id = None

        # 标注数据: {name: (x_pct, y_pct)}
        self.elements: dict[str, dict] = {}
        self.marker_ids: list[int] = []

        # 截图缩放比例（截图物理尺寸 / 显示尺寸）
        self.scale_x = 1.0
        self.scale_y = 1.0

        self._build_ui()
        self._refresh_windows()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(top, text="目标窗口:").pack(side=tk.LEFT)
        self.window_combo = ttk.Combobox(top, width=50, state="readonly")
        self.window_combo.pack(side=tk.LEFT, padx=5)
        self.window_combo.bind("<<ComboboxSelected>>", self._on_window_selected)

        ttk.Button(top, text="刷新", command=self._refresh_windows).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="截图", command=self._capture).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="清空标注", command=self._clear_markers).pack(side=tk.LEFT, padx=2)

        # 信息栏
        info_frame = ttk.Frame(self.root)
        info_frame.pack(fill=tk.X, padx=5)
        self.info_label = ttk.Label(info_frame, text="选择窗口后点击「截图」")
        self.info_label.pack(side=tk.LEFT)

        # 截图画布
        canvas_frame = ttk.Frame(self.root)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.canvas = tk.Canvas(canvas_frame, bg="#f0f0f0", cursor="crosshair")
        vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        hbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=0, column=2, sticky="ew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # 底部状态
        bottom = ttk.Frame(self.root)
        bottom.pack(fill=tk.X, padx=5, pady=5)

        self.status_label = ttk.Label(bottom, text="已标注: 0 个控件")
        self.status_label.pack(side=tk.LEFT)

        ttk.Button(bottom, text="导出预设", command=self._export_preset).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bottom, text="管理预设", command=self._manage_presets).pack(side=tk.RIGHT, padx=2)

    # ------------------------------------------------------------------
    # 窗口管理
    # ------------------------------------------------------------------

    def _refresh_windows(self):
        """枚举所有顶层窗口并更新下拉列表。"""
        self.windows = []
        try:
            import uiautomation as uia
            for child in uia.GetRootControl().GetChildren():
                try:
                    name = child.Name or ""
                    if name.strip():
                        hwnd = child.NativeWindowHandle
                        proc = child.GetProcessName() or ""
                        self.windows.append({
                            "hwnd": hwnd,
                            "title": name,
                            "process": proc,
                        })
                except Exception:
                    continue
        except Exception:
            pass

        # 按标题排序
        self.windows.sort(key=lambda w: w["title"])
        titles = [f"[0x{w['hwnd']:X}] {w['title']}" for w in self.windows]
        self.window_combo["values"] = titles
        if titles:
            self.window_combo.current(0)
            self._select_by_index(0)

    def _on_window_selected(self, event=None):
        idx = self.window_combo.current()
        if idx >= 0:
            self._select_by_index(idx)

    def _select_by_index(self, idx: int):
        if 0 <= idx < len(self.windows):
            w = self.windows[idx]
            self.selected_hwnd = w["hwnd"]
            self.selected_title = w["title"]
            self.process_name = w["process"]
            self.info_label.config(text=f"窗口: {w['title']} | hwnd=0x{w['hwnd']:X}")

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------

    def _capture(self):
        """截取选中窗口的客户区并显示。"""
        if not self.selected_hwnd:
            messagebox.showwarning("提示", "请先选择窗口")
            return

        # 获取客户区坐标
        from .windows_api import get_client_rect
        cr = get_client_rect(self.selected_hwnd)
        if not cr:
            messagebox.showerror("错误", "无法获取窗口客户区")
            return

        # 截图
        from .screenshot import capture_window
        result = capture_window(
            cr["client_left"], cr["client_top"],
            cr["client_left"] + cr["client_width"],
            cr["client_top"] + cr["client_height"],
            quality=95,  # PNG 无损用于标注
        )
        if not result:
            messagebox.showerror("错误", "截图失败")
            return

        # 解码显示
        import base64, io
        from PIL import Image, ImageTk
        b64, mime = result
        img_data = base64.b64decode(b64)
        self.screenshot = Image.open(io.BytesIO(img_data))

        # 缩放到画布显示（最大 800x600）
        display_w, display_h = 800, 600
        img_w, img_h = self.screenshot.size
        scale = min(display_w / img_w, display_h / img_h, 1.0)
        display_w = int(img_w * scale)
        display_h = int(img_h * scale)
        self.scale_x = img_w / display_w
        self.scale_y = img_h / display_h

        disp_img = self.screenshot.resize((display_w, display_h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(disp_img)

        self.canvas.delete("all")
        self.canvas_image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        self.canvas.config(scrollregion=(0, 0, display_w, display_h), width=display_w, height=display_h)

        self.info_label.config(text=f"截图: {img_w}x{img_h} → 显示 {display_w}x{display_h}")
        self._clear_markers()

    # ------------------------------------------------------------------
    # 标注系统
    # ------------------------------------------------------------------

    def _on_canvas_click(self, event):
        """用户点击截图画布 → 弹窗命名 → 记录坐标。"""
        if self.screenshot is None:
            return

        # 物理坐标
        px = int(event.x * self.scale_x)
        py = int(event.y * self.scale_y)

        name = simpledialog.askstring(
            "标注控件",
            f"坐标 ({px}, {py})\n请输入控件名称:",
            parent=self.root,
        )
        if not name:
            return

        # 百分比坐标
        img_w, img_h = self.screenshot.size
        x_pct = round(px / img_w, 4)
        y_pct = round(py / img_h, 4)

        self.elements[name] = {"x_pct": x_pct, "y_pct": y_pct}

        # 画标记
        r = 4
        cx, cy = event.x, event.y
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="red", outline="white", width=2)
        self.canvas.create_text(cx + 10, cy - 10, text=name, anchor=tk.W, fill="red", font=("Arial", 10, "bold"))

        self._update_status()

    def _clear_markers(self):
        """清除所有标注（只清数据，不重绘画布）。"""
        self.elements = {}
        self._update_status()

    def _update_status(self):
        self.status_label.config(text=f"已标注: {len(self.elements)} 个控件")

    # ------------------------------------------------------------------
    # 预设管理
    # ------------------------------------------------------------------

    def _export_preset(self):
        """导出预设文件。"""
        if not self.elements:
            messagebox.showwarning("提示", "请先标注至少一个控件")
            return

        app_name = simpledialog.askstring(
            "导出预设", "应用名称 (如 wechat):",
            initialvalue=self.process_name.replace(".exe", "").lower() or "app",
            parent=self.root,
        )
        if not app_name:
            return

        app_version = simpledialog.askstring(
            "导出预设", "应用版本 (如 3.9.10):",
            initialvalue="1.0.0",
            parent=self.root,
        )
        if not app_version:
            return

        preset = {
            "app": app_name,
            "version": app_version,
            "process_name": self.process_name,
            "window_title": self.selected_title,
            "elements": self.elements,
        }

        os.makedirs(PRESETS_DIR, exist_ok=True)
        filename = f"{app_name}_{app_version}.json"
        filepath = os.path.join(PRESETS_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(preset, f, ensure_ascii=False, indent=2)

        # 同时保存一份到项目 presets 目录（便于 git 提交）
        project_presets = os.path.join(os.path.dirname(__file__), "..", "presets")
        os.makedirs(project_presets, exist_ok=True)
        proj_path = os.path.join(project_presets, filename)
        with open(proj_path, "w", encoding="utf-8") as f:
            json.dump(preset, f, ensure_ascii=False, indent=2)

        messagebox.showinfo(
            "导出成功",
            f"已保存:\n  {filepath}\n  {proj_path}\n\n"
            f"共 {len(self.elements)} 个控件:\n" +
            "\n".join(f"  {n} @ ({v['x_pct']:.1%}, {v['y_pct']:.1%})" for n, v in self.elements.items())
        )

    def _manage_presets(self):
        """查看/删除本地预设。"""
        if not os.path.isdir(PRESETS_DIR):
            messagebox.showinfo("预设管理", "暂无预设文件")
            return

        files = [f for f in os.listdir(PRESETS_DIR) if f.endswith(".json")]
        if not files:
            messagebox.showinfo("预设管理", "暂无预设文件")
            return

        win = tk.Toplevel(self.root)
        win.title("预设管理")
        win.geometry("500x400")

        listbox = tk.Listbox(win, font=("Consolas", 10))
        listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        for f in files:
            fp = os.path.join(PRESETS_DIR, f)
            try:
                with open(fp, "r") as fh:
                    data = json.load(fh)
                info = f"{data.get('app', '?')} v{data.get('version', '?')} — {len(data.get('elements', {}))} 控件"
                listbox.insert(tk.END, f"  {f}")
                listbox.insert(tk.END, f"    {info}")
                listbox.insert(tk.END, "")
            except Exception:
                listbox.insert(tk.END, f"  {f} (读取失败)")

        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=5)


def main():
    app = AnnotatorApp()
    app.root.mainloop()


if __name__ == "__main__":
    main()
