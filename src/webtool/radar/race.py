"""并发竞速: 多个 RSSHub 公共实例同时发请求, 取最先成功的若干个

用法是 race(dict_of_callables) —— 每个 job 返回 (结果, 耗时), ok 判定该
结果是否有效, need 指定要凑够几个有效结果。挂掉的实例不 join, 随进程退出。
"""


def race(jobs, ok=None, timeout=None, need=None):
    """并发跑 {key: callable}

    need=None: 等到第一个满足 ok 的就返回 (results 只含已完成的 key)。
    need=N  : 等 N 个满足 ok 的。
    need=-1 : 等全部跑完 (早退会把没回来的记成未知)。

    用 daemon 线程而不是 ThreadPoolExecutor: 后者在解释器退出时会 join 所有
    worker, 而这里恰恰要放弃还没回来的慢/挂请求; daemon 线程不阻塞退出。
    """
    import threading
    ok = ok or (lambda r: bool(r))
    results, lock, done = {}, threading.Lock(), threading.Event()
    left = [len(jobs)]
    hits = [0]

    def run(key, fn):
        try:
            r = fn()
        except Exception:
            r = None
        with lock:
            results[key] = r
            left[0] -= 1
            if ok(r):
                hits[0] += 1
            if need == -1:
                finished_enough = left[0] <= 0        # 等全部
            elif need:
                finished_enough = hits[0] >= need      # 等够 N 个
            else:
                finished_enough = True                 # 等第一个
        if finished_enough or left[0] <= 0:
            done.set()

    threads = [threading.Thread(target=run, args=(k, fn), daemon=True)
               for k, fn in jobs.items()]
    for t in threads:
        t.start()
    done.wait(timeout)
    return results
