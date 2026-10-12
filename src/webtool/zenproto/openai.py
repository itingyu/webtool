"""OpenAI Chat Completions 兼容协议 (/v1/chat/completions)

当前 Zen 免费层用的就是这个形状, 行为与拆包前逐项一致。与 Anthropic 的差异见
anthropic.py 顶部注释。

SSE 解析: choices[].delta.{content, reasoning|reasoning_content, tool_calls[]},
外加 choices[].finish_reason 与 usage; 靠 data: [DONE] 哨兵收尾。
"""
import json

from webtool.zenproto.base import USER_AGENT, Protocol


class OpenAIProtocol(Protocol):
    name = 'openai'
    chat_url = 'https://opencode.ai/zen/v1/chat/completions'
    models_url = 'https://opencode.ai/zen/v1/models'
    auth_header = 'Authorization'
    auth_prefix = 'Bearer '
    sees_done = True

    def build_headers(self, ses_id=None, msg_id=None):
        """占位 Bearer public + x-opencode-* 会话/指纹头

        UA 与 x-opencode-client/project 是网关的指纹校验项, 少一个就 403,
        不是装饰 —— 换协议时别把它们当冗余删掉。
        """
        from webtool.zenproto import make_message_id, make_session_id
        return {
            'Authorization': self.auth_value(),
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
            'x-opencode-client': 'cli',
            'x-opencode-project': 'global',
            'x-opencode-session': ses_id or make_session_id(),
            'x-opencode-request': msg_id or make_message_id(),
            'Accept': '*/*',
        }

    def build_body(self, model, prompt, system=None, tool_choice=None,
                   full=False):
        from webtool.zenproto import DEFAULT_SYSTEM, full_tools, minimal_tools
        body = {
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
        }
        return json.dumps(body, ensure_ascii=False).encode('utf-8')

    def parse_sse(self, lines):
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