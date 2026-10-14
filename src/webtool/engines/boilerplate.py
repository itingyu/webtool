"""无依赖正文抽取: readability 算法 (纯标准库, 零关键词表)

**为什么要有它**: 链上主力 trafilatura 与 readability-lxml 都要 lxml。装不上
lxml 的平台 (Termux/Android 之类) 一路掉到 inscriptis, 而 inscriptis 是"整页
纯文本" —— 导航栏、二维码、APP 推广、相关推荐、页脚版权全在里面。用户拿到一堆
广告和无效内容还得自己眯着眼找正文, 这比报错更糟: 它看着像成功了。

这里是 readability 那套**打分选块**算法的移植, 只用结构信号 (段落长度、标点、
链接密度、祖先累积), 不认任何关键词 —— 换语言、换站点都不用改。

四步:

1. **清洗** —— 按标签剔除 script/style/iframe 等非内容节点, 按 style 剔除
   隐藏元素 (display:none / visibility:hidden);
2. **打分** —— 每个"段落级"节点按 innerText 打分, 分数累积给父 (全权) 与祖父
   (半权), 这是 readability 的核心: 正文容器会因为内部段落多而浮上来;
3. **定级** —— 取总分最高的节点, 若其中某一个子节点独占大部分分数 (>= 60%),
   就下钻一层。上层包裹 div 常常"顺手"把侧栏/推广也算进来, 下钻是为了甩掉它们;
4. **清尾** —— 对最终容器逐个检查子块: 分数过低的、链接密度过高的 (纯导航/
   友情链接) 剔除。

**三处针对中文页的调整, 不是拍脑袋而是量纲问题**:

- readability 的阈值是按英文字符定的。同样的信息量中文只要 1/3 的字符数, 所以
  这里把长度折成"等效英文长度" (`_eff`: 一个汉字算 3 个) 再比阈值, 否则中文段落
  会被 `MIN_TEXT_LENGTH` 一律判死;
- readability 数逗号当"像正文"的证据。中文里逗号在导航碎片 ("方便，快捷"、
  "专业，丰富") 里同样遍地都是, 更可靠的正文信号是**句末标点** (。！？；),
  所以给它 3 倍权重;
- 标题/导航项零标点, 天然得低分, 不需要把它们列成黑名单。
"""

import re
from html.parser import HTMLParser

_VOID = {'br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'area', 'base',
         'col', 'embed', 'param', 'track', 'wbr'}

# 整棵子树直接砍: 语义上就不可能是正文, 与站点无关
_DROP_TAGS = {'script', 'style', 'noscript', 'iframe', 'svg', 'canvas',
              'template', 'form', 'button', 'select', 'option', 'textarea',
              'input', 'nav', 'aside', 'footer', 'header', 'map', 'object'}

# 段落级: 打分只认这些节点的 innerText
_BLOCK_TAGS = {'p', 'div', 'section', 'article', 'main', 'td', 'th', 'pre',
               'blockquote', 'li', 'dd', 'dt', 'h1', 'h2', 'h3', 'h4', 'h5',
               'h6', 'figcaption'}

# 渲染时断行的标签
_BREAK_TAGS = _BLOCK_TAGS | {'ul', 'ol', 'table', 'tr', 'br', 'figure', 'dl'}

# 正文信号
_SENT_END = '。！？；!?;'          # 句末: 只有真正的句子才有
_COMMA = '，、,.'                  # 逗号: 片段里也有, 权重低

_MIN_EFF = 75                     # 等效英文 75 字 ≈ 25 个英文字符的 readability 下限
_LINK_DENSITY_MAX = 0.5           # 子块链接密度上限 (纯导航/链接墙)
_DESCEND_RATIO = 0.6              # 单个子节点占父分数多少才值得下钻
_DENSITY_RATIO = 0.55             # 子块密度低于容器内最高密度的这个比例 = 碎片堆


def _eff(text_len, cjk_len):
    """等效英文长度: 汉字信息密度约 3 倍, 拿英文阈值比中文必须折算"""
    return (text_len - cjk_len) + cjk_len * 3


def _count_cjk(s):
    n = 0
    for ch in s:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0x3000 <= o <= 0x303F:
            n += 1
    return n


class _Node:
    __slots__ = ('tag', 'attrs', 'kids', 'parent')

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.kids = []
        self.parent = parent


class _Tree(HTMLParser):
    """够用的容错解析: 没闭合的标签按"往上找同名祖先"收尾"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('#root', {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = _Node(tag, {k: (v or '') for k, v in attrs}, self.cur)
        self.cur.kids.append(n)
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_Node(tag, {k: (v or '') for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if data and data.strip():
            self.cur.kids.append(data)


def _hidden(attrs):
    style = (attrs.get('style') or '').replace(' ', '').lower()
    if not style:
        return False
    return 'display:none' in style or 'visibility:hidden' in style


def _clean(node):
    """步骤 1: 按标签/可见性剔除整棵子树"""
    keep = []
    for k in node.kids:
        if isinstance(k, str):
            keep.append(k)
            continue
        if k.tag in _DROP_TAGS or _hidden(k.attrs):
            continue
        _clean(k)
        keep.append(k)
    node.kids = keep
    return node


def _stats(node, memo):
    """(总字数, 汉字数, 句末标点数, 逗号数, 链接内字数) —— 一次自底向上"""
    key = id(node)
    if key in memo:
        return memo[key]
    if isinstance(node, str):
        v = (len(node), _count_cjk(node),
             sum(node.count(c) for c in _SENT_END),
             sum(node.count(c) for c in _COMMA), 0)
        memo[key] = v
        return v
    t = cjk = sent = comma = link = 0
    for k in node.kids:
        kt, kc, ks, kk, kl = _stats(k, memo)
        t += kt
        cjk += kc
        sent += ks
        comma += kk
        link += kl
    if node.tag == 'a':
        link = t
    v = (t, cjk, sent, comma, link)
    memo[key] = v
    return v


def _score(st):
    """readability 的打分式, 标点权重按中文改写 (见模块 docstring)"""
    t, cjk, sent, comma, _link = st
    if _eff(t, cjk) < _MIN_EFF:
        return 0.0
    return 1.0 + sent * 3 + comma + min(_eff(t, cjk) / 300.0, 3.0)


def _density(st):
    """每 100 等效字符里有几个标点 —— 正文的"文气"密度

    这是把导航/推广块和正文段分开的关键量: 两者长度可能差不多, 但正文靠标点
    把字连成句子, 推广块 ("分享到微信朋友圈" "扫描二维码关注") 是没有标点的
    碎片堆。按长度归一, 才不会让"谁的块更大"变成"谁更像正文"。
    """
    t, cjk, sent, comma, _link = st
    if (t - cjk) + cjk * 3 <= 0:
        return 0.0
    return (sent * 3 + comma) * 100.0 / _eff(t, cjk)


def _walk(node):
    for k in node.kids:
        if not isinstance(k, str):
            yield k
            yield from _walk(k)


def _aggregate(root, memo):
    """步骤 2: 分数累积给 自己 + 父(全权) + 祖父(半权)"""
    agg = {}
    for node in _walk(root):
        s = _score(memo[id(node)])
        if s <= 0:
            continue
        agg[id(node)] = agg.get(id(node), 0.0) + s
        up = node.parent
        if up is not None:
            agg[id(up)] = agg.get(id(up), 0.0) + s
            gp = up.parent
            if gp is not None:
                agg[id(gp)] = agg.get(id(gp), 0.0) + s * 0.5
    return agg


def _children(node):
    return [k for k in node.kids if not isinstance(k, str)]


def _pick(root, memo, agg):
    """步骤 3: 最高分节点 + 独占型下钻"""
    cands = [n for n in _walk(root)
             if n.tag in _BLOCK_TAGS and agg.get(id(n)) and memo[id(n)][0] >= 30]
    if not cands:
        return None
    top = max(cands, key=lambda n: agg[id(n)])
    for _ in range(8):                       # 下钻深度封顶, 防病态嵌套
        top_score = agg.get(id(top), 0.0)
        kids = [(agg.get(id(k), 0.0), k) for k in _children(top)]
        if not kids:
            break
        best_s, best_k = max(kids, key=lambda kv: kv[0])
        if top_score <= 0 or best_s < top_score * _DESCEND_RATIO:
            break
        top = best_k
    return top


def _trim(node, memo, agg):
    """步骤 4: 容器内按"文气密度"清尾

    同一个容器里往往并排着正文块和推广/声明/举报块 (站点把它们塞在文章区域里),
    长度甚至后者更大, 靠长度分不开; 但它们没有标点、是碎片堆, 密度会低一截。
    以容器内最高的那个子块密度为基准, 明显更"干"的子块丢掉。
    """
    kids = _children(node)
    dens = {id(k): _density(memo[id(k)]) for k in kids}
    best = max(dens.values()) if dens else 0.0
    keep = []
    for k in node.kids:
        if isinstance(k, str):
            keep.append(k)
            continue
        t, _cjk, _s, _c, link = memo[id(k)]
        if t == 0:                                  # 空壳
            continue
        if link and t and link / t > _LINK_DENSITY_MAX:
            continue                                # 链接墙: 导航/友链/相关阅读
        if best > 0 and dens[id(k)] < best * _DENSITY_RATIO:
            continue                                # 碎片堆: 推广/声明/分享
        keep.append(k)
    node.kids = keep
    return node


def _render(node):
    """渲染成纯文本: 块级标签断行, 行内标签直接拼"""
    out = []

    def rec(n):
        for k in n.kids:
            if isinstance(k, str):
                out.append(k)
                continue
            if k.tag == 'br':
                out.append('\n')
                continue
            rec(k)
            if k.tag in _BREAK_TAGS:
                out.append('\n')

    rec(node)
    text = ''.join(out)
    text = re.sub(r'[ \t\u00a0]+', ' ', text)
    return re.sub(r'\n\s*\n+', '\n', text).strip()


def extract_boilerplate(html, url, meta):
    """链上排在 readability 之后、全文保底之前; 纯标准库, 不会 ImportError"""
    tree = _Tree()
    try:
        tree.feed(html or '')
    except Exception:
        return '', meta
    _clean(tree.root)
    memo = {}
    _stats(tree.root, memo)
    agg = _aggregate(tree.root, memo)
    best = _pick(tree.root, memo, agg)
    if best is None:
        return '', meta
    text = _render(_trim(best, memo, agg))
    if _eff(len(text), _count_cjk(text)) >= _MIN_EFF:
        return text, meta
    # 选中的容器太干: 换成整页渲染, 交给上层判薄
    return _render(tree.root), meta
