"""L7 流式通道: SSE 读取 + WebSocket 帧编解码

出网**不在这里** —— 请求仍经 `net.transport` (指纹/线路/证书与普通请求同源),
本模块只负责"拿到裸流之后怎么按协议切帧"。业务模块不再各自 read1/切行/解压。

- **SSE**: `open_sse()` 发请求 (走 transport), `iter_sse(resp)` 逐行产出。
  字节层切行 (整块 decode 再切会把跨读边界的汉字写成 U+FFFD), 按
  Content-Encoding 增量解压 (gzip/deflate; br/zstd 无 stdlib 支持, 明确报错)。
- **WebSocket**: `ws_key()/ws_accept()` 握手, `encode_frame()/FrameReader`
  帧编解码 (RFC 6455)。`open_ws()` 是预留的直连入口, 见其文档。

消费者: `cli/zen/client.py` 的流式聊天 (SSE)。
"""
import base64
import hashlib
import os
import zlib

# ── SSE ─────────────────────────────────────────────────────────


class StreamAborted(RuntimeError):
    """流读到一半断了 (超时/连接重置/解压失败)。调用方已消费到的行不受影响。"""


class _Identity:
    def __call__(self, b):
        return b

    def flush(self):
        return b''


class _Zlib:
    def __init__(self, wbits):
        self._d = zlib.decompressobj(wbits)

    def __call__(self, b):
        return self._d.decompress(b) if b else b''

    def flush(self):
        return self._d.flush()


class _NoImpl:
    def __init__(self, enc):
        self.enc = enc

    def __call__(self, _b):
        raise RuntimeError('上游返回 %s 压缩, 本地没有对应库 (装 brotli/'
                           'zstandard, 或从 Accept-Encoding 去掉它)' % self.enc)

    def flush(self):
        return b''


def decompressor(encoding):
    """按 Content-Encoding 造增量解压器 (原 cli/zen/client._unzipper)

    返回对象可调用 `d(chunk)` 喂数据, 结束时**必须** `d.flush()` —— 压缩流
    的最后一块常被压在解压器内部, 不 flush 就会丢掉尾巴 (SSE 的 `[DONE]`
    正好在尾巴上)。gzip/deflate 走 stdlib 增量解; br/zstd 无 stdlib 支持,
    喂数据时明确报错, 不喂乱码。
    """
    enc = (encoding or '').strip().lower()
    if enc in ('', 'identity'):
        return _Identity()
    if enc in ('gzip', 'x-gzip'):
        return _Zlib(16 + zlib.MAX_WBITS)
    if enc == 'deflate':
        return _Zlib(zlib.MAX_WBITS)
    return _NoImpl(enc)


def open_sse(method, url, *, headers=None, data=None, proxy=None,
             timeout=None, via='urllib', raw_headers=True, **kw):
    """发一次流式请求, 返回 transport 的流式响应 (body 未读)

    默认走 urllib + raw_headers (对上家来说要的是"一个说协议的普通客户端",
    塞浏览器指纹没意义还可能踩协议校验); 线路/证书仍归 transport。
    """
    from webtool.net import transport
    return transport.request(method, url, raw_headers=raw_headers, via=via,
                             stream=True, headers=headers, data=data,
                             proxy=proxy, timeout=timeout, **kw)


def iter_sse(resp, chunk_size=65536):
    """transport 的流式响应 → 逐行产出 SSE 原始行 (str, 无换行)

    - 字节层切行: 整块 decode 再切会把跨读边界的汉字写成 U+FFFD
    - 增量解压: 一个解压器全程复用 (跨 chunk 的流不能每块各造一个)
    - 读中断抛 StreamAborted, 已产出的行照常先交给调用方
    - 末尾无换行的残行也产出

    SSE 语义 (`data:` 累积、事件类型、`[DONE]`) 由调用方解析 —— 这里只保证
    "行是完整的、编码是干净的"。
    """
    raw = resp.raw
    unzip = decompressor(raw.headers.get('Content-Encoding'))
    read = getattr(raw, 'read1', None) or (lambda n: raw.read(n))
    remainder = b''
    with raw:
        while True:
            try:
                raw_chunk = read(chunk_size)
            except (TimeoutError, OSError) as e:
                raise StreamAborted('%s: %s' % (type(e).__name__, str(e)[:100]))
            if not raw_chunk:          # 只有**原始**读空才是 EOF
                break
            chunk = unzip(raw_chunk)   # 解压后为空是常态 (块不满), 不能当 EOF
            if not chunk:
                continue
            remainder += chunk
            if b'\n' not in remainder:
                continue
            *complete, remainder = remainder.split(b'\n')
            for c in complete:
                yield c.decode('utf-8', errors='replace')
        # EOF: 压缩流的最后一块常压在解压器内部, 不 flush 就丢尾巴
        try:
            tail = unzip.flush()
        except Exception:
            tail = b''
        if tail:
            *complete, remainder = (remainder + tail).split(b'\n')
            for c in complete:
                yield c.decode('utf-8', errors='replace')
        if remainder:
            yield remainder.decode('utf-8', errors='replace')


# ── WebSocket: 握手与帧编解码 (RFC 6455) ─────────────────────────
#
# 本模块提供 WS 的**纯协议层**: 握手键/应答、帧编解码、消息重组 (分片/ping/pong)。
# 建连 (`open_ws`) 需要保持底层裸读写, curl_cffi 会话不暴露该能力, 得另开一条
# socket/ssl/CONNECT 通道并接上 netx 的线路与证书决策 —— 目前**没有消费方**,
# 不预造 (见 docs/refactor-plan.md P3)。首个 WS 消费方接入时, 用这里的
# encode_frame/FrameReader 拼上 transport 的握手路径即可, 协议层无需再动。

WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

OP_CONT, OP_TEXT, OP_BIN = 0x0, 0x1, 0x2
OP_CLOSE, OP_PING, OP_PONG = 0x8, 0x9, 0xA

_FIN = 0x80
_MASK = 0x80


def ws_key():
    """一个合法的 Sec-WebSocket-Key (16 字节随机的 base64)"""
    return base64.b64encode(os.urandom(16)).decode('ascii')


def ws_accept(key):
    """Sec-WebSocket-Key → 服务端应回应的 Sec-WebSocket-Accept"""
    return base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode('ascii')).digest()).decode('ascii')


def ws_handshake_headers(url, key=None, extra=None):
    """升级请求头; 返回 (headers, key)"""
    from urllib.parse import urlsplit
    host = urlsplit(url).netloc
    k = key or ws_key()
    h = {
        'Host': host,
        'Upgrade': 'websocket',
        'Connection': 'Upgrade',
        'Sec-WebSocket-Key': k,
        'Sec-WebSocket-Version': '13',
    }
    h.update(extra or {})
    return h, k


def ws_check_accept(headers, key):
    """校验服务端 101 响应里的 Sec-WebSocket-Accept (大小写不敏感)"""
    got = ''
    for k, v in (headers or {}).items():
        if str(k).lower() == 'sec-websocket-accept':
            got = v
            break
    return got.strip() == ws_accept(key)


def encode_frame(opcode, payload=b'', *, fin=True, mask=True):
    """造一帧。客户端 → 服务端**必须** mask (RFC 6455 5.3)"""
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    head = bytearray()
    head.append((_FIN if fin else 0) | (opcode & 0x0F))
    n = len(payload)
    mbit = _MASK if mask else 0
    if n < 126:
        head.append(mbit | n)
    elif n < 65536:
        head.append(mbit | 126)
        head += n.to_bytes(2, 'big')
    else:
        head.append(mbit | 127)
        head += n.to_bytes(8, 'big')
    if not mask:
        return bytes(head) + payload
    mk = os.urandom(4)
    head += mk
    masked = bytes(b ^ mk[i % 4] for i, b in enumerate(payload))
    return bytes(head) + masked


def encode_close(code=1000, reason=''):
    import struct
    body = struct.pack('!H', code) + (reason.encode('utf-8') if reason else b'')
    return encode_frame(OP_CLOSE, body)


class FrameReader:
    """从连续字节流里切出 WS 帧。`read(n)` 是"最多读 n 字节"的取数函数,
    `write` 可选 —— 给了才能在读消息时自动回 pong。"""

    def __init__(self, read, write=None):
        self._read = read
        self._write = write

    def _exact(self, n):
        buf = b''
        while len(buf) < n:
            b = self._read(n - len(buf))
            if not b:
                raise StreamAborted('WS 流提前结束 (want %d, got %d)'
                                    % (n, len(buf)))
            buf += b
        return buf

    def read_frame(self):
        """→ (opcode, payload: bytes, fin: bool)。服务端帧不该带 mask。"""
        b0, b1 = self._exact(2)
        fin = bool(b0 & _FIN)
        opcode = b0 & 0x0F
        masked = bool(b1 & _MASK)
        n = b1 & 0x7F
        if n == 126:
            n = int.from_bytes(self._exact(2), 'big')
        elif n == 127:
            n = int.from_bytes(self._exact(8), 'big')
        mk = self._exact(4) if masked else b''
        payload = self._exact(n) if n else b''
        if masked:
            payload = bytes(c ^ mk[i % 4] for i, c in enumerate(payload))
        return opcode, payload, fin

    def read_message(self):
        """读到一条完整消息 (自动拼分片、回 pong、处理 close) → (opcode, bytes)

        ping/pong 在内部消化, 不冒泡给调用方; close 返回 (OP_CLOSE, body)。
        """
        parts, first_op = [], None
        while True:
            opcode, payload, fin = self.read_frame()
            if opcode == OP_PING:
                if self._write:
                    self._write(encode_frame(OP_PONG, payload, mask=True))
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                return OP_CLOSE, payload
            if opcode == OP_CONT:
                parts.append(payload)
            else:
                first_op = opcode
                parts = [payload]
            if fin:
                return first_op, b''.join(parts)
