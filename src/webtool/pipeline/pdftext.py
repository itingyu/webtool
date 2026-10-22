"""PDF 文本抽取 (本地): 走 pypdf, 不依赖远程 reader

为什么要有这层: fetch 碰到 PDF 原本只能"下载"不能"读" —— 本地链返回
raw-binary, 正文得靠 --via auto 走远程 reader (耗配额、依赖对方在线)。
论文/财报/白皮书是高频刚需, 本地能抽出来就不该逼用户去花配额。

设计:
- pypdf 缺失时优雅降级 (返回 unavailable, 上层照旧只报下载结果)
- 抽取失败不抛 —— PDF 可能加密/损坏/纯扫描件, 都不该让整次 fetch 失败
- 按页切, 页码标在每段前, 便于回查原文
"""
from __future__ import annotations

import re

from webtool.core.logging import get_logger

logger = get_logger(__name__)

# 页码标记: "## 第 3 页" —— 抽取结果按页切, 带页码才好回查
_PAGE_SEP = re.compile(r'\n{3,}')


def available():
    """pypdf 是否可用 (装没装决定能不能抽)"""
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        return False


def _clean_page(txt):
    """把一页的文字收拾干净: 去软连字符断词、去行尾空白、压多余空行"""
    if not txt:
        return ''
    # PDF 里常见的断词连字符: "inter-\nnational" → "international"
    txt = re.sub(r'(\w)-\n(\w)', r'\1\2', txt)
    lines = [ln.rstrip() for ln in txt.split('\n')]
    # 连续空行压成一行分隔 (页内的段落间隙)
    out, blank = [], False
    for ln in lines:
        if not ln.strip():
            blank = True
            continue
        if blank and out:
            out.append('')
        blank = False
        out.append(ln)
    return '\n'.join(out).strip()


def extract(path, pages=None, max_chars=0):
    """从 PDF 抽文本 → (text, meta)

    path: 本地 PDF 路径
    pages: 页码区间字符串, 如 "1-5" / "1,3,5-7"; None = 全文
    max_chars: >0 时截断

    返回 (text, meta):
      meta 含 status (ok/empty/unavailable/error)、pages (总页数)、
      extracted (实际抽的页数)、error (失败原因)
    任何异常都收在这里, 不往上抛 —— 抽不出只是一条附加信息, 不是致命错。
    """
    if not available():
        return '', {'status': 'unavailable', 'error': 'pypdf 未安装 (pip install pypdf)'}
    try:
        import pypdf
    except ImportError:
        return '', {'status': 'unavailable', 'error': 'pypdf 未安装'}

    try:
        reader = pypdf.PdfReader(path)
    except Exception as e:
        return '', {'status': 'error', 'error': f'打开失败: {type(e).__name__}: {str(e)[:200]}'}

    # 加密检查必须排在取页数之前: 加密 PDF 上 len(reader.pages) 直接抛
    # FileNotDecryptedError, 顺序反了根本走不到下面的 decrypt 分支。
    if reader.is_encrypted:
        # 很多 PDF 只是设了空 owner 口令, 用空串解一次能开
        try:
            if reader.decrypt('') == 0:
                return '', {'status': 'error', 'error': 'PDF 已加密 (需口令)'}
        except Exception as e:
            return '', {'status': 'error',
                        'error': f'PDF 已加密且解不开: {type(e).__name__}'}

    try:
        total = len(reader.pages)
    except Exception as e:
        return '', {'status': 'error',
                    'error': f'读页数失败: {type(e).__name__}: {str(e)[:160]}'}

    want = _parse_pages(pages, total)
    chunks, got = [], 0
    for idx in want:
        try:
            raw = reader.pages[idx].extract_text() or ''
        except Exception as e:
            logger.debug('pdftext | 第 %d 页抽取失败: %s', idx + 1, e, exc_info=True)
            continue
        got += 1
        body = _clean_page(raw)
        if body:
            chunks.append(f'## 第 {idx + 1} 页\n\n{body}')
    text = _PAGE_SEP.sub('\n\n', '\n\n'.join(chunks)).strip()
    meta = {'status': 'ok' if text else 'empty', 'pages': total, 'extracted': got}
    if not text:
        # 全是扫描图/空页是常态, 说明白比报个错有用
        meta['error'] = ('没抽到文字 (可能是扫描件/纯图片 PDF, 需 OCR)' if got
                         else '每页抽取都失败')
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + '\n…[truncated]'
        meta['truncated'] = True
    return text, meta


def _parse_pages(pages, total):
    """把 "1-5,8" 这样的页码串解成 0-based 下标列表 (越界丢弃, 顺序去重)"""
    if not pages:
        return list(range(total))
    idxs, seen = [], set()
    for part in str(pages).split(','):
        part = part.strip()
        if not part:
            continue
        m = re.match(r'^(\d+)\s*-\s*(\d+)$', part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            for i in range(a - 1, b):
                if 0 <= i < total and i not in seen:
                    seen.add(i)
                    idxs.append(i)
            continue
        if part.isdigit():
            i = int(part) - 1
            if 0 <= i < total and i not in seen:
                seen.add(i)
                idxs.append(i)
    return idxs
