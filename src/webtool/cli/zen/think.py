"""思考标签切分 (zen): 整段定性 split_think + 流式 _ThinkSplitter + 终端着色开关

从 cli/zen/client.py 拆出 (P4): 与请求编排/重试无关, 纯文本处理 + 终端能力判定。
client 仍再导出这些名字, 老引用无需改。
"""
import os
import sys

_THINK_TAGS = ('<think>', '<thinking>', '<reasoning>')

_END_THINK_TAGS = ('</think>', '</thinking>', '</reasoning>')


def split_think(text):
    """把混在正文里的思考标签剥出来 → (思考, 正文)

    有些模型不走 reasoning 通道, 而是把思考直接写进 content 并用 `</think>`
    之类标签包着 (上游偶尔只留闭标签)。见到闭标签: 它前面的是思考, 后面才是
    答案。只有开标签没有闭标签 (被截断) 则整段算思考。没有标签原样返回。
    """
    if not text:
        return '', text
    low = text.lower()
    hit = None                                # (位置, 标签)
    for tag in _END_THINK_TAGS:
        i = low.find(tag)
        if i != -1 and (hit is None or i < hit[0]):
            hit = (i, tag)
    if hit is None:
        for tag in _THINK_TAGS:
            if tag in low:
                return text, ''
        return '', text
    i, tag = hit
    return text[:i], text[i + len(tag):].lstrip('\n')


class _ThinkSplitter:
    """流式剥思考标签: 标签绝不原样打到屏幕, 标签内的文字算思考。

    标签可能被切成两个 chunk, 所以尾部的"可能是标签前缀"的部分先扣在手里,
    等下一个 chunk 到了再判。分类只影响**渲染**(上文是否算思考), 最终正文由
    `split_think` 在整段上定性, 两者一致。
    """

    _TAGS = _THINK_TAGS + _END_THINK_TAGS
    _MAX = max(len(t) for t in _TAGS)

    def __init__(self):
        self.pending = ''
        self.in_think = False

    def _classify(self, piece):
        return ('think' if self.in_think else 'text', piece)

    def feed(self, chunk):
        self.pending += chunk
        out = []
        while True:
            low = self.pending.lower()
            hit = None
            for tag in self._TAGS:
                i = low.find(tag)
                if i != -1 and (hit is None or i < hit[0]):
                    hit = (i, tag)
            if hit is None:
                break
            i, tag = hit
            if self.pending[:i]:
                out.append(self._classify(self.pending[:i]))
            self.in_think = not tag.startswith('</')
            self.pending = self.pending[i + len(tag):]
        keep = 0
        low = self.pending.lower()
        for tag in self._TAGS:                     # 扣住可能是标签开头的尾巴
            for n in range(min(len(tag) - 1, len(low)), 0, -1):
                if low.endswith(tag[:n]):
                    keep = max(keep, n)
                    break
        if keep:
            ready, self.pending = self.pending[:-keep], self.pending[-keep:]
        else:
            ready, self.pending = self.pending, ''
        if ready:
            out.append(self._classify(ready))
        return out

    def flush(self):
        out = [self._classify(self.pending)] if self.pending else []
        self.pending = ''
        return out


def _color_on():
    """终端着色开关: 非终端 / NO_COLOR 一律不上色 (管道与日志里不该混转义序列)"""
    if os.environ.get('NO_COLOR'):
        return False
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False
