# -*- coding: utf-8 -*-
"""优雅关闭单测 —— 纯本地, 不联网

验证:
  1. thread_pool() 被打断时不 join 在飞任务, 进程能立刻退出 (daemon + 不登记 _threads_queues)
  2. 打断时未开始的任务被取消 (cancel_futures), 只跑起 workers 个
  3. Ctrl-C 一次: 协作退出 (KeyboardInterrupt)
  4. Ctrl-C 两次: 强制 os._exit(130) —— 卡在 C 调用/线程 join 里时的唯一出路

跑法: python3 tests/test_shutdown.py
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'src')

fails = []

def check(cond, msg, detail=''):
    print(('PASS' if cond else 'FAIL') + ' ' + msg + (' ' + detail if detail and not cond else ''))
    if not cond:
        fails.append(msg)


def _run(code, *, timeout=15, sigs=()):
    """在子进程里跑一段代码; sigs 是按秒延迟发的 SIGINT 列表; 返回 (rc, out, 秒)"""
    env = dict(os.environ, PYTHONPATH=SRC)
    t0 = time.time()
    p = subprocess.Popen([sys.executable, '-c', code], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True)
    _send = []
    if sigs:
        for delay in sigs:
            _send.append((t0 + delay, delay))
        # 用一个简单循环按时发信号, 同时等进程结束
        import threading
        def _sig_loop():
            for at, _d in _send:
                time.sleep(max(0.0, at - time.time()))
                if p.poll() is None:
                    p.send_signal(__import__('signal').SIGINT)
        th = threading.Thread(target=_sig_loop, daemon=True)
        th.start()
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, _ = p.communicate()
        return None, out, time.time() - t0
    return p.returncode, out, time.time() - t0


# ── 1. 打断后进程立刻退出 (不被 30s 的 worker 拖住) ──────────────────
_code1 = '''
import sys, time
from webtool.core.resilient import thread_pool
try:
    with thread_pool(2) as ex:
        ex.submit(time.sleep, 30)
        raise KeyboardInterrupt
except KeyboardInterrupt:
    print("exited")
'''
rc, out, dur = _run(_code1, timeout=20)
check(rc == 0 and 'exited' in out, '打断后正常收尾 (rc=0)', str(rc) + out)
check(dur < 8, '打断后不被在飞任务拖住 (秒=%.1f)' % dur)


# ── 2. 打断时取消未开始的任务 ────────────────────────────────────
_code2 = '''
import time
from webtool.core.resilient import thread_pool
started = []
def work(i):
    started.append(i); time.sleep(1)
futs = []
try:
    with thread_pool(2) as ex:
        futs = [ex.submit(work, i) for i in range(50)]
        time.sleep(0.3)
        raise KeyboardInterrupt
except KeyboardInterrupt:
    pass
print("started=%d cancelled=%d" % (len(started), sum(f.cancelled() for f in futs)))
'''
rc, out, dur = _run(_code2, timeout=20)
line = [l for l in out.splitlines() if l.startswith('started=')]
check(bool(line), '拿到统计行', out)
if line:
    started = int(line[0].split()[0].split('=')[1])
    cancelled = int(line[0].split()[1].split('=')[1])
    check(started <= 4, '只跑起 workers 个任务 (started=%d)' % started)
    check(cancelled >= 40, '未开始的任务被取消 (cancelled=%d)' % cancelled)


# ── 3+4. Ctrl-C 一次协作, 两次强制 ───────────────────────────────
_code3 = '''
import time
from webtool.core import shutdown
shutdown.install()
print("ready", flush=True)
try:
    while True:
        time.sleep(0.2)
except KeyboardInterrupt:
    print("first-caught", flush=True)
    while True:                 # 等第二次 → 应被 hard_exit
        time.sleep(0.2)
'''
rc, out, dur = _run(_code3, timeout=12, sigs=(0.8, 1.6))
check('ready' in out, '子进程已就绪', out)
check('first-caught' in out, '第一次 Ctrl-C 协作退出 (KeyboardInterrupt)', out)
check(rc == 130, '第二次 Ctrl-C 强制退出 130 (rc=%s)' % rc)
check(dur < 6, '强制退出很快 (秒=%.1f)' % dur)


print()
if fails:
    print('%d FAIL' % len(fails))
    sys.exit(1)
print('ALL PASS')
