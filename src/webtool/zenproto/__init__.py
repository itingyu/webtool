"""zenproto: 对话协议抽象层

把"发一次大模型对话"拆成协议无关 (端点拼装/流式收包/重试降级, 在 zen.py)
与协议相关 (请求体/认证头/SSE 事件语义, 在这里) 两半。目前两种:

    openai      OpenAI Chat Completions 兼容 (Zen 免费层默认)
    anthropic   Anthropic Messages API (/v1/messages)

协议无关的一半只依赖这里暴露的契约, 因此加第三种协议 = 在本包加一个
Protocol 子类, 不改 zen.py。

三种通道 (content / reasoning / tool_calls) 必须分开收的��因: 模型思考时
content 本来就是空的, 绝不能"content 空就读 reasoning"—— 那会把
"The user asks what time is it. I should say I don't know." 当答案打给用户。
只有全部流结束、正文确实一个字符都没有时, 才把 reasoning 兜底当答案。
"""
import time

from webtool.zenproto.anthropic import AnthropicProtocol
from webtool.zenproto.base import Protocol
from webtool.zenproto.openai import OpenAIProtocol

DEFAULT_SYSTEM = "You are a helpful assistant. Be brief."
TOOL_CHOICES = ("none", "auto", "required")

# 分类器只认这两个名字; 其余工具留着只是为了 --full-tools
MINIMAL_TOOL_NAMES = ("bash", "read")

# 完整工具定义只在 --full-tools 时发送。描述文本不随包分发: 原始实现的
# bash 描述硬编码了本机绝对路径, 每次请求都外传内部目录结构。
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

PROTOCOLS = {
    'openai': OpenAIProtocol,
    'anthropic': AnthropicProtocol,
}


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


def get_protocol(name=None, config=None):
    """按名取协议实例; name 为空取 openai。

    config 里显式给 protocol 时以它为准 —— 这样 ~/.webtool/zen.json 能整套
    换协议 + 换端点 + 带 key, CLI 不用动。
    """
    name = (name or (config or {}).get('protocol') or 'openai').lower()
    cls = PROTOCOLS.get(name)
    if not cls:
        raise ValueError('未知协议 %r (可选: %s)'
                         % (name, ', '.join(sorted(PROTOCOLS))))
    return cls(config)


# ---------------------------------------------------------------- ID 生成
# ses_/msg_ ID: 12 hex (时间戳×4096+计数, session 走递减) + 14 base62。
# 复刻自 opencode 的 packages/schema/src/identifier.ts。random 部分用
# secrets (CSPRNG)。

import secrets

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


class StickySession:
    """跨请求复用 ses_id (让上游有机会复用同一会话的服务端缓存)

    实测 (2026-10, 10 次顺序调用 + 3 组对照): Zen 免费层 usage 里
    cached_tokens / cache_creation_input_tokens 恒为 0, 同 prompt 连打也
    不涨; 开不开耗时无差异 (2.6-3.7s)。所以 CLI 默认关闭, 不按提速手段看待。

    ses_id 的构造方式由协议决定: OpenAI 用 x-opencode-session, Anthropic 侧
    会话亲和靠的是首个 user 消息与 conversation id, 这里只管复用本地标识。
    """

    def __init__(self, protocol):
        self.proto = protocol
        self.ses_id = make_session_id()

    def headers(self):
        """每次请求换新的 msg/request id, ses_id 固定不变"""
        return self.proto.build_headers(self.ses_id, make_message_id())


def make_message_id():
    return 'msg_' + _ID.gen()


__all__ = ['AnthropicProtocol', 'DEFAULT_SYSTEM', 'IDGen', 'MINIMAL_TOOL_NAMES',
           'OpenAIProtocol', 'PROTOCOLS', 'Protocol', 'TOOL_CHOICES',
           'full_tools', 'get_protocol', 'make_message_id', 'make_session_id',
           'minimal_tools']