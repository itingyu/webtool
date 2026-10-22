"""二维码图片渲染 (纯本地, 不联网)

给扫码登录用: 把一段文本 (App deep link / 会话 id) 渲染成 PNG。
可选依赖 qrcode; 没装时上层报可读提示, 不静默失败。
"""
from __future__ import annotations


class QRRenderError(RuntimeError):
    """没装 qrcode 库, 或渲染失败"""


def render(text, path, size=320, border=2):
    """把 text 渲染成二维码 PNG, 返回 path"""
    try:
        import qrcode
    except ImportError as e:
        raise QRRenderError(
            '缺少 qrcode 库: pip install qrcode') from e
    try:
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=8, border=border)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        img = img.resize((size, size))
        img.save(path)
    except Exception as e:
        raise QRRenderError(f'二维码渲染失败: {e}') from e
    return path
