"""Zen 的 OpenAI 兼容协议细节: 端点/认证头/请求体/流式解析/ID 生成

只有一个协议, 所以都是普通函数而不是策略类 —— 真要接第二种协议时再抽基类。

认证: 免费层用占位 `Bearer public`, 不需要真 key。
指纹头: UA 与 x-opencode-client/project 是网关的校验项, 少一个就 403,
它们不是装饰, 别当冗余删。
"""
import json
import secrets
import time

USER_AGENT = 'opencode/1.18.15 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14'

CHAT_URL = 'https://opencode.ai/zen/v1/chat/completions'
MODELS_URL = 'https://opencode.ai/zen/v1/models'

DEFAULT_SYSTEM = "You are a helpful assistant. Be brief."
TOOL_CHOICES = ("none", "auto", "required")

# 分类器只认这两个名字; 其余工具留着只是为了 --full-tools
_FULL_TOOL_SPECS = [
    ('bash', 'Executes a given bash command.'),
    ('edit', 'Performs exact string replacements in files.'),
    ('glob', 'Fast file pattern matching tool.'),
    ('grep', 'Searches file contents with regular expressions.'),
    ('read', 'Reads a file from the filesystem.'),
    ('skill', 'Load a specialized skill when the task matches.'),
    ('task', 'Launch a new agent to handle complex tasks.'),
    ('todowrite', 'Maintain a structured task list.'),
    ('webfetch', 'Fetches content from a specified URL.'),
    ('websearch', 'Search the web using the session provider.'),
    ('write', 'Writes a file to the local filesystem.'),
]

MINIMAL_TOOL_NAMES = ("bash", "read")


def minimal_tools():
    """通过分类器的最小工具定义: bash + read, parameters 空对象。"""
    return [{'type': 'function',
             'function': {'name': n, 'parameters': {}}}
            for n in MINIMAL_TOOL_NAMES]


def full_tools():
    """原始的 11 个工具定义 (--full-tools)。描述已去敏, 不含本机路径。"""
    return [{'type': 'function',
             'function': {'name': n, 'description': d,
                          'parameters': {'type': 'object', 'properties': {},
                                         'required': []}}}
            for n, d in _FULL_TOOL_SPECS]


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
        cur = ts * 0x1000 + self.counter
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
    """跨请求复用 ses_id (让上游有机会复用同一会话的服务端缓存)

    实测 (2026-10, 10 次顺序调用 + 3 组对照): Zen 免费层 usage 里
    cached_tokens 恒为 0, 同 prompt 连打也不涨; 开不开耗时无差异
    (2.6-3.7s)。所以 CLI 默认关闭, 不按提速手段看待。
    """

    def __init__(self):
        self.ses_id = make_session_id()

    def headers(self):
        """每次请求换新的 msg/request id, ses_id 固定不变"""
        return build_headers(self.ses_id, make_message_id())


def _endpoints():
    """端点: 包内 data/zen.json + ~/.webtool/zen.json 叠加 (mtime 热生效),
    文件缺失/无值回落内置常量"""
    from webtool.core.config_data import load as _cfg_load
    d = _cfg_load('zen', 'zen.json') or {}
    return (d.get('chat_url') or CHAT_URL,
            d.get('models_url') or MODELS_URL)


def build_headers(ses_id=None, msg_id=None):
    """占位 Bearer public + x-opencode-* 会话/指纹头"""
    return {
        'Authorization': 'Bearer public',
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT,
        'x-opencode-client': 'cli',
        'x-opencode-project': 'global',
        'x-opencode-session': ses_id or make_session_id(),
        'x-opencode-request': msg_id or make_message_id(),
        'Accept': '*/*',
    }


def model_headers():
    """列模型用的头: 认证同源, 但不带会话/指纹头 (列表接口不吃这些)"""
    return {'Accept': 'application/json', 'User-Agent': USER_AGENT,
            'Authorization': 'Bearer public'}


def build_body(model, prompt, system=None, tool_choice=None, full=False):
    """OpenAI Chat Completions 请求体"""
    return json.dumps({
        'model': model,
        'max_tokens': 32000,
        'messages': [
            {'role': 'system', 'content': system or DEFAULT_SYSTEM},
            {'role': 'user', 'content': prompt},
        ],
        'tools': full_tools() if full else minimal_tools(),
        'tool_choice': tool_choice or 'none',
        'stream': True,
        'stream_options': {'include_usage': True},
    }, ensure_ascii=False).encode('utf-8')


def parse_models(data):
    """OpenAI 形状的模型清单 dict → id 列表"""
    return [m.get('id') for m in (data or {}).get('data', []) if m.get('id')]


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

