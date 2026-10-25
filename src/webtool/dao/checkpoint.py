"""批任务断点: 已完成条目落盘, 重跑跳过

从 core/resilient 抽出 (P5, DAO 层): 断点是"存取"而不是"弹性策略",
与缓存/状态同为 dao 的职责。resilient 再导出旧名, 调用点无需改。
"""
import json
import os


class Checkpoint:
    """批任务断点: 已完成条目记进 ~/.webtool/cache/checkpoint-<名>.json

    用法: cp = Checkpoint('feed-20261015'); 剩余 = cp.pending(items, key)
    逐条完成调 cp.done(k); 全部完成 cp.clear()。文件损坏按没有算 (重跑)。
    """

    def __init__(self, name):
        self.path = os.path.join(
            os.path.expanduser('~/.webtool/cache'),
            'checkpoint-' + name.replace('/', '_') + '.json')
        self._done = set()
        try:
            with open(self.path, encoding='utf-8') as f:
                self._done = set(json.load(f))
        except (OSError, ValueError):
            pass

    def pending(self, items, key=str):
        return [it for it in items if key(it) not in self._done]

    def done(self, k):
        self._done.add(k)
        self._save()

    def clear(self):
        self._done.clear()
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(sorted(self._done), f)
            os.replace(tmp, self.path)
        except OSError:
            pass                       # 断点写不进只影响续跑, 不影响任务
