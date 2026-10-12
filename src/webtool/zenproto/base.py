"""协议基类: 对话线协议无关的部分都收敛到子类

两种协议的五处差异 (端点/认证头/system 位置/tools 形状/SSE 事件) 全部
落在子类实现, 基类只定义契约:

    name         协议标识, 出现在配置与 CLI 里
    chat_url     对话端点
    build_headers(ses_id, msg_id)
    build_body(model, prompt, system, tool_choice, full) -> bytes
    parse_sse(lines) -> yield (content, reasoning, tool_calls, usage, error)
    models_url   模型清单端点 (None = 该协议不支持)
    parse_models(data) -> [model_id]
    sees_done    流里是否靠 [DONE] 哨兵判断正常收尾

`parse_sse` 的五元组约定 (两种协议共用, 上层 drain 不关心具体协议):
    content     正文增量
    reasoning   思考增量, 与 content 必须分开收 (见 zenproto/__init__.py 说明)
    tool_calls  分片下发, 按 index 归位
    usage       用量对象 (None = 上游没给)
    error       错误串; '__TOOLCALLS__' 是保留值, 表示模型要调工具

URL 默认值: 子类给 defaults, 实例可被配置 (data/zen.json 或
~/.webtool/zen.json) 覆盖 —— 换第三方中转只需改配置, 不改代码。
"""


# 网关指纹校验项; 住本模块而不是包 __init__, 因为子类要导入它
# (反向导入 __init__ 会成环)
USER_AGENT = 'opencode/1.18.15 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14'


class Protocol:
    """对话协议基类 (默认按 OpenAI 兼容实现, 各子类按需覆盖)"""

    name = 'openai'
    chat_url = None
    models_url = None
    # 默认认证: 公共端点用占位 Bearer; 需要真实 key 的协议覆盖它
    auth_header = 'Authorization'
    auth_prefix = 'Bearer '
    extra_headers = {}
    sees_done = True

    def __init__(self, config=None):
        self.config = config or {}
        if self.config.get('chat_url'):
            self.chat_url = self.config['chat_url']
        if self.config.get('models_url'):
            self.models_url = self.config['models_url']
        if self.config.get('api_key'):
            self.auth_prefix = ''
            self._api_key = self.config['api_key']
        else:
            self._api_key = None

    def build_headers(self, ses_id=None, msg_id=None):
        """默认 OpenAI 形状: Authorization + x-opencode-*"""
        h = {
            self.auth_header: (self.auth_prefix + self._api_key) if self._api_key
                              else 'public',
            'Content-Type': 'application/json',
        }
        h.update(self.extra_headers)
        return h

    def build_body(self, model, prompt, system=None, tool_choice=None,
                   full=False):
        raise NotImplementedError

    def parse_sse(self, lines):
        raise NotImplementedError

    def auth_value(self):
        """认证头取值: 有 key 用 key, 否则公共端点占位 (Bearer public)"""
        if self._api_key:
            return self.auth_prefix + self._api_key
        return self.auth_prefix + 'public' if self.auth_prefix else None

    def model_headers(self):
        """列模型用的头: 与对话同源认证, 但不带会话/指纹头 (列表接口不吃这些)"""
        h = {'Accept': 'application/json', 'User-Agent': USER_AGENT}
        v = self.auth_value()
        if v is not None:
            h[self.auth_header] = v
        return h

    def parse_models(self, data):
        """默认 OpenAI 形状 {data: [{id}]}"""
        return [m.get('id') for m in (data or {}).get('data', []) if m.get('id')]