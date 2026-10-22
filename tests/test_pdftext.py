"""PDF 本地文本抽取: 抽取/分页/降级

覆盖:
1. 有文字层的 PDF 能抽出正文 (本地造 PDF, 不碰外网)
2. --pdf-pages 页码区间只抽指定页
3. 无文字层 (扫描件) 不报错, 说清原因
4. 加密 PDF 不崩 (顺序反了会抛 FileNotDecryptedError)
5. 文件不存在 / pypdf 缺失都优雅降级
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

N = [0]
FAIL = []


def check(cond, name, extra=''):
    N[0] += 1
    if cond:
        print('PASS', name)
    else:
        print('FAIL', name, extra)
        FAIL.append(name)


def _mkpdf(path, pages_text, encrypt=None):
    """造一个带文字层的 PDF (直接拼原始 PDF 字节, 不依赖 reportlab)"""
    objs = {}          # obj 编号 -> 内容
    n_pages = len(pages_text)
    page_ids = [4 + i * 2 for i in range(n_pages)]     # 每页: Page + Contents
    kids = ' '.join(f'{pid} 0 R' for pid in page_ids)
    objs[1] = '<< /Type /Catalog /Pages 2 0 R >>'
    objs[2] = f'<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>'
    objs[3] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
    for i, txt in enumerate(pages_text):
        pid, cid = page_ids[i], page_ids[i] + 1
        objs[pid] = (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] '
                     f'/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>')
        safe = txt.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
        stream = f'BT /F1 12 Tf 20 150 Td ({safe}) Tj ET'.encode('latin-1')
        objs[cid] = (f'<< /Length {len(stream)} >>\nstream\n'.encode('latin-1')
                     + stream + b'\nendstream')
    if encrypt:
        # 加密交给 pypdf (原始字节做 RC4 麻烦); 先写明文再原地加密
        from pypdf import PdfWriter
        w = PdfWriter()
        w.add_blank_page(width=300, height=300)
        with open(path, 'wb') as f:
            w.write(f)
        w2 = PdfWriter()
        w2.append(path)
        w2.encrypt(encrypt)
        with open(path, 'wb') as f:
            w2.write(f)
        return path

    out = bytearray(b'%PDF-1.4\n')
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        body = objs[num]
        if isinstance(body, str):
            body = body.encode('latin-1')
        out += f'{num} 0 obj\n'.encode('latin-1') + body + b'\nendobj\n'
    xref_at = len(out)
    maxnum = max(objs)
    out += f'xref\n0 {maxnum + 1}\n'.encode('latin-1')
    out += b'0000000000 65535 f \n'
    for num in range(1, maxnum + 1):
        out += f'{offsets.get(num, 0):010d} 00000 n \n'.encode('latin-1')
    out += (f'trailer\n<< /Size {maxnum + 1} /Root 1 0 R >>\nstartxref\n'
            f'{xref_at}\n%%EOF\n').encode('latin-1')
    with open(path, 'wb') as f:
        f.write(bytes(out))
    return path


TMP = tempfile.mkdtemp(prefix='webtool-pdf-')
from webtool.pipeline import pdftext          # noqa: E402

# --- 1. 有文字层能抽出来 ---
try:
    p1 = _mkpdf(os.path.join(TMP, 'a.pdf'), ['Hello World Alpha', 'Second Page Beta'])
    txt, meta = pdftext.extract(p1)
    check(meta.get('status') == 'ok', '有文字层的 PDF 抽出文本', meta)
    check('Alpha' in txt, '抽到第一页内容', txt[:80])
    check('Beta' in txt, '抽到第二页内容', txt[:80])
    check('第 1 页' in txt and '第 2 页' in txt, '页码标记在正文里', txt[:120])

    # --- 2. 页码区间 ---
    txt2, meta2 = pdftext.extract(p1, pages='2')
    check('Beta' in txt2 and 'Alpha' not in txt2, 'pages="2" 只抽第 2 页', txt2[:80])
    check(meta2.get('extracted') == 1, '只算了 1 页', meta2)

    txt3, _ = pdftext.extract(p1, pages='1-2')
    check('Alpha' in txt3 and 'Beta' in txt3, 'pages="1-2" 抽两页', txt3[:60])

    # 越界页码不该崩
    txt4, meta4 = pdftext.extract(p1, pages='5-9')
    check(meta4.get('status') in ('ok', 'empty'), '越界页码不崩', meta4)

    # --- 3. 无文字层 (扫描件) ---
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    blank = os.path.join(TMP, 'blank.pdf')
    w.write(blank)
    txt5, meta5 = pdftext.extract(blank)
    check(meta5.get('status') == 'empty', '无文字层 PDF 报 empty 不报错', meta5)
    check('OCR' in (meta5.get('error') or ''), '说清可能要 OCR', meta5)

    # --- 4. 加密 PDF 不崩 ---
    penc = os.path.join(TMP, 'enc.pdf')
    _mkpdf(penc, ['secret text'], encrypt='secret')
    txt6, meta6 = pdftext.extract(penc)
    check(meta6.get('status') == 'error', '加密 PDF 报 error 而不是抛异常', meta6)
    check('加密' in (meta6.get('error') or ''), '加密原因说清了', meta6)

    # --- 5. 文件不存在 ---
    txt7, meta7 = pdftext.extract(os.path.join(TMP, 'nope.pdf'))
    check(meta7.get('status') == 'error', '文件不存在报 error', meta7)

    # --- 6. max_chars 截断 ---
    txt8, meta8 = pdftext.extract(p1, max_chars=10)
    check(len(txt8) <= 40 and meta8.get('truncated'), 'max_chars 截断生效', len(txt8))
except ImportError:
    check(False, 'pypdf 可用 (装不上则跳过)')

# --- 7. 缺 pypdf 时优雅降级 (模拟 import 失败) ---
import builtins                                  # noqa: E402
_real = builtins.__import__


def _fake(name, *a, **k):
    if name == 'pypdf':
        raise ImportError('simulated')
    return _real(name, *a, **k)


builtins.__import__ = _fake
try:
    import importlib
    import webtool.pipeline.pdftext as _pt
    importlib.reload(_pt)
    check(_pt.available() is False, '缺 pypdf 时 available() 为 False')
    t, m = _pt.extract(os.path.join(TMP, 'a.pdf'))
    check(m.get('status') == 'unavailable', '缺 pypdf 时报 unavailable', m)
    check(t == '', '缺 pypdf 时正文为空')
finally:
    builtins.__import__ = _real
    import importlib
    import webtool.pipeline.pdftext as _pt
    importlib.reload(_pt)

print('\n%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
