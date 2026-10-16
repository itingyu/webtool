# -*- coding: utf-8 -*-
"""net/stream 单测 (纯本地, 不联网): SSE 逐行读取 + WebSocket 帧编解码

覆盖:
  1. iter_sse: 逐行 / UTF-8 跨块边界不碎字 / 增量解压 / 末尾残行 / 读中断报错
  2. WS: 握手 key/accept 向量 / 帧编解码往返 / 分片重组 / ping 自动回 pong
跑法: python3 tests/test_stream.py
"""
import io
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []


def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL') + ' ' + name
          + (f' ({detail})' if (detail and not cond) else ''))
    if not cond:
        fails.append(name)


class _Raw:
    def __init__(self, data, headers=None, chunk=None, raise_after=None):
        self._b = io.BytesIO(data)
        self.headers = headers or {}
        self._chunk = chunk
        self._raise_after = raise_after
        self._n = 0

    def read1(self, n):
        if self._raise_after is not None and self._n >= self._raise_after:
            raise OSError('boom')
        if self._chunk:
            n = min(n, self._chunk)
        self._n += 1
        return self._b.read(n)

    read = read1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Resp:
    def __init__(self, raw):
        self.raw = raw


from webtool.net import stream as S   # noqa: E402

print('=== 1. SSE 逐行 ===')
r = _Resp(_Raw(b'data: a\n\ndata: [DONE]\n'))
check('逐行产出', list(S.iter_sse(r)) == ['data: a', '', 'data: [DONE]'])

r = _Resp(_Raw(b'data: x'))            # 无末尾换行
check('末尾残行也产出', list(S.iter_sse(r)) == ['data: x'])

print('\n=== 2. UTF-8 跨块不碎字 (chunk=1 强制逐字节切) ===')
body = 'data: 中文\n'.encode('utf-8')
r = _Resp(_Raw(body, chunk=1))
check('跨块汉字不产生 U+FFFD', list(S.iter_sse(r)) == ['data: 中文'])

print('\n=== 3. 增量解压 ===')
co = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
gz = co.compress(b'data: hi\n\ndata: [DONE]\n') + co.flush()
r = _Resp(_Raw(gz, headers={'Content-Encoding': 'gzip'}, chunk=3))
check('gzip 流增量解', list(S.iter_sse(r)) == ['data: hi', '', 'data: [DONE]'])
try:
    S.decompressor('br')(b'x')
    check('br 明确报错', False)
except RuntimeError as e:
    check('br 明确报错', 'br' in str(e))

print('\n=== 4. 读中断 → StreamAborted (已产出行先交出) ===')
got = []
r = _Resp(_Raw(b'data: a\ndata: b\n', chunk=8, raise_after=2))
try:
    for ln in S.iter_sse(r):
        got.append(ln)
    check('中断应抛 StreamAborted', False)
except S.StreamAborted as e:
    check('中断抛 StreamAborted 且已交出行',
          got == ['data: a', 'data: b'] and 'OSError' in str(e), str(got))

print('\n=== 5. WS 握手向量 ===')
check('accept 向量 (RFC 6455 例)',
      S.ws_accept('dGhlIHNhbXBsZSBub25jZQ==') == 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')
h, k = S.ws_handshake_headers('wss://example.com/ws')
check('握手头齐备', h['Upgrade'] == 'websocket' and h['Sec-WebSocket-Version'] == '13'
      and h['Sec-WebSocket-Key'] == k and h['Host'] == 'example.com')
check('accept 校验', S.ws_check_accept({'Sec-WebSocket-Accept': S.ws_accept(k)}, k)
      and not S.ws_check_accept({'Sec-WebSocket-Accept': 'nope'}, k))

print('\n=== 6. WS 帧编解码往返 ===')
f = S.encode_frame(S.OP_TEXT, 'hi', mask=True)
fr = S.FrameReader(io.BytesIO(f).read)
check('单帧往返 (文本, 客户端 mask)', fr.read_frame() == (S.OP_TEXT, b'hi', True))
f2 = S.encode_frame(S.OP_BIN, b'\x00\x01\x02', mask=False)
check('大/小长度掩码位', S.FrameReader(io.BytesIO(f2).read).read_frame()
      == (S.OP_BIN, b'\x00\x01\x02', True))

print('\n=== 7. 分片重组 + ping 自动回 pong ===')
data = (S.encode_frame(S.OP_TEXT, b'he', fin=False, mask=False)
        + S.encode_frame(S.OP_CONT, b'llo', fin=True, mask=False))
check('分片重组', S.FrameReader(io.BytesIO(data).read).read_message()
      == (S.OP_TEXT, b'hello'))
pongs = []
data = (S.encode_frame(S.OP_PING, b'p', mask=False)
        + S.encode_frame(S.OP_TEXT, b'hi', mask=False))
op, payload = S.FrameReader(io.BytesIO(data).read, write=pongs.append).read_message()
check('ping 内部消化并回 pong', op == S.OP_TEXT and payload == b'hi' and len(pongs) == 1)
check('回的是合法 pong 帧',
      S.FrameReader(io.BytesIO(pongs[0]).read).read_frame() == (S.OP_PONG, b'p', True))

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
