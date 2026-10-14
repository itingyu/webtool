"""Zen 的 OpenAI 兼容协议细节: 端点/认证头/请求体/流式解析/ID 生成

只有一个协议, 所以都是普通函数而不是策略类 —— 真要接第二种协议时再抽基类。

认证: 免费层用占位 `Bearer public`, 不需要真 key。

免费层闸门的两道判据 (2026-10-14 用官方 1.19.0 抓包逐项二分坐实):
  1. 请求头要够像官方客户端。缺 User-Agent / x-opencode-session-id /
     Authorization 任一项 → 403; 大小写、顺序、Accept-Encoding、Connection
     不敏感。头这一侧照 build_headers 发就行。
  2. body 里的 tools + tool_choice。必须是真机原版 schema (自造瘦 schema / 空壳
     凑数都不行)、tool_choice=auto (none 直接 403)。最小可用集是 bash+read 两个,
     只要 read 或只要 bash 都会被拒。见 tools()。
两条任一不满足即 FreeTierError; 两条都满足才 200 流式。system/user 文本、
模型 id 之外的消息内容都不参与判定。
"""
import json
import secrets
import time
import urllib.parse
from pathlib import Path

from webtool.core.config_data import USER_DIR

# 三段各有出处, 别随手改:
#   opencode/<版本>            = 已发布 CLI 的版本 (npm opencode-ai 的 latest)
#   ai-sdk/provider-utils/...  = 取自已发布 CLI 二进制里的常量 (1.19.0 里是 4.0.23)
#   runtime/bun/...            = 同上, 二进制里嵌的运行时串 `bun/1.3.14`
# 形状由 ai-sdk 拼: `<provider名>/<版本> ai-sdk/provider-utils/<版本> runtime/bun/<版本>`
USER_AGENT = 'opencode/1.19.0 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14'

# 官方 1.19.0 交互式会话打的端点 (2026-10-14 抓包)。旧的 /zen/v1/... 是另一条
# 服务, 免费层在那边一律 403; 换到这条 + 补齐 body 后才 200。
CHAT_URL = 'https://opencode.ai/inference/v1/chat/completions'
MODELS_URL = 'https://opencode.ai/zen/v1/models'

STICKY_FILE = 'sticky.json'   # 粘性会话 id 的落盘位置 (USER_DIR 下)
STICKY_PERIOD = 3600          # 轮换粒度: 按整点切 (bucket = floor(now/period))

DEFAULT_SYSTEM = "You are a helpful assistant. Be brief."
TOOL_CHOICES = ("none", "auto", "required")

# 真机 12 个工具定义 (2026-10-14 从官方 1.19.0 抓包提取, 未做任何改写)。
# 为什么必须真发: 免费层闸门把 body 也算进判据 —— 实测 (头用真机不变)
#   tool_choice=none        → 403        tools 只有我们自己写的瘦 schema → 403
#   tools 为空              → 403        前 6 个真机工具               → 200
#   system/user 文本随意      → 200        只留 1 个真机工具             → 403
# 即: tools 要给得像真的 + tool_choice=auto, 少一个就回 FreeTierError。
# 闸门放行所需的最小集: 真机 schema 里必须同时有 bash 和 read。
# 实测 (2026-10-14, 请求头保持真机形态):
#   只要 read / 只要 bash / [bash,edit] / 前 5 个真机工具   → 403
#   [bash,read] / 前 6 个 / 6 个不含 question                → 200
#   read 重复 6 次 / bash+read + 4 个空壳凑数                → 403
# 即: 每个 tool 都得是真机原版 schema, 且 bash 与 read 缺一不可 —— 不是数量门槛。
DEFAULT_TOOL_NAMES = ('bash', 'read')
_TOOLS = []


def tools(names=None):
    """真机工具定义 (data/zen_tools.json, 抓包原样)

    names=None → 闸门最小集 (bash+read, 实测 200, 体积最小)
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
                    tool_names=None, ses_id=None, msg_id=None, url=None):
    """将要发出的请求 (不出网): {method, url, headers, body}

    与 `call_zen` 走同一套 `build_body` / `build_headers` / `_endpoints`,
    所以看到的就是真会发的 —— 排查免费层闸门时头与体都得能看见。
    headers 给的是**服务端视角**: 在本函数调用的头之上套了 urllib/http.client
    实际会做的改写 (2026-10-15 本地 echo 服务端抓报文实测), 于是它和真机那 13 个
    头一一对应, 少一个都不可能:
      Host、Content-Length    http.client 补 (值是真: URL 的主机 + 这份体的字节数)
      Connection: close       urllib 写死 (真机是 keep-alive, 我们发不出去)
      头名 .title()           x-opencode-session → X-Opencode-Session (真机小写)
    顺序: 我们的 10 个按真机序, 库补的两个 + Connection 追加在后 (实测报文里
    它们排在开头, 那是 http.client 的写法); HTTP 头顺序无语义, 看集合。
    """
    body_bytes = build_body(model, prompt, system, tool_choice, tool_names)
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

    (缓存收益实测为 0: 免费层 usage.cached_tokens 恒 0, 开关耗时无差异。
    要它是因为调用方要会话稳定, 不是为提速。)
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
    """占位 Bearer public + x-opencode-* 会话/指纹头, 逐项对齐真机

    2026-10-14/15 用 MITM 抓官方 1.19.0 请求逐条对照 (经得起复核), 真机
    13 个头, 顺序也照抄 (x-opencode-request 在 session 之前):
      Authorization: Bearer public
      User-Agent: opencode/1.19.0 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14
      x-opencode-client: cli          x-opencode-project: global
      x-opencode-request: msg_<24位>  x-opencode-session: ses_<12位hex><14位base62>
      x-opencode-session-id: <同 x-opencode-session 的值>   ← 曾漏发
      Accept: */*                     Accept-Encoding: gzip, deflate, br, zstd  ← 曾漏发
    真机还有三个头, 但**不由我们写** (写了也没用/会重复), 实测见 request_preview:
      Host、Content-Length  http.client 自己补
      Connection: keep-alive  urllib 在 do_open 里写死改成 `Connection: close`
                              (源码原话: 本类不复用连接, 必须让服务端关掉),
                              所以叠在 headers 里是死代码 —— 不写。

    与真机的两处不可控差异 (都不影响闸门, bisect_path 验过头名大小写):
      ① 头名被 urllib `.title()` 规范化: x-opencode-session → X-Opencode-Session
         (真机是小写); 要逐字一致得弃用 urllib 自己写 http.client 报文, 顺带
         才能发 keep-alive —— 但 urllib 本来也不复用连接, 复用收益为 0, 不做。
      ② Accept-Encoding 抄了真机, 万一上游真压缩 urllib 不会自己解 —— zen.py
         的 `_unzipper` 兜着 (gzip/deflate 增量解, br/zstd 明确报错)。

    闸门其实不看这些头 (见文件头: 判据是头形态 + body), 对齐是为了不留隐患。
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


def build_body(model, prompt, system=None, tool_choice=None, tool_names=None):
    """OpenAI Chat Completions 请求体

    tools 用真机定义、tool_choice 默认 auto —— 两者都是闸门判据 (见文件头注释)。
    """
    return json.dumps({
        'model': model,
        'max_tokens': 32000,
        'messages': [
            {'role': 'system', 'content': system or DEFAULT_SYSTEM},
            {'role': 'user', 'content': prompt},
        ],
        'tools': tools(tool_names),
        'tool_choice': tool_choice or 'auto',
        'stream': True,
        'stream_options': {'include_usage': True},
    }, ensure_ascii=False).encode('utf-8')


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

