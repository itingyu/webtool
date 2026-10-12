"""RSSHub 路径模板解析与实参填充

模板语法:
    /:name            必填参数
    /:name?           可选参数, 不填则整段消失
    /:name{regex}?    带正则约束的可选参数

最终订阅 URL = 实例前缀 + 模板 + 实参。
"""

import re

_PARAM_RE = re.compile(r':([A-Za-z_]\w*)(\{[^}]*\})?(\?)?')

class MissingParams(Exception):
    """必填参数没给全"""

    def __init__(self, missing):
        self.missing = missing
        super().__init__(', '.join('%s' % m[0] for m in missing))


# ---------------------------------------------------------------- 模板解析


def parse_params(template):
    """模板 → [(参数名, 是否可选, 正则约束或 None)]

    >>> parse_params('/163/ds/:id')
    [('id', False, None)]
    >>> parse_params('/36kr/:category/:subCategory?')
    [('category', False, None), ('subCategory', True, None)]
    >>> parse_params('/81rc/:category{.+}?')
    [('category', True, '.+')]
    """
    out = []
    for m in _PARAM_RE.finditer(template):
        name, rex, opt = m.group(1), m.group(2), m.group(3)
        out.append((name, bool(opt), rex[1:-1] if rex else None))
    return out


def fill_path(template, params, strict=True):
    """模板 + 实参 → 填好的路径 (缺可选段自动剔除)

    params 键可带 path 里的正则后缀, 如 {'category{.+}?': 'x'} 与 {'category': 'x'}
    等价 —— 先按裸名试, 再按原文试。

    strict=True 时必填参数缺失抛 MissingParams; strict=False 时原样保留 :name
    (交给 RSSHub 自己报错, 适合只想看 URL 的时候)。
    """
    specs = parse_params(template)
    out, missing = template, []
    for name, optional, rex in specs:
        val = params.get(name)
        if val is None:
            for k, v in params.items():          # 容忍 'category{.+}?' 这类键
                if k.split('{')[0].rstrip('?') == name:
                    val = v
                    break
        if val is None:
            if optional:
                # 剔掉整个参数段: ':name{regex}?' 连同前导 '/'
                out = re.sub(r'/:' + re.escape(name) + r'(\{[^}]*\})?\?', '', out)
            else:
                missing.append((name, rex))
            continue
        out = out.replace(f':{name}{{{rex}}}?' if rex else f':{name}?',
                          str(val))
        out = out.replace(f':{name}{{{rex}}}' if rex else f':{name}',
                          str(val))
    if missing and strict:
        raise MissingParams(missing)
    return out.rstrip('/') or '/'


def render_url(instance, template, params=None, strict=True):
    """实例前缀 + 模板 + 实参 → 完整订阅 URL"""
    return instance.rstrip('/') + fill_path(template, params or {}, strict)
