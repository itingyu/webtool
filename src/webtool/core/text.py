"""文本清洗工具类: HTML 片段 → 纯文本

搜索引擎/站点源返回的标题摘要普遍带标签、实体与高亮标记, 各模块此前
各写一份正则, 行为不一致 (有的不 unescape、有的吃掉 <em> 里的高亮词)。
这里收口成四个明确意图的函数, 调用方按语义选, 不再复制正则。

    strip_tags   只去标签, 保留 <em> 高亮文字 (原文语义)
    clean_markup 去标签 + 折叠空白, 连 <em> 标签一起吃掉 (只要文字)
    unescape     HTML 实体解码, 不动标签
    plain        strip_tags + unescape (最常见的"标题转纯文本")
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