"""模型输出上限: 从上游 400 报文里学到, 落盘记住, 下次直接照用

为什么要有这份文件: `--max-tokens` 的默认值 (200k) 不可能对所有模型都对 ——
各家上限从 8k 到 131k 不等, 而上游**只在你超了之后**才把上限告诉你。不记住的话
每次运行都要先撞一次墙 (一次白跑的请求 + 一段报错) 才降档; 记住了就一次到位。

学到的事实与**用户配置**分开放 (`zen_limits.json`, 不是 zen.json):
zen.json 是"我想要什么"(人手写、会被用户改), 这份是"上游告诉我是什么"(程序写、
只在 400 里更新)。混在一起的话, 用户改一次 max_tokens 就会把学到的事实冲掉,
而"改了没生效"这种事极难排查。

只在**上游明说**上限时才写: 从错误文案里抠不出数字就不记 —— 猜一个值记下来,
下次会静默用一个错的数字, 比每次撞墙还糟。
"""
import json
import os
import re
import time

from webtool.core.config_data import USER_DIR

# 落盘位置: ~/.webtool/zen_limits.json (跟 WEBTOOL_DIR 走)
STORE_FILE = 'zen_limits.json'

# 上限的合法区间: 抠出 0 / 999999999 这种数字多半是把报错里的**别的**数字
# 当成了上限 (比如 "max_tokens: 200000" 里那个被拒的值), 宁可不信。
_MIN_LIMIT = 1
_MAX_LIMIT = 10_000_000

# 抓"上限"而不是"被拒的值"。顺序即优先级 —— 越具体的写法排越前。
# 第一条是 Anthropic 风格: `max_tokens: 32000 > 16384, which is the maximum …`
# (被拒值和上限同时出现, 必须先认出 `>` 关系, 否则会抓成 32000)。
_PATTERNS = (
    r'max_tokens:\s*\d+\s*>\s*(\d+)',
    r'at most\s+(\d+)',
    r'less than or equal to\s+(\d+)',
    r'must be\s*<=\s*(\d+)',
    r'exceeds? the maximum[^0-9]{0,40}?(\d+)',
    r'maximum[^0-9]{0,40}?(\d+)',
)

# 报文里出现这些词才谈得上"这是 token 上限报错" —— 免得任何一句
# "maximum ... 123" 都被当成 token 上限。只要沾 'token' 就算 (各家写法太散:
# max_tokens / maxOutputTokens / max output tokens / completion tokens),
# 真正的把关交给下面的 _PATTERNS 和 context 排除。
_HINTS = ('token',)

# 命中片段里出现这些词就不是"输出上限" —— 最典型的是
# `maximum context length is 200000 tokens` (那是上下文窗口, 不是回复上限),
# 记错的话下次会拿一个毫不相干的数字当上限。
_NOT_LIMIT = ('context', 'input')


def parse_limit(body):
    """从 400 报文里抠出模型输出上限; 抠不出 → None

    各家文案完全不同 (OpenAI 兼容 / Anthropic / Gemini), 只认**明确表达上限**
    的写法。宁可返回 None (下次再撞一次) 也不能猜错 —— 记错的值会被静默沿用。
    """
    if not body:
        return None
    low = str(body).lower()
    if not any(h in low for h in _HINTS):
        return None
    for pat in _PATTERNS:
        m = re.search(pat, str(body), re.I)
        if not m:
            continue
        if any(w in m.group(0).lower() for w in _NOT_LIMIT):
            continue
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if _MIN_LIMIT <= n <= _MAX_LIMIT:
            return n
    return None


def _path():
    return os.path.join(str(USER_DIR), STORE_FILE)


def load():
    """全部记住的上限: {model: {'max_tokens', 'at', 'hits', 'source'}}

    文件坏了当空 —— 这份是"加分项", 读不出来只是回到"撞一次墙", 不该让 zen
    整个不可用。
    """
    try:
        with open(_path(), encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict) and isinstance(v.get('max_tokens'), int):
            out[str(k)] = v
        elif isinstance(v, int):                  # 手写简写: {"m": 8192}
            out[str(k)] = {'max_tokens': v}
    return out


def limit_for(model):
    """这个模型记住的上限; 没有 → None"""
    if not model:
        return None
    rec = load().get(str(model))
    return rec.get('max_tokens') if rec else None


def _save(d):
    p = _path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = '%s.tmp%d' % (p, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except OSError:
        return False
    return True


def remember(model, limit, source='上游 400'):
    """记下模型上限 → (是否写成功, 是否是新值)

    同一个上限再学到一次只累加 hits (用来判断"上游真的一直这么说");
    上限变了就覆盖 —— 模型的实际上限被上游调过是常事, 死守旧值会一直撞墙。
    """
    if not model or not isinstance(limit, int) or not _MIN_LIMIT <= limit <= _MAX_LIMIT:
        return False, False
    d = load()
    key = str(model)
    rec = d.get(key) or {}
    fresh = rec.get('max_tokens') != limit
    d[key] = {'max_tokens': limit,
              'hits': (0 if fresh else int(rec.get('hits') or 0)) + 1,
              'at': time.strftime('%Y-%m-%d %H:%M:%S'),
              'source': source}
    return _save(d), fresh


def forget(model=None):
    """忘掉记住的上限: 给了 model 只忘那个, 否则全忘。返回清掉的条数"""
    d = load()
    if model:
        n = 1 if d.pop(str(model), None) is not None else 0
    else:
        n = len(d)
        d = {}
    _save(d)
    return n


def clamp(model, requested):
    """(该用的值, 被记住的上限 或 None)

    requested 超了记住的上限就降到上限; 没记住、没给值、或没超, 原样返回。
    返回第二项让调用方能说清"我按记住的值降了档" —— 静默改掉用户给的数字
    会让人以为 200k 生效了。
    """
    lim = limit_for(model)
    if not lim or not requested:
        return requested, None
    try:
        req = int(requested)
    except (TypeError, ValueError):
        return requested, None
    if req <= lim:
        return requested, None
    return lim, lim


def describe(rows=None):
    """人读摘要, 给 `webtool zen --limits` 用 → [str]"""
    d = load() if rows is None else rows
    if not d:
        return ['还没有记住任何模型的上限 —— 上游在 400 里报了上限之后才会记下']
    out = ['记住的模型输出上限 (来自上游报错; 文件 %s)' % _path()]
    for m in sorted(d):
        r = d[m]
        out.append('  %-34s %8d  %s  确认 %s 次%s'
                   % (m, r['max_tokens'], r.get('at') or '-',
                      r.get('hits') or 1,
                      ('  [%s]' % r['source']) if r.get('source') else ''))
    out.append('请求的 --max-tokens 超过这些值时会自动降档 (并说明)。'
               '要忘掉: webtool zen --forget-limits [--model <名>]')
    return out
