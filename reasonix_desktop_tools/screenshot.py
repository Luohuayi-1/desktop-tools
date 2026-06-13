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


def capture_window(left: int, top: int,
                   right: int, bottom: int) -> Optional[str]:
    """截取指定区域的截图，返回 base64 编码的 PNG。

    优先使用 DXcam（D3D），失败时回退 PIL。
    可以截取被其他窗口遮挡的内容。

    参数:
        left, top: 区域左上角屏幕坐标
        right, bottom: 区域右下角屏幕坐标

    返回 base64 PNG 字符串，失败返回 None。
    """
    # 方案 A: DXcam（D3D，可截取被遮挡内容）
    result = _capture_dxcam(left, top, right, bottom)
    if result is not None:
        return result

    # 方案 B: PIL ImageGrab（传统方式，不支持被遮挡窗口）
    result = _capture_pil(left, top, right, bottom)
    if result is not None:
        return result

    logger.error("所有截图方案均失败")
    return None


def _capture_dxcam(left: int, top: int,
                   right: int, bottom: int) -> Optional[str]:
    """使用 DXcam（D3D 后端）截取指定区域。"""
    try:
        import dxcam
        import numpy as np
        from PIL import Image

        camera = dxcam.create(output_color="RGB")
        if camera is None:
            return None

        # 截取区域
        region = (left, top, right, bottom)
        frame = camera.grab(region=region)

        if frame is None:
            # 首次调用可能返回 None，重试一次
            import time
            time.sleep(0.1)
            frame = camera.grab(region=region)

        if frame is None:
            logger.warning("DXcam 返回空帧")
            return None

        # numpy array → PIL Image → PNG base64
        img = Image.fromarray(frame)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    except ImportError:
        logger.debug("dxcam 未安装")
        return None
    except Exception as exc:
        logger.warning("DXcam 截图失败: %s", exc)
        return None


def _capture_pil(left: int, top: int,
                 right: int, bottom: int) -> Optional[str]:
    """使用 PIL ImageGrab 截取指定区域（fallback）。"""
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    except ImportError:
        logger.error("PIL 未安装")
        return None
    except Exception as exc:
        logger.error("PIL 截图失败: %s", exc)
        return None


def capture_full_screen() -> Optional[str]:
    """截取全屏，返回 base64 PNG。

    不依赖窗口信息，直接截取当前屏幕全部内容。
    """
    try:
        import dxcam
        import numpy as np
        from PIL import Image

        camera = dxcam.create(output_color="RGB")
        if camera is not None:
            frame = camera.grab()
            if frame is not None:
                img = Image.fromarray(frame)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        pass

    # fallback
    return _capture_pil(0, 0, 99999, 99999)
