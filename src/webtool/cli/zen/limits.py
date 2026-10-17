"""模型输出上限: 优先从模型目录预取, 落盘记住; 目录拿不到再从上游 400 里学

为什么要有这份文件: `--max-tokens` 的默认值 (200k) 不可能对所有模型都对 ——
各家上限从 8k 到 131k 不等, 而上游**只在你超了之后**才把上限告诉你。不记住的话
每次运行都要先撞一次墙 (一次白跑的请求 + 一段报错) 才降档; 记住了就一次到位。

两条来源, 分工明确:
  1. **模型目录** (models.dev 的 opencode 提供方, 字段 limit.output) —— 主路径,
     见 refresh_from_catalog()。拿到的值是上游**主动公布**的, 不是猜的。
  2. **上游 400 报文** (parse_limit) —— 兜底, 目录没覆盖到时用。

早期只有第 2 条, 代价有两个: 每个新模型的第一次请求**必定失败一次**;
上游改一次措辞, 反推就**静默**失效。现改为第 1 条打底。

学到的事实与**用户配置**分开放 (`zen_limits.json`, 不是 zen.json):
zen.json 是"我想要什么"(人手写、会被用户改), 这份是"上游告诉我是什么"(程序写)。
混在一起的话, 用户改一次 max_tokens 就会把学到的事实冲掉, 而"改了没生效"
这种事极难排查。

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

# ── 模型目录 (主路径) ─────────────────────────────────────────────────
# 数据来源: models.dev 的 opencode 提供方目录 (字段 limit.output)。
# 上游 /v1/models 只回 id/object/created/owned_by, **不带上限**, 所以上限只能
# 从这里拿, 或者从 400 报文里反推。
CATALOG_URL = 'https://models.dev/api.json'
CATALOG_PROVIDER = 'opencode'
CATALOG_FILE = 'model_catalog.json'

# 目录默认 7 天不重复抓 —— 上限不是分钟级会变的东西, 每次运行都联网既慢又
# 没必要。抓取全程 best-effort: 失败沿用旧值, 绝不阻断请求。
_CATALOG_TTL = 168 * 3600

# 但失败后不能还按 7 天算 —— 那意味着接下来一周都不再尝试。给个短窗口, 让
# 临时故障 (断网 / 代理抽风) 过去后能自动恢复, 又不至于每次调用都去重试。
_CATALOG_RETRY = 15 * 60


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


# ── 目录抓取 (主路径) ───────────────────────────────────────────────────

def _sane(v):
    """目录里的 limit.output 也可能是 null / 字符串 / 离谱值, 一律按不信处理"""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if _MIN_LIMIT <= v <= _MAX_LIMIT else None


def _catalog_path():
    return os.path.join(str(USER_DIR), CATALOG_FILE)


def _fetch_text(url):
    """按 url 取文本。HTTP 只走 netx 一处 (代理 / TLS / 大小限制都在那儿)"""
    from webtool.net import netx
    text, status = netx.get(url, kind='nav')
    if status and int(status) >= 400:
        raise ValueError('HTTP %s' % status)
    return text


def _catalog_meta():
    """(上次尝试时间戳, 是否新鲜)。文件坏了当不新鲜 → 触发重抓

    记的是**尝试**时间而不是成功时间: 抓失败时也要落盘, 否则网络一断, 每次
    zen 调用都会重拉一遍 5.7MB (每次还带一轮超时), 请求根本发不出去。失败只
    是把新鲜窗口缩到 _CATALOG_RETRY, 数据本身仍旧是上次的好值。
    """
    try:
        with open(_catalog_path(), encoding='utf-8') as f:
            ts = int(json.load(f).get('ts') or 0)
    except (OSError, ValueError, TypeError):
        return 0, False
    return ts, bool(ts) and time.time() - ts < _CATALOG_TTL


def _touch_catalog():
    """落盘"上次尝试时间"。写不了就算了 —— 只是多抓一次, 不影响请求"""
    try:
        os.makedirs(os.path.dirname(_catalog_path()), exist_ok=True)
        tmp = '%s.tmp%d' % (_catalog_path(), os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'ts': int(time.time()), 'source': CATALOG_URL},
                      f, ensure_ascii=False)
        os.replace(tmp, _catalog_path())
    except OSError:
        pass


def refresh_from_catalog(force=False, only=None, fetch_text=None):
    """从模型目录预取上限 → 写进上限表 → 目录条目数

    `only` = 真正调得动的那些模型 id; 目录里上百个模型绝大部分调不了, 全塞进
    上限表只会虚胖, 所以调用方最好先问上游再传交集。None = 不过滤。
    `fetch_text(url) -> str` 默认走 netx (代理 / TLS / 大小限制都在那儿),
    可注入替换以便测试。

    整份目录约 5.7MB, 为省内存只在**文本层**把 opencode 那一段抠出来再解析,
    不把整棵树建成对象。失败返回旧表条数, 不抛 —— 这份是"加分项", 抓不到就
    退回 400 反推, 不该让 zen 整个不可用。
    """
    ts, fresh = _catalog_meta()
    if not force and fresh:
        return len(load())
    if fetch_text is None:
        fetch_text = _fetch_text
    # 先看上次失败后是否已经过了重试窗口, 别在短时间内反复抓
    if not force and ts and time.time() - ts < _CATALOG_RETRY:
        return len(load())
    try:
        text = fetch_text(CATALOG_URL)
        prov = extract_provider(text, CATALOG_PROVIDER)
        if prov is None:
            raise ValueError('目录里没找到提供方 ' + CATALOG_PROVIDER)
        models = prov.get('models')
        if not isinstance(models, dict):
            raise ValueError('提供方 %s 没有 models' % CATALOG_PROVIDER)
        out = {}
        for mid, m in models.items():
            if only is not None and mid not in only:
                continue
            if not isinstance(m, dict):
                continue
            lim = _sane((m.get('limit') or {}).get('output'))
            if lim is not None:
                out[str(mid)] = lim
        # `only` 过滤后为空是**正常情况** (这个模型压根不在目录里), 不是故障 ——
        # 不该当错误重试, 更不该因此清掉已有值。目录本身没抠出东西才算失败。
        if not out and only is None:
            raise ValueError('目录里没抠出任何带上限的模型')
    except Exception:
        # 抓不到就用旧的: 宁可沿用上次的上限, 也不要清空成"什么都不知道"
        _touch_catalog()
        return len(load())

    d = load()
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    for mid, lim in out.items():
        rec = d.get(mid) or {}
        if rec.get('max_tokens') == lim:
            continue                      # 值没变就不重写, 免得把 hits 冲掉
        d[mid] = {'max_tokens': lim,
                  'hits': int(rec.get('hits') or 0),
                  'at': stamp,
                  'source': CATALOG_URL}
    if out:
        _save(d)
    _touch_catalog()                      # 成功也落时间戳, 否则每次都重抓
    return len(out)


def extract_provider(text, provider):
    """从整份目录 JSON 里抠出某个 provider 的对象 → dict 或 None"""
    block = extract_object(text, provider)
    if block is None:
        return None
    try:
        v = json.loads(block)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def extract_object(text, key):
    """抠出 `"<key>": { ... }` 的那段原文, 抠不出 → None

    只认"作为 key 出现"的形式 (后面跟 : 和 {), 且括号配对时跳过字符串字面量里
    的括号与转义, 所以 `"id": "opencode"` 这类**值**不会误命中。
    """
    if not text or not key:
        return None
    needle = '"%s"' % key
    n = len(needle)
    pos = 0
    while True:
        i = text.find(needle, pos)
        if i < 0:
            return None
        j = i + n
        while j < len(text) and text[j].isspace():
            j += 1
        if j < len(text) and text[j] == ':':
            j += 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j < len(text) and text[j] == '{':
                end = match_brace(text, j)
                if end > j:
                    return text[j:end + 1]
        pos = i + n


def match_brace(s, start):
    """返回与 start 处 '{' 配对的 '}' 下标; 找不到 → -1"""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1


def floor_limit():
    """表里已知的最小输出上限。

    目录里查不到的模型按它保守处理 —— 宁可少要一点, 也不盲发一次注定被上游
    打回的请求。代价是长输出可能被压短, 所以调用方必须把"用了 floor 兜底"
    这件事打进日志, 不能静默。
    """
    vals = [r['max_tokens'] for r in load().values()]
    return min(vals) if vals else 0


def clamp(model, requested):
    """(该用的值, 被记住的上限 或 None)

    requested 超了记住的上限就降到上限; 没记住、没给值、或没超, 原样返回。
    返回第二项让调用方能说清"我按记住的值降了档" —— 静默改掉用户给的数字
    会让人以为 200k 生效了。

    目录里查不到这个模型时用 floor_limit() 兜底, 不盲发 —— 表整个是空的
    (一次都没抓到) 才原样放行, 那时确实无从判断。
    """
    lim = limit_for(model)
    if lim is None:
        floor = floor_limit()
        if floor <= 0:
            return requested, None
        lim = floor
    if not requested:
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
    out = ['记住的模型输出上限 (来自模型目录或上游报错; 文件 %s)' % _path()]
    for m in sorted(d):
        r = d[m]
        out.append('  %-34s %8d  %s  确认 %s 次%s'
                   % (m, r['max_tokens'], r.get('at') or '-',
                      r.get('hits') or 1,
                      ('  [%s]' % r['source']) if r.get('source') else ''))
    floor = floor_limit()
    if floor:
        out.append('目录里查不到的模型会按最保守值 %d 兜底 (不盲发)。' % floor)
    out.append('请求的 --max-tokens 超过这些值时会自动降档 (并说明)。'
               '要忘掉: webtool zen --forget-limits [--model <名>]')
    return out
