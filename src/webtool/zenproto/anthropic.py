"""Anthropic Messages API 协议 (/v1/messages)

与 OpenAI 兼容形状的五处硬差异, 都不能靠改字段名绕过:

1. 端点     /v1/messages, 不是 /v1/chat/completions
2. 认证     x-api-key + anthropic-version 头, 不是 Authorization: Bearer
3. system   顶层字段, 不塞进 messages 数组 (messages 只允许 user/assistant)
4. tools    {name, description, input_schema}, 没有 type:"function" 外层包装;
             tool_choice 是 {type:"auto"|"any"|"none"} 对象, 不是字符串
5. SSE      事件带 type 字段 (message_start / content_block_delta / ...),
             没有 choices[] 也没有 [DONE] 哨兵

SSE 事件 → 五元组的映射:
    message_start        usage 里的 input_tokens/cache_read 先记下
    content_block_delta  text_delta→content, thinking_delta→reasoning,
                         input_json_delta→tool_calls 分片
    message_delta        stop_reason=tool_use→'__TOOLCALLS__', 其余非 end_turn
                         视为错误; usage 里的 output_tokens 补齐
    error                原样透出错误信息
收尾靠 message_stop (不用 [DONE])。

usage 归一: Anthropic 用 input_tokens/output_tokens, 统一换算成 OpenAI 的
prompt_tokens/completion_tokens/total_tokens, 让下游 (--show-body 之外的
统计/展示) 只有一套字段名。
"""
import json

from webtool.zenproto.base import Protocol

DEFAULT_SYSTEM = 'You are a helpful assistant. Be brief.'
ANTHROPIC_VERSION = '2023-06-01'


class AnthropicProtocol(Protocol):
    name = 'anthropic'
    chat_url = 'https://api.anthropic.com/v1/messages'
    models_url = 'https://api.anthropic.com/v1/models'
    auth_header = 'x-api-key'
    auth_prefix = ''
    extra_headers = {'anthropic-version': ANTHROPIC_VERSION}
    # Anthropic 流没有 [DONE], 靠 message_stop 事件收尾
    sees_done = False

    def __init__(self, config=None):
        super().__init__(config)
        self._input_tokens = None
        self._cache_read = None

    def build_headers(self, ses_id=None, msg_id=None):
        """x-api-key + anthropic-version; 无 key 时用占位 'public'"""
        h = {'x-api-key': self._api_key or 'public',
             'anthropic-version': ANTHROPIC_VERSION,
             'Content-Type': 'application/json'}
        return h

    def build_body(self, model, prompt, system=None, tool_choice=None,
                   full=False):
        """system 提到顶层; tools 去 type 包装; tool_choice 变对象"""
        from webtool.zenproto import full_tools, minimal_tools
        tc = {'none': {'type': 'none'},
              'auto': {'type': 'auto'},
              'required': {'type': 'any'}}
        body = {
            'model': model,
            'max_tokens': 32000,
            'system': system or DEFAULT_SYSTEM,
            'messages': [{'role': 'user', 'content': prompt}],
            'tools': self._tools(full_tools() if full else minimal_tools()),
            'tool_choice': tc.get(tool_choice or 'none', {'type': 'auto'}),
            'stream': True,
        }
        return json.dumps(body, ensure_ascii=False).encode('utf-8')

    @staticmethod
    def _tools(tools):
        """OpenAI {type,function:{name,parameters}} → Anthropic {name,input_schema}"""
        out = []
        for t in tools or []:
            fn = (t.get('function') or {}) if t.get('type') == 'function' else t
            out.append({'name': fn.get('name'),
                        'description': fn.get('description') or '',
                        'input_schema': fn.get('parameters')
                                         or {'type': 'object', 'properties': {}}})
        return out

    def parse_sse(self, lines):
        """Anthropic 事件流 → 五元组"""
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
            if not isinstance(evt, dict):
                continue
            etype = evt.get('type')

            if etype == 'error':
                err = evt.get('error') or {}
                msg = err.get('message') if isinstance(err, dict) else str(err)
                yield '', '', [], evt.get('usage'), str(msg)[:300]
                continue

            if etype == 'message_start':
                # input_tokens/cache_read 只在这里给一次, 先存着
                u = (evt.get('message') or {}).get('usage') or {}
                self._input_tokens = u.get('input_tokens')
                self._cache_read = u.get('cache_read_input_tokens')
                continue

            if etype == 'content_block_start':
                cb = evt.get('content_block') or {}
                if cb.get('type') == 'tool_use':
                    yield '', '', [{'index': evt.get('index', 0),
                                    'id': cb.get('id'),
                                    'type': 'function',
                                    'name': cb.get('name'),
                                    'arguments': ''}], None, None
                continue

            if etype == 'content_block_delta':
                d = evt.get('delta') or {}
                idx = evt.get('index', 0)
                if d.get('type') == 'text_delta':
                    if d.get('text'):
                        yield d['text'], '', [], None, None
                elif d.get('type') == 'thinking_delta':
                    if d.get('thinking'):
                        yield '', d['thinking'], [], None, None
                elif d.get('type') == 'input_json_delta':
                    if d.get('partial_json'):
                        yield '', '', [{'index': idx, 'id': None, 'type': None,
                                        'name': None,
                                        'arguments': d['partial_json']}], None, None
                continue

            if etype == 'message_delta':
                delta = evt.get('delta') or {}
                stop = delta.get('stop_reason')
                u = evt.get('usage') or {}
                out_tok = u.get('output_tokens')
                usage = self._merge_usage(out_tok)
                err = None
                if stop == 'tool_use':
                    err = '__TOOLCALLS__'
                elif stop and stop not in ('end_turn', 'stop_sequence'):
                    err = 'stop_reason=%s' % stop
                yield '', '', [], usage, err
                continue

            if etype == 'message_stop':
                yield '', '', [], self._merge_usage(None), None
                continue
            # ping / content_block_stop 等无内容事件直接忽略

    def _merge_usage(self, output_tokens):
        """Anthropic 字段名 → OpenAI 字段名, 供下游一套统计口径"""
        if self._input_tokens is None and output_tokens is None:
            return None
        pt = self._input_tokens
        ct = output_tokens
        u = {}
        if pt is not None:
            u['prompt_tokens'] = pt
        if ct is not None:
            u['completion_tokens'] = ct
        if pt is not None or ct is not None:
            u['total_tokens'] = (pt or 0) + (ct or 0)
        if self._cache_read:
            u['prompt_tokens_details'] = {'cached_tokens': self._cache_read}
        return u or None

    def parse_models(self, data):
        """Anthropic /v1/models 是 {data: [{id}]}, 与 OpenAI 同形状"""
        return [m.get('id') for m in (data or {}).get('data', []) if m.get('id')]