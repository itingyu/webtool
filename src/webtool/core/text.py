"""文本清洗工具类: HTML 片段 → 纯文本

搜索引擎/站点源返回的标题摘要普遍带标签、实体与高亮标记, 各模块此前
各写一份正则, 行为不一致 (有的不 unescape、有的吃掉 <em> 里的高亮词)。
这里收口成明确意图的几个函数, 调用方按语义选, 不再复制正则。

    strip_tags   只去标签, 保留 <em> 高亮文字 (原文语义)
    clean_markup 去标签 + 折叠空白, 连 <em> 标签一起吃掉 (只要文字)
    unescape     HTML 实体解码, 不动标签
    plain        strip_tags + unescape (最常见的"标题转纯文本")
    md_to_text   markdown 正文 → 纯文本 (只去标记, 不动内容)

两个"转纯文本"别混用: `plain` 吃的是 HTML 片段 (搜索摘要), `md_to_text` 吃的是
markdown 正文 (正文提取器的产物)。正文里带 markdown 标记不是"脏", 是格式 ——
只有明确要 txt 时才该抹掉。
"""
import re
from html import unescape as _unescape

_RE_TAG = re.compile(r'<[^>]+>')
_RE_EM = re.compile(r'</?em[^>]*>')
_RE_WS = re.compile(r'\s+')

def strip_tags(s):
    """去标签但保留 <em> 高亮文字; 不解码实体。空值安全。"""
    return _RE_WS.sub(' ', _RE_EM.sub('', _RE_TAG.sub('', s or ''))).strip()

def clean_markup(s):
    """去全部标签 (含 <em> 标签本身) + 折叠空白, 只要文字内容"""
    return _RE_WS.sub(' ', _RE_TAG.sub('', s or '')).strip()

def unescape(s):
    """HTML 实体解码 + 去首尾空白, 不动标签"""
    return _unescape(s or '').strip()

def plain(s):
    """strip_tags + unescape: 搜索引擎标题转纯文本的标准做法"""
    return _unescape(strip_tags(s)).strip()

def truncate(s, n):
    """按字符截断, 超长补省略号 (用于 snippet 长度上限)"""
    s = s or ''
    return s if len(s) <= n else s[:n - 1] + '…'

# markdown → 纯文本
# 刻意**不**做的两件事: 不删列表符号 (- / 1.), 不删缩进 —— 纯文本里它们照样是
# 排版, 抹掉反而把并列关系糊成一段。要抹的是"离开 markdown 渲染器就变噪声"的
# 那一类标记: 井号/星号/反引号/链接括号/表格竖线。
_RE_MD_IMG = re.compile(r'!\[((?:\\.|[^\[\]])*)\]\((?:[^()]|\([^()]*\))*\)')
# 先图后链: ![a](b) 内含 [a](b)。标签里可能有转义方括号 (`\[email protected\]`),
# URL 里可能有括号 (维基 /wiki/Python_(语言)), 两条都得容得下, 否则链接原样留下。
_RE_MD_LINK = re.compile(r'\[((?:\\.|[^\[\]])+)\]\((?:[^()]|\([^()]*\))*\)')
_RE_MD_REF = re.compile(r'\[([^\]]+)\]\[[^\]]*\]')       # 引用式链接 [文字][1]
_RE_MD_CODE = re.compile(r'`+([^`]*)`+')
# 前后断言: `a*b*c` 不是强调; 反斜杠转义的 `\*` 是字面星号, 也不是 —— 转义留给
# 最后的 _RE_MD_ESC 还原, 这里先别碰, 否则 `\*literally\*` 会被当强调吃掉星号。
_RE_MD_BOLD = re.compile(r'(?<!\\)\*\*([^*]+)\*\*|(?<!\\)__([^_]+)__')
_RE_MD_EM = re.compile(r'(?<![*\w\\])\*([^*\n]+)\*(?![*\w])')
_RE_MD_ESC = re.compile(r'\\([\\`*_{}\[\]()#+.!~|>-])')        # markdown 转义: \[ \* …
_RE_MD_HEAD = re.compile(r'^#{1,6}[ \t]+', re.M)
_RE_MD_QUOTE = re.compile(r'^>[ \t]?', re.M)
_RE_MD_FENCE = re.compile(r'^[ \t]*```.*$', re.M)
_RE_MD_RULE = re.compile(r'^[ \t]{0,3}(?:[-*_][ \t]*){3,}$', re.M)
_RE_MD_TSEP = re.compile(r'^[ \t]*\|?[ \t:|-]+\|[ \t:|-]*$', re.M)   # |---|---|
_RE_MD_ROW = re.compile(r'^[ \t]*\|(.+)\|[ \t]*$', re.M)             # | a | b |
_RE_MD_BLANK = re.compile(r'\n{3,}')
_RE_FM = re.compile(r'\A---\n[\s\S]*?\n---\n')           # YAML 元数据头


def strip_front_matter(s):
    """切掉开头的 YAML 元数据头 (`---\\ntitle: ...\\n---\\n`), 没有就原样返回

    只要正文时的入口 (markdown 仍是 markdown, 不做去标记)。元数据单独取,
    留在正文里会被下游当成内容的一部分。
    """
    m = _RE_FM.match(s or '')
    return (s or '')[m.end():] if m else (s or '')


def md_to_text(s, keep_meta=True):
    """markdown 正文 → 纯文本: 去标记, 内容一字不少

    fetch 的 `-f txt` 走这里。markdown 标记 (标题、强调、表格) 与链接都得抹干净,
    只抹一半等于给了个假 txt。

    `keep_meta=False` 时连 YAML 元数据头一起去掉: 那一段是给机器看的
    (title/url/date/tags), 塞在"纯文本正文"前面就是噪声 —— 要元数据走 `-f json`。
    为 True 时原样保留 (它是元数据不是 markdown 标记, 抹掉等于静默丢信息),
    但同样要先切出来, 否则它那两行 `---` 会被当水平线吃掉。
    """
    m = _RE_FM.match(s or '')
    head, body = (m.group(0), s[m.end():]) if m else ('', s or '')
    body = _RE_MD_FENCE.sub('', body)
    body = _RE_MD_IMG.sub(r'\1', body)
    body = _RE_MD_LINK.sub(r'\1', body)
    body = _RE_MD_REF.sub(r'\1', body)
    body = _RE_MD_CODE.sub(r'\1', body)
    body = _RE_MD_BOLD.sub(lambda m: m.group(1) or m.group(2), body)
    body = _RE_MD_EM.sub(r'\1', body)
    body = _RE_MD_ESC.sub(r'\1', body)
    body = _RE_MD_HEAD.sub('', body)
    body = _RE_MD_QUOTE.sub('', body)
    body = _RE_MD_RULE.sub('', body)
    body = _RE_MD_TSEP.sub('', body)
    body = _RE_MD_ROW.sub(lambda m: ' '.join(x.strip() for x in m.group(1).split('|')), body)
    return (head if keep_meta else '') + _RE_MD_BLANK.sub('\n\n', body).strip()