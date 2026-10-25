"""Zen 的 OpenAI 兼容协议细节: 端点/认证头/请求体/流式解析/ID 生成

认证: 免费层用占位 `Bearer public`, 不需要真 key。

免费层两道闸门 (判据取自官方 1.19.0 的实际报文):
  1. 请求头要够像官方客户端: 缺 User-Agent / x-opencode-session-id /
     Authorization 任一项 → 403; 大小写、顺序、Accept-Encoding、Connection 不敏感。
  2. body 里的 tools + tool_choice: 必须是真机原版 schema (瘦 schema / 空壳凑数都
     不行), tool_choice=auto (none 直接 403); 最小可用集 bash+read 两个, 缺一个即拒。
两条任一不满足即 FreeTierError。system/user 文本、模型 id 之外的消息内容都不参与判定。
"""
import json
import secrets
import time
import urllib.parse
from pathlib import Path

from webtool.core.config_data import USER_DIR

# 形状由 ai-sdk 拼: `<provider名>/<版本> ai-sdk/provider-utils/<版本> runtime/bun/<版本>`
# 版本号取自已发布的官方 CLI (npm opencode-ai 的 latest 与其二进制里的常量)
USER_AGENT = 'opencode/1.19.0 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14'

# 免费层只在这条端点放行, /zen/v1/* 一律 403 (models 清单仍走 zenv1)
CHAT_URL = 'https://opencode.ai/inference/v1/chat/completions'
MODELS_URL = 'https://opencode.ai/zen/v1/models'

STICKY_FILE = 'sticky.json'   # 粘性会话 id 的落盘位置 (USER_DIR 下)
STICKY_PERIOD = 3600          # 轮换粒度: 按整点切 (bucket = floor(now/period))

DEFAULT_SYSTEM = "You are a helpful assistant. Be brief."
TOOL_CHOICES = ("none", "auto", "required")

# 请求默认值。命令行显式给的值优先, 其次 ~/.webtool/zen.json 的 zen 段, 最后这里。
# max_tokens 取 200k: 上游不校验上限, 给足即可 (具体模型自己截断)。
DEFAULT_MAX_TOKENS = 200000
DEFAULT_THINK = 'medium'
DEFAULTS = {
    'model': 'big-pickle',
    'system': None,
    'tool_choice': 'auto',
    'tools': 'min',
    'reasoning_effort': DEFAULT_THINK,
    'max_tokens': DEFAULT_MAX_TOKENS,
    'live': True,
}

def defaults():
    """zen 的可配置默认值: 包内 data/zen.json + ~/.webtool/zen.json 的 zen 段叠加

    优先级: 命令行 > 配置文件 > 内置 (见 DEFAULTS)。只认 DEFAULTS 里列出的键,
    写错的键不会有任何作用 (也不会报错) —— 与其它配置段同一套合并语义。
    `extra_body` 例外: 它是**原样并进请求体的字典**, 用来补上游新加的字段
    (如 thinking / 别的提供商扩展), 内容不做任何校验。
    """
    from webtool.core.config_data import load as _cfg_load
    d = _cfg_load('zen', 'zen.json') or {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        v = d.get(k)
        if v is not None and v != '':
            out[k] = v
    out['extra_body'] = d.get('extra_body') or {}
    return out

# 真机 12 个工具定义 (字段照抄 data/zen_tools.json, 未改写)。
# 闸门判据不在于数量: 每个 tool 都得是真机原版 schema, 且 bash 与 read 缺一不可;
# 只要一个 / 瘦 schema / 空壳凑数 / 重复项都会被 403。
DEFAULT_TOOL_NAMES = ('bash', 'read')
_TOOLS = []


def tools(names=None):
    """真机工具定义 (data/zen_tools.json, 原样)

    names=None → 闸门最小集 (bash+read, 体积最小)
    names='all' → 全部 12 个
    """
    global _TOOLS
    if not _TOOLS:
        from webtool.core.config_data import DATA_DIR
        from webtool.core import jsonfmt
        _TOOLS = jsonfmt.read(DATA_DIR / 'zen_tools.json').get('tools') or []
    if names == 'all':
        return _TOOLS
    want = names or DEFAULT_TOOL_NAMES
    return [t for t in _TOOLS if t['function']['name'] in want]


SHOW_VIEWS = ('request', 'headers', 'body', 'text')


def resolve_tool_names(spec=None):
    """`--tools` 取值 → `build_body(tool_names=...)` 的参数

    min/空 → None (闸门最小集 bash+read)
    all    → 'all' (真机 12 个)
    其余   → 逗号/空格切分的名字表 (如 `bash,read,grep`)
    """
    s = (spec or '').strip().lower()
    if not s or s in ('min', 'minimal'):
        return None
    if s == 'all':
        return 'all'
    return [n for n in s.replace(' ', ',').split(',') if n]


def request_preview(model, prompt, system=None, tool_choice=None,
                    tool_names=None, ses_id=None, msg_id=None, url=None,
                    reasoning_effort=None, max_tokens=None, messages=None,
                    tool_defs=None):
    """将要发出的请求 (不出网): {method, url, headers, body}

    与 `call_zen` 走同一套 `build_body` / `build_headers` / `_endpoints`,
    所以看到的就是真会发的 —— 排查免费层闸门时头与体都得能看见。
    headers 给的是**服务端视角**: 在本函数调用的头之上套了 urllib/http.client
    实际会做的改写, 与官方客户端的 13 个头一一对应:
      Host、Content-Length    http.client 补 (值是真: URL 的主机 + 这份体的字节数)
      Connection: close       urllib 写死 (真机是 keep-alive, 我们发不出去)
      头名 .title()           x-opencode-session → X-Opencode-Session (真机小写)
    顺序: 我们的 10 个在前, 库补的两个 + Connection 追加在后; HTTP 头顺序无语义, 看集合。
    """
    body_bytes = build_body(model, prompt, system, tool_choice, tool_names,
                            reasoning_effort, max_tokens, messages=messages,
                            tool_defs=tool_defs)
    url = url or _endpoints()[0]
    wire = {k.title(): v for k, v in build_headers(ses_id, msg_id).items()}
    wire['Connection'] = 'close'                  # urllib 写死的, 不是我们的选择
    wire['Host'] = urllib.parse.urlsplit(url).netloc
    wire['Content-Length'] = str(len(body_bytes))
    return {'method': 'POST', 'url': url, 'headers': wire,
            'body': json.loads(body_bytes)}


_BASE62 = ('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
           'abcdefghijklmnopqrstuvwxyz')


class IDGen:
    def __init__(self):
        self.last_ts = 0
        self.counter = 0

    def gen(self, descending=False, timestamp_ms=None):
        ts = timestamp_ms or int(time.time() * 1000)
        if ts != self.last_ts:
            self.counter = 0
            self.last_ts = ts
        self.counter += 1
        # 48 位 = 12 hex 字符, 与官方 id 的 hex 段等宽 (真机: msg_13af12f48001…)
        # 早先没掩码: ms 时间戳 ×0x1000 是 53 位 → hex 段 14 位, 整个 msg_ id 长 32
        # 而真机是 30, 即畸形 id —— 已修, 别退回。
        cur = (ts * 0x1000 + self.counter) & ((1 << 48) - 1)
        if descending:
            cur = (~cur) & ((1 << 48) - 1)
        rand = ''.join(_BASE62[b % 62] for b in secrets.token_bytes(14))
        return format(cur, '012x') + rand


_ID = IDGen()


def make_session_id():
    return 'ses_' + _ID.gen(descending=True)


def make_message_id():
    return 'msg_' + _ID.gen()


class StickySession:
    """固定 ses_id 跨请求/跨进程复用, **每整点换一个**

    轮换按整点对齐: bucket = floor(now / 3600), 小时数一变就换新 id ——
    所以新 ses_id 总在 HH:00:00 那一刻生效, 而不是"距上次创建满一小时"
    (10:59 建的, 11:00 就换)。状态存 `~/.webtool/sticky.json`:
    `{session_id, bucket, created}`; `WEBTOOL_DIR` 可改目录, `--no-sticky`
    退回"每次运行都新生成"。

    只固定 ses_id; msg/request id 照旧逐请求换新。
    """

    def __init__(self, period=STICKY_PERIOD, path=None):
        self.period = period
        self.path = Path(path) if path else (USER_DIR / STICKY_FILE)
        self.bucket = int(time.time() // period)
        self.ses_id, self.created = self._load()

    def _load(self):
        now = time.time()
        try:
            d = json.loads(self.path.read_text(encoding='utf-8'))
            sid = d['session_id']
            if str(sid).startswith('ses_') and int(d.get('bucket', -1)) == self.bucket:
                return sid, float(d.get('created', now))
        except (OSError, ValueError, KeyError, TypeError):
            pass                                   # 缺文件/坏 JSON/字段怪 → 重建
        sid, created = make_session_id(), now
        try:                                       # 落盘失败不该拦下请求
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({'session_id': sid, 'bucket': self.bucket,
                            'created': created}), encoding='utf-8')
        except OSError:
            pass
        return sid, created

    def headers(self, msg_id=None):
        """每次请求换新的 msg/request id, ses_id 固定"""
        return build_headers(self.ses_id, msg_id or make_message_id())


def _endpoints():
    """端点: 包内 data/zen.json + ~/.webtool/zen.json 叠加 (mtime 热生效),
    文件缺失/无值回落内置常量"""
    from webtool.core.config_data import load as _cfg_load
    d = _cfg_load('zen', 'zen.json') or {}
    return (d.get('chat_url') or CHAT_URL,
            d.get('models_url') or MODELS_URL)


def build_headers(ses_id=None, msg_id=None):
    """占位 Bearer public + x-opencode-* 会话/指纹头, 逐项对齐官方客户端 1.19.0

    13 个头, 顺序照抄 (x-opencode-request 在 session 之前):
      Authorization: Bearer public
      User-Agent: opencode/1.19.0 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14
      x-opencode-client: cli          x-opencode-project: global
      x-opencode-request: msg_<24位>  x-opencode-session: ses_<12位hex><14位base62>
      x-opencode-session-id: <同 x-opencode-session 的值>
      Accept: */*                     Accept-Encoding: gzip, deflate, br, zstd
    另有三个头不由我们写: Host / Content-Length 由 http.client 补; Connection 被
    urllib 写死成 close (它不复用连接), 叠进 headers 是死代码。

    两处与真机不可控的差异 (不影响闸门):
      ① 头名被 urllib `.title()` 规范化: x-opencode-session → X-Opencode-Session
      ② Accept-Encoding 抄了真机, 上游真压缩时由 zen.py 的 `_unzipper` 增量解
         (gzip/deflate; br/zstd 明确报错)
    """
    ses = ses_id or make_session_id()
    return {
        'Authorization': 'Bearer public',
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT,
        'x-opencode-client': 'cli',
        'x-opencode-project': 'global',
        'x-opencode-request': msg_id or make_message_id(),
        'x-opencode-session': ses,
        'x-opencode-session-id': ses,
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
    }


def model_headers():
    """列模型用的头: 认证同源, 但不带会话/指纹头 (列表接口不吃这些)"""
    return {'Accept': 'application/json', 'User-Agent': USER_AGENT,
            'Authorization': 'Bearer public'}


def build_body(model, prompt=None, system=None, tool_choice=None, tool_names=None,
               reasoning_effort=None, max_tokens=None, extra=None, messages=None,
               tool_defs=None):
    """OpenAI Chat Completions 请求体

    tools 用真机定义、tool_choice 默认 auto —— 两者都是闸门判据 (见文件头注释)。
    `reasoning_effort` 只在显式给值时带上 (可选值随模型而异, 见 zen --think)。
    `extra` (默认取 zen.json 的 extra_body) 原样并入, 同名字段以它为准。

    `messages` 给了就**原样**当整个会话 (多轮循环用), prompt/system 不再拼;
    不给才走两消息的默认形状。`tool_defs` 是**已筛好的工具定义列表**, agent
    模式自己挑子集时从这走 —— 筛选逻辑只在 tools() 一处, 别再写一份。
    """
    body = {
        'model': model,
        'max_tokens': max_tokens or DEFAULT_MAX_TOKENS,
        'messages': ([{'role': 'system', 'content': system or DEFAULT_SYSTEM},
                      {'role': 'user', 'content': prompt or ''}]
                     if messages is None else messages),
        'tools': tool_defs if tool_defs is not None else tools(tool_names),
        'tool_choice': tool_choice or 'auto',
        'stream': True,
        'stream_options': {'include_usage': True},
    }
    if reasoning_effort:
        body['reasoning_effort'] = reasoning_effort
    if extra is None:
        extra = defaults().get('extra_body') or {}
    if extra:
        body.update(extra)          # 原样并入: thinking 之类的上游字段从这走
    return json.dumps(body, ensure_ascii=False).encode('utf-8')


def parse_models_full(data):
    """模型清单 dict → [{id, created, owned_by}]

    只搬接口原样给的字段, 不做任何推断 —— 上游哪天多给一列(上下文/价格),
    这里加一行就能进表; 少给的字段补 None, 界面不用为空值让步。
    """
    out = []
    for m in (data or {}).get('data') or []:
        if isinstance(m, dict) and m.get('id'):
            out.append({'id': m['id'], 'created': m.get('created'),
                        'owned_by': m.get('owned_by')})
    return out


def parse_sse(lines):
    """choices/delta 形状 → 五元组"""
    for line in lines:
        line = line.strip()
        if not line.startswith('data:'):
            continue
        payload = line[5:].strip()
        if not payload or payload == '[DONE]':
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(evt, dict) and evt.get('error'):
            err = evt['error']
            msg = (err.get('message') if isinstance(err, dict) else None) or str(err)
            yield '', '', [], evt.get('usage'), str(msg)[:300]
            continue
        text = reason = ''
        calls = []
        finish = None
        for choice in evt.get('choices') or []:
            delta = choice.get('delta') or {}
            if delta.get('content'):
                text += delta['content']
            for key in ('reasoning', 'reasoning_content'):
                if delta.get(key):
                    reason += delta[key]
            for tc in (delta.get('tool_calls') or []):
                fn = tc.get('function') or {}
                calls.append({'index': tc.get('index', 0),
                              'id': tc.get('id'),
                              'type': tc.get('type'),
                              'name': fn.get('name'),
                              'arguments': fn.get('arguments') or ''})
            if choice.get('finish_reason'):
                finish = choice['finish_reason']
        usage = evt.get('usage')
        err = None
        if finish == 'tool_calls':
            err = '__TOOLCALLS__'
        elif finish and finish != 'stop':
            err = 'finish_reason=%s' % finish
        if text or reason or calls or usage or err:
            yield text, reason, calls, usage, err

