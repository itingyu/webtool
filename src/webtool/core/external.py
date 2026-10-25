"""外部插件通用通道: 子进程 + 逐行 JSON (供 core / net 共用)

协议 v1:
    {"op":"ping","protocol":1}            → {"ok":true,"protocol":1}
    {"op":"call","kind":"filter",
     "args":[...],"kwargs":{...}}         → {"result": ...} / {"error":"..."}
    拦截器另有 preflight/inspect/bypass/note_* (见 net/extproc.py)
"""
import json
import os
import select
import subprocess
import time


class ExternalError(RuntimeError):
    pass


def is_external(spec):
    """声明成外部进程插件? 显式 type, 或只给了 command 没给 entry"""
    p = spec.get('params') or {}
    t = str(spec.get('type') or p.get('type') or '').lower()
    if t in ('external', 'process', 'stdio'):
        return True
    return (bool(spec.get('command') or p.get('command'))
            and not (spec.get('entry') or spec.get('module')))


def _field(spec, key, default=None):
    p = spec.get('params') or {}
    v = spec.get(key)
    return p.get(key, default) if v is None else v


def command_of(spec):
    cmd = _field(spec, 'command') or []
    return [str(x) for x in cmd] if not isinstance(cmd, str) else [cmd]


def timeout_of(spec, default=0.5):
    try:
        return float(_field(spec, 'timeout', default) or default)
    except (TypeError, ValueError):
        return default


class ExternalProcess:
    """一个常驻子进程 + 超时/崩溃隔离 (失败 30s 内不再拉起)"""

    def __init__(self, command, timeout=0.5):
        self.command = list(command or [])
        self.timeout = float(timeout or 0.5)
        self._proc = None
        self._buf = b''
        self._dead_until = 0.0
        self.last_error = ''

    # ── 生命周期 ──────────────────────────────────────────────────────
    def _spawn(self):
        if not self.command:
            raise ExternalError('未配置 command')
        try:
            self._proc = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0, close_fds=True)
        except Exception as e:                  # noqa: BLE001
            raise ExternalError('启动失败: %s' % e)
        self._buf = b''
        r = self._rpc('ping', protocol=1)
        if not r.get('ok'):
            raise ExternalError('ping 未通过')

    def _rpc(self, op, **payload):
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise ExternalError('进程已退出')
        msg = json.dumps({'op': op, **payload}, ensure_ascii=False, default=str) + '\n'
        try:
            proc.stdin.write(msg.encode('utf-8'))
            proc.stdin.flush()
        except Exception as e:                  # noqa: BLE001
            raise ExternalError('写入失败: %s' % e)
        deadline = time.time() + self.timeout
        while b'\n' not in self._buf:
            remain = deadline - time.time()
            if remain <= 0:
                raise ExternalError('响应超时 %.2fs' % self.timeout)
            ready, _, _ = select.select([proc.stdout], [], [], remain)
            if not ready:
                raise ExternalError('响应超时 %.2fs' % self.timeout)
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                raise ExternalError('进程已退出 (无响应)')
            self._buf += chunk
        line, self._buf = self._buf.split(b'\n', 1)
        line = line.strip()
        if not line:
            return {}
        try:
            return json.loads(line.decode('utf-8'))
        except Exception:                       # noqa: BLE001
            raise ExternalError('响应不是 JSON: %r' % line[:80])

    def _ready(self):
        if time.time() < self._dead_until:
            return False
        if self._proc is not None and self._proc.poll() is None:
            return True
        try:
            self._spawn()
        except Exception as e:                  # noqa: BLE001
            self.last_error = str(e)
            self._dead_until = time.time() + 30
            self.close()
            return False
        return True

    def call(self, op='call', **payload):
        """一次调用; 失败静默返回 None (外部插件不该拖垮主流程)"""
        if not self._ready():
            return None
        try:
            return self._rpc(op, **payload)
        except Exception as e:                  # noqa: BLE001
            self.last_error = str(e)
            self._dead_until = time.time() + 30
            self.close()
            return None

    def ping(self):
        if not self._ready():
            return False, self.last_error
        try:
            self._rpc('ping', protocol=1)
            return True, ''
        except Exception as e:                  # noqa: BLE001
            self.last_error = str(e)
            self.close()
            return False, str(e)

    def close(self):
        p, self._proc = self._proc, None
        self._buf = b''
        if p is not None:
            try:
                p.kill()
            except Exception:                   # noqa: BLE001
                pass


def probe(spec, name='<external>'):
    """体检: 起一次、ping 通、关掉 → (ok, 原因)"""
    proc = ExternalProcess(command_of(spec), timeout_of(spec, 0.5))
    if not proc.command:
        return False, '未配置 command'
    ok, err = proc.ping()
    proc.close()
    return ok, err or ('' if ok else '无法启动')


class ExternalCallable:
    """把任意类别的插件调用转成一个子进程调用

    Registry 在 items() 里给 type=external 的声明套上本代理, 因此 engines /
    filters / extractors 等拿到的是普通 callable, 不需要知道跨语言这回事。
    """

    missing = False

    def __init__(self, name, kind, spec):
        self.name = name
        self.kind = kind
        self.command = command_of(spec)
        self.timeout = timeout_of(spec, 0.5)
        self.proc = ExternalProcess(self.command, self.timeout)
        self.last_error = ''

    def __call__(self, *args, **kwargs):
        r = self.proc.call('call', kind=self.kind,
                           args=list(args), kwargs=dict(kwargs))
        self.last_error = self.proc.last_error
        if r is None:
            return None
        if r.get('error'):
            raise ExternalError('%s: %s' % (self.name, r['error']))
        return r.get('result')

    def ping(self):
        return self.proc.ping()

    def close(self):
        self.proc.close()
