"""下载器本地验证: 断点续传 / 校验 / 进度, 全用本地 Range 服务器, 不碰外网"""
import hashlib
import http.server
import os
import shutil
import socket
import sys
import threading

sys.path.insert(0, 'src')
from webtool.net import download as dl

PAYLOAD = bytes(range(256)) * 1200          # 300KB+
ETAG = '"v1"'
WORK = '/tmp/dlwork'


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    honor_range = True
    cut_once = True          # /cut.bin 只模拟一次断流, 不然永远下不完

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path
        if path == '/missing':
            self.send_response(404)
            body = b'Not Found'
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        data = PAYLOAD
        if path == '/small.bin':
            data = PAYLOAD[:5000]
        rng = self.headers.get('Range')
        ifr = self.headers.get('If-Range')
        cut = path == '/cut.bin' and self.cut_once
        if cut:
            type(self).cut_once = False
        if rng and self.honor_range and (not ifr or ifr == ETAG):
            start = int(rng.split('=')[1].split('-')[0])
            if start >= len(data):
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{len(data)}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{len(data)-1}/{len(data)}')
            chunk = data[start:]
            if cut:                             # 假装半路断网: 只发一半就关
                chunk = chunk[:len(chunk) // 2]
                self.send_header('Content-Length', str(len(data) - start))
                self.end_headers()
                self.wfile.write(chunk)
                self.wfile.flush()
                self.close_connection = True
                return
            self.send_header('Content-Length', str(len(chunk)))
            self.send_header('ETag', ETAG)
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            self.wfile.write(chunk)
            return
        if cut:
            chunk = data[:len(data) // 2]
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(chunk)
            self.wfile.flush()
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('ETag', ETAG)
        if self.honor_range:
            self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Length', str(len(PAYLOAD)))
        self.end_headers()


class NoRange(H):
    honor_range = False


def serve(cls):
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}'


fails = []


def write_meta(dest, url, validator, total):
    """手写 .part.meta —— 用 json.dump, 手拼字符串会把引号拼坏"""
    import json
    with open(dest + '.part.meta', 'w') as f:
        json.dump({'url': url, 'validator': validator, 'total': total}, f)


def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


def op(url):
    """按传进来的 URL 建 opener —— 不能从全局变量取路径, 否则测的不是被测对象"""
    from webtool.net import transport

    def opener(headers):
        return transport.open_stream(url, timeout=20, headers=headers, proxy='direct')
    return opener


CUR = {'path': '/big.bin'}
srv, base = serve(H)
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)
dest = os.path.join(WORK, 'big.bin')

# 1) 全新下载
CUR['path'] = '/big.bin'
r = dl.download(base + '/big.bin', dest, op(base + '/big.bin'), progress=False)
check(r.get('file') and os.path.getsize(dest) == len(PAYLOAD), '整段下载: 文件完整')
check(not os.path.exists(dest + '.part'), '下完不留 .part')
check(open(dest, 'rb').read() == PAYLOAD, '内容与源一致')

# 2) 断点续传: 手动造一个"下到 100KB 就断了"的现场
half = 100000
with open(dest + '.part', 'wb') as f:
    f.write(PAYLOAD[:half])
write_meta(dest, base + '/big.bin', ETAG, len(PAYLOAD))
os.remove(dest)
r = dl.download(base + '/big.bin', dest, op(base + '/big.bin'), progress=False)
check(r.get('resumed_from') == half, f'续传: 从 {half} 接着收')
check(open(dest, 'rb').read() == PAYLOAD, '续传后内容仍然一致 (没拼错位)')
check(not os.path.exists(dest + '.part.meta'), '下完清掉 .part.meta')

# 3) 本地那份已经够了 → 416 → 直接改名
with open(dest + '.part', 'wb') as f:
    f.write(PAYLOAD)
write_meta(dest, base + '/big.bin', ETAG, len(PAYLOAD))
os.remove(dest)
r = dl.download(base + '/big.bin', dest, op(base + '/big.bin'), progress=False)
check(r.get('file') and open(dest, 'rb').read() == PAYLOAD, '416: 本地已够, 直接认完成')

# 4) 半路断网 → 留 .part + 报错, 再跑一次接上
CUR['path'] = '/cut.bin'
cutdest = os.path.join(WORK, 'cut.bin')
r = dl.download(base + '/cut.bin', cutdest, op(base + '/cut.bin'), progress=False)
check('error' in r and os.path.exists(cutdest + '.part'),
      '下到一半断网: 报错但留下 .part (不丢进度)')
check(not os.path.exists(cutdest), '断网时不许出现顶着正式名的半成品')
first = os.path.getsize(cutdest + '.part')
r = dl.download(base + '/cut.bin', cutdest, op(base + '/cut.bin'), progress=False)
check(r.get('size') == len(PAYLOAD) and open(cutdest, 'rb').read() == PAYLOAD,
      f'再跑一次从 {first} 续到完整')

# 5) 服务端不认 Range (200): 必须从头下, 不许在旧片段后面接
CUR['path'] = '/small.bin'
srv2, base2 = serve(NoRange)
nd = os.path.join(WORK, 'norange.bin')
with open(nd + '.part', 'wb') as f:
    f.write(b'X' * 1000)
open(nd + '.part.meta', 'w').write('{"url": "%s/small.bin", "validator": "\\"%s\\""}'
                                  % (base2, ETAG))
r = dl.download(base2 + '/small.bin', nd, op(base2 + '/small.bin'), progress=False)
check(open(nd, 'rb').read() == PAYLOAD[:5000],
      '服务端不认 Range 就整个重下 (接着写只会拼出坏文件)')

# 6) 404: 不落盘
r = dl.download(base + '/missing', os.path.join(WORK, 'nope.bin'), op(base + '/missing'), progress=False)
check('error' in r and not os.path.exists(os.path.join(WORK, 'nope.bin')),
      '404 报错且不落盘')

# 7) 孤零零的 .part (没有 .meta): 不可信, 清掉重下
orphan = os.path.join(WORK, 'orphan.bin')
with open(orphan + '.part', 'wb') as f:
    f.write(b'junk' * 100)
r = dl.download(base + '/small.bin', orphan, op(base + '/small.bin'), progress=False)
check(r.get('resumed_from') == 0 and open(orphan, 'rb').read() == PAYLOAD[:5000],
      '没有 .meta 同伴的 .part 直接作废 (凭什么信它是这东西的)')

# 8) 进度输出: 非 TTY 只有结果行, 不许有 \r
import io
import contextlib
buf = io.StringIO()
with contextlib.redirect_stderr(buf):
    dl.download(base + '/big.bin', os.path.join(WORK, 'big2.bin'), op(base + '/big.bin'), progress=False)
check('\r' not in buf.getvalue() and '下载完成' in buf.getvalue(),
      '非 TTY 进度: 只报一句结果, 不刷 \r')

# 9) 强制开进度时, TTY 分支要写出百分比
class FakeTTY(io.StringIO):
    def isatty(self):
        return True


buf = FakeTTY()
with contextlib.redirect_stderr(buf):
    dl.download(base + '/big.bin', os.path.join(WORK, 'big3.bin'), op(base + '/big.bin'), progress=True)
check('\r' in buf.getvalue(), '强制开进度时原地刷新 (\r) 生效')

check(dl.human(1536) == '1.5 KB' and dl.human(999) == '999 B', 'human() 说人话')
check(dl.total_of({'content-range': 'bytes 100-299/300'}, 206, 100) == 300,
      '总大小优先读 Content-Range 的 /z')
check(dl.request_headers(100, ETAG) == {
    'Accept-Encoding': 'identity', 'Range': 'bytes=100-', 'If-Range': ETAG},
    '续传请求头: identity + Range + If-Range 都不能少')
check(dl.request_headers(0, '') == {'Accept-Encoding': 'identity'},
      '全新下载不带 Range')

srv.shutdown()
srv2.shutdown()
print('FAILED: %d' % len(fails) if fails else 'ALL PASS')
sys.exit(1 if fails else 0)
