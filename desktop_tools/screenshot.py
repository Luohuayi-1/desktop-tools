"""窗口截图模块。

优先使用 DXcam（D3D 后端，可截取被遮挡的窗口内容），
回退到 PIL ImageGrab。

DXcam 通过 DirectX 读取显卡后缓冲区，不受窗口遮挡影响。
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# DXcam 单例（避免重复创建实例的警告）
_dx_camera = None

def _get_dpi_scale(hwnd: int = 0) -> float:
    """获取指定窗口的 DPI 缩放比例。hwnd=0 用主屏。"""
    try:
        import ctypes
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd or ctypes.windll.user32.GetDesktopWindow())
        return dpi / 96.0
    except Exception:
        return 1.0


def _get_dxcam():
    """获取或创建全局 DXcam 实例。"""
    global _dx_camera
    if _dx_camera is not None:
        return _dx_camera
    try:
        import dxcam
        _dx_camera = dxcam.create(output_color="RGB")
        return _dx_camera
    except Exception:
        return None


def capture_window(left: int, top: int,
                   right: int, bottom: int,
                   quality: int = 100,
                   hwnd: int = 0) -> Optional[tuple[str, str]]:
    """截取指定区域的截图，返回 (base64, mime_type) 元组。

    优先使用 DXcam（D3D），失败时回退 PIL。
    可以截取被其他窗口遮挡的内容。

    参数:
        left, top: 区域左上角屏幕坐标（逻辑坐标，DPI 自动转换）
        right, bottom: 区域右下角屏幕坐标
        quality: JPEG 压缩质量 1-100（默认 85）。

    返回 (base64, "image/jpeg"|"image/png")，失败返回 None。
    """
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        logger.warning("无效截图区域: (%d,%d)-(%d,%d)", left, top, right, bottom)
        return None

    # DXcam 需要物理坐标（逻辑坐标 × DPI 缩放）
    # 用 window 的 hwnd 获取其所在屏幕的 DPI
    scale = _get_dpi_scale(hwnd)
    phys_left = int(left * scale)
    phys_top = int(top * scale)
    phys_right = int(right * scale)
    phys_bottom = int(bottom * scale)

    result = _capture_dxcam(phys_left, phys_top, phys_right, phys_bottom, quality)
    if result is not None:
        return result

    # PIL fallback 用逻辑坐标（PIL 自动处理 DPI）
    result = _capture_pil(left, top, right, bottom, quality)
    if result is not None:
        return result

    logger.error("所有截图方案均失败")
    return None


def _encode_img(img, quality: int) -> Optional[tuple[str, str]]:
    """将 PIL Image 编码为 base64。返回 (base64, mime_type)。"""
    try:
        buf = io.BytesIO()
        if quality < 95:
            img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            mime = "image/jpeg"
        else:
            img.save(buf, format="PNG", optimize=True)
            mime = "image/png"
        b64 = base64.b64encode(buf.getvalue()).decode()
        return (b64, mime)
    except Exception as exc:
        logger.error("图片编码失败: %s", exc)
        return None


def _capture_dxcam(left: int, top: int,
                   right: int, bottom: int,
                   quality: int,
                   hwnd: int = 0) -> Optional[tuple[str, str]]:
    """使用 DXcam（D3D 后端）截取指定区域。"""
    try:
        import numpy as np
        from PIL import Image

        camera = _get_dxcam()
        if camera is None:
            return None

        region = (left, top, right, bottom)
        frame = camera.grab(region=region)

        if frame is None:
            import time
            time.sleep(0.1)
            frame = camera.grab(region=region)

        if frame is None:
            logger.warning("DXcam 返回空帧")
            return None

        img = Image.fromarray(frame)
        # DXcam 获取的是物理像素，按 DPI 缩放回逻辑像素
        s = _get_dpi_scale(hwnd) if hwnd else 1.0
        if s != 1.0:
            w = int(img.width / s)
            h = int(img.height / s)
            img = img.resize((w, h), Image.LANCZOS)
        return _encode_img(img, quality)

    except ImportError:
        logger.debug("dxcam 未安装")
        return None
    except Exception as exc:
        logger.warning("DXcam 截图失败: %s", exc)
        return None


def _capture_pil(left: int, top: int,
                 right: int, bottom: int,
                 quality: int) -> Optional[tuple[str, str]]:
    """使用 PIL ImageGrab 截取指定区域（fallback）。"""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        return _encode_img(img, quality)
    except ImportError:
        logger.error("PIL 未安装")
        return None
    except Exception as exc:
        logger.error("PIL 截图失败: %s", exc)
        return None


def capture_full_screen(quality: int = 100) -> Optional[tuple[str, str]]:
    """截取全屏，返回 (base64, mime_type)。"""
    try:
        from PIL import Image
        camera = _get_dxcam()
        if camera is not None:
            import numpy as np
            frame = camera.grab()
            if frame is not None:
                img = Image.fromarray(frame)
                return _encode_img(img, quality)
    except Exception:
        pass

    # PIL ImageGrab.grab(bbox=(0,0,large,large)) 自动裁剪到实际屏幕大小，
    # 传超大值相当于"从(0,0)截取到屏幕右下角"，等价于不传 bbox 的全屏截取。
    return _capture_pil(0, 0, 99999, 99999, quality)
