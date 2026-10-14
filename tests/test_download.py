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

# --- 多连接分片 --------------------------------------------------------------
# 分片要同一份内容并发写: 每段 seek 到自己的偏移, 谁也不碰谁的字节
BIG = bytes(range(256)) * 20480         # 5MB: 每段至少 MIN_SPLIT, 才有 4 段
import http.server as _hs


class BigH(_hs.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_GET(self):
        data = BIG
        rng = self.headers.get('Range')
        start, end = 0, len(data) - 1
        if rng:
            part = rng.split('=')[1]
            a, _, b = part.partition('-')
            start = int(a)
            end = int(b) if b else end
            end = min(end, len(data) - 1)
            if start >= len(data):
                self.send_response(416)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
        else:
            self.send_response(200)
        chunk = data[start:end + 1]
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(chunk)))
        self.send_header('ETag', ETAG)
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        self.wfile.write(chunk)


srv3 = _hs.ThreadingHTTPServer(('127.0.0.1', 0), BigH)
threading.Thread(target=srv3.serve_forever, daemon=True).start()
base3 = f'http://127.0.0.1:{srv3.server_address[1]}'
big = os.path.join(WORK, 'big4.bin')

def op3(url):
    from webtool.net import transport

    def opener(headers):
        return transport.open_stream(url, timeout=20, headers=headers, proxy='direct')
    return opener


r = dl.download(base3 + '/big.bin', big, op3(base3 + '/big.bin'), jobs=4, progress=False)
check(r.get('jobs') == 4 and 'file' in r, '--jobs 4: 走分片下载')
check(open(big, 'rb').read() == BIG, '4 段并发下载后内容一致 (没有拼错位)')
check(not os.path.exists(big + '.part'), '分片下完不留 .part')

# 分片续传: 假造"第 1 段下完了、第 3 段下了一半"的现场
segs = dl._segments(len(BIG), 4)
done = [segs[0][1] + 1, 0, 5000, 0]
with open(big + '.part', 'wb') as f:
    f.truncate(len(BIG))
with open(big + '.part', 'r+b') as f:      # 只有"已下完"的部分是真数据
    f.seek(segs[0][0])
    f.write(BIG[segs[0][0]:segs[0][1] + 1])
    f.seek(segs[2][0])
    f.write(BIG[segs[2][0]:segs[2][0] + 5000])
with open(big + '.part.meta', 'w') as f:
    import json as _json
    _json.dump({'url': base3 + '/big.bin', 'total': len(BIG), 'validator': ETAG,
                'segs': segs, 'done': done}, f)
os.path.exists(big) and os.remove(big)
r = dl.download(base3 + '/big.bin', big, op3(base3 + '/big.bin'), progress=False)
check('file' in r and open(big, 'rb').read() == BIG,
      '分片续传: 只补没下完的段, 拼出来仍然一致')
check(dl._seg_meta(big, base3 + '/big.bin') is None, '分片下完清掉现场')

# 服务端不认 Range: jobs=4 也要退回单连接 (200 拿全量, 不能瞎切)
srv4, base4 = serve(NoRange)
r = dl.download(base4 + '/small.bin', os.path.join(WORK, 'nofrag.bin'),
                op(base4 + '/small.bin'), jobs=4, progress=False)
check('jobs' not in r and open(os.path.join(WORK, 'nofrag.bin'), 'rb').read() == PAYLOAD[:5000],
      '服务端不认 Range: 自动退回单连接 (切了也白切)')

# 慢链路才看得出多连接的价值: 每条连接被限速时, 4 段并发该快出好几倍。
# 顺带反证"分片真的并发跑了" —— 如果哪次退化回串行, 这条会先红
import time as _time
_D = bytes(range(256)) * 16384           # 4MB, 够 4 段


class ThrottleH(_hs.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_GET(self):
        rng = self.headers.get('Range')
        start, end = 0, len(_D) - 1
        if rng:
            a, _, b = rng.split('=')[1].partition('-')
            start, end = int(a), min(int(b) if b else end, len(_D) - 1)
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(_D)}')
        else:
            self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('ETag', ETAG)
        self.end_headers()
        for i in range(start, end + 1, 16384):
            self.wfile.write(_D[i:min(i + 16384, end + 1)])
            self.wfile.flush()
            _time.sleep(0.05)            # 每 16KB 停 50ms ≈ 320KB/s 每连接


srv5 = _hs.ThreadingHTTPServer(('127.0.0.1', 0), ThrottleH)
threading.Thread(target=srv5.serve_forever, daemon=True).start()
base5 = f'http://127.0.0.1:{srv5.server_address[1]}'

def _timed(jobs):
    p = os.path.join(WORK, f'thr{jobs}.bin')
    t0 = _time.time()
    dl.download(base5 + '/f.bin', p, op(base5 + '/f.bin'), jobs=jobs, progress=False)
    el = _time.time() - t0
    same = open(p, 'rb').read() == _D
    os.remove(p)
    return el, same


t1, s1 = _timed(1)
t4, s4 = _timed(4)
check(s1 and s4, '限速链路上单/多连接内容都一致')
check(t4 < t1 / 2, f'限速链路 4 连接该快一倍以上 (实测 {t1:.1f}s → {t4:.1f}s)')
srv5.shutdown()

check(dl._segments(10, 3) == [[0, 2], [3, 5], [6, 9]], '分段: 均匀切且不重不漏')
check(dl._segments(1000001, 8)[-1][1] == 1000000, '最后一段吃到文件末尾')
srv3.shutdown()
srv4.shutdown()

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
