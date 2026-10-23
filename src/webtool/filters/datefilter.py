"""按时间过滤搜索结果 (filter 插件: datefilter)

为什么要单独一层: 关键词搜索引擎 (bing/sogou/baidu/360) **不返回发布日期**
—— 实测结果项里没有任何日期字段, 摘要里也未必带日期。所以"按时间筛"不能
只靠引擎给的元数据, 得从标题/摘要的正文里认日期。

判定顺序 (先命中先用, 都认不出就当"未知"):
1. 结构化字段: publish_date / date / time / pub_date / published
2. 摘要/标题里的绝对日期: 2026-10-22 / 2026/10/22 / 2026年10月22日 /
   10月22日 / Oct 22, 2026 / 22 Oct 2026
3. 相对时间: 3天前 / 昨天 / 刚刚 / 2小时前 / 5分钟前 / 2周前 (英文同款)

相对时间按"今天"倒推 —— 但只在同一年份内可信, 跨年 (12月31日说"3天前")
会算到去年, 这在"近一周"这种查询里通常是想要的 (12月28日的"3天前"确实
是去年), 但在"今年"这种查询里会误杀。对策: 跨年时把相对时间算出的日期
标记为 low_confidence, 只在 --since 距离超过 30 天时才采信。

**未知日期的条目默认保留**, 不因为"认不出日期"就丢掉 —— 那会把大半结果
清空, 用户以为没结果了。真的想要严格模式用 --date-strict。
"""
import datetime
import re

# 结构化日期字段 (按优先级)
_DATE_FIELDS = ('publish_date', 'published', 'pub_date', 'date',
                'time', 'publishDate', 'post_date')

# 绝对日期: 2026-10-22 / 2026/10/22 / 2026.10.22
_RE_ISO = re.compile(r'(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})')
# 中文绝对日期: 2026年10月22日
_RE_CN_FULL = re.compile(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日?')
# 中文月日 (无年): 10月22日
_RE_CN_MD = re.compile(r'(?<!\d)(\d{1,2})月\s*(\d{1,2})日?')
# 英文: Oct 22, 2026 / October 22, 2026
_RE_EN_MDY = re.compile(
    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b',
    re.I)
# 英文: 22 Oct 2026
_RE_EN_DMY = re.compile(
    r'\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+(20\d{2})\b',
    re.I)
# 相对时间 (中文)
_RE_CN_REL = re.compile(
    r'(刚刚|刚才|今天|今日|昨天|昨日|前天)'
    r'|(\d+)\s*(分钟|小时|鐘頭|天|周|星期|个月|年)前')
# 相对时间 (英文)
_RE_EN_REL = re.compile(
    r'\b(just now|today|yesterday)\b'
    r'|\b(\d+)\s+(minute|min|hour|hr|day|week|month|year)s?\s+ago\b', re.I)

_MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
           'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}

_CN_UNIT_DAYS = {'分钟': 1 / 1440, '小时': 1 / 24, '天': 1, '周': 7,
                 '星期': 7, '个月': 30, '年': 365}
_EN_UNIT_DAYS = {'minute': 1 / 1440, 'min': 1 / 1440, 'hour': 1 / 24,
                 'hr': 1 / 24, 'day': 1, 'week': 7, 'month': 30, 'year': 365}


def _mk(y, m, d):
    try:
        return datetime.date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _parse_structured(value):
    """结构化日期字段 → date (认 ISO/时间戳/中文)"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.date.fromtimestamp(float(value))
        except (ValueError, OSError, OverflowError):
            return None
    s = str(value).strip()
    if not s:
        return None
    m = _RE_ISO.search(s) or _RE_CN_FULL.search(s)
    if m:
        return _mk(m.group(1), m.group(2), m.group(3))
    # 纯时间戳 (秒)
    if s.isdigit() and len(s) == 10:
        try:
            return datetime.date.fromtimestamp(int(s))
        except (ValueError, OSError, OverflowError):
            return None
    return None


def _parse_text(text, today=None):
    """正文里的日期 → (date, low_confidence)

    low_confidence=True 表示"无年份的月日"或"跨年推算的相对时间" ——
    调用方可以据此决定要不要采信。
    """
    if not text:
        return None, False
    today = today or datetime.date.today()

    m = _RE_ISO.search(text) or _RE_CN_FULL.search(text)
    if m:
        return _mk(m.group(1), m.group(2), m.group(3)), False

    m = _RE_EN_MDY.search(text)
    if m:
        return _mk(m.group(3), _MONTHS[m.group(1).lower()[:3]], m.group(2)), False
    m = _RE_EN_DMY.search(text)
    if m:
        return _mk(m.group(3), _MONTHS[m.group(2).lower()[:3]], m.group(1)), False

    # 相对时间 (先于无年月日: "3天前" 比同句里的 "10月22日" 更贴近"最近")
    m = _RE_CN_REL.search(text)
    if m:
        if m.group(1):
            base = today - datetime.timedelta(days={'刚刚': 0, '刚才': 0,
                                                   '今天': 0, '今日': 0,
                                                   '昨天': 1, '昨日': 1,
                                                   '前天': 2}[m.group(1)])
            return base, False
        n = int(m.group(2))
        unit = m.group(3)
        days = n * _CN_UNIT_DAYS.get(unit, 1)
        base = today - datetime.timedelta(days=days)
        # 跨年推算: 相对时间往前推, 若推出的日期落在未来, 说明是去年的事
        low = False
        if base > today:
            base = base - datetime.timedelta(days=365)
            low = True
        return base, low

    m = _RE_EN_REL.search(text)
    if m:
        if m.group(1):
            word = m.group(1).lower()
            base = today - datetime.timedelta(days=1 if word == 'yesterday' else 0)
            return base, False
        n = int(m.group(2))
        unit = m.group(3).lower()
        days = n * _EN_UNIT_DAYS.get(unit, 1)
        base = today - datetime.timedelta(days=days)
        low = False
        if base > today:
            base = base - datetime.timedelta(days=365)
            low = True
        return base, low

    # 无年月的月日 (10月22日) — 低置信: 年份靠猜
    m = _RE_CN_MD.search(text)
    if m:
        d = _mk(today.year, m.group(1), m.group(2))
        if d is None:
            return None, False
        if d > today + datetime.timedelta(days=1):
            # 落在未来 → 去年
            d = _mk(today.year - 1, m.group(1), m.group(2))
        return d, True

    return None, False


def item_date(item, today=None):
    """结果的日期 → (date, source, low_confidence); 认不出返回 (None, '', False)

    source: 'field' / 'text' / '' (认不出)
    """
    today = today or datetime.date.today()
    for f in _DATE_FIELDS:
        if f in item:
            d = _parse_structured(item.get(f))
            if d:
                return d, 'field', False
    # 正文: 摘要 + 标题 (标题里的日期也算)
    text = ' '.join(str(item.get(k) or '') for k in ('snippet', 'title',
                                                      'description', 'summary'))
    d, low = _parse_text(text, today)
    if d:
        return d, 'text', low
    return None, '', False


def _shift_months(d, months):
    """d 前后平移 n 个日历月 (月底溢出则夹到当月最后一天)"""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    import calendar
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def parse_since(spec, today=None):
    """--since 参数 → date

    认得: YYYY-MM-DD / YYYY/MM/DD / N天前 / 7d / 2w / 3m / 1y / 今天 / 昨天
    """
    today = today or datetime.date.today()
    s = (spec or '').strip()
    if not s:
        return None
    low = s.lower()
    if low in ('today', '今天'):
        return today
    if low in ('yesterday', '昨天'):
        return today - datetime.timedelta(days=1)
    m = _RE_ISO.search(s) or _RE_CN_FULL.search(s)
    if m:
        return _mk(m.group(1), m.group(2), m.group(3))
    # 相对: 7d / 2w / 3m / 1y / 30天
    m = re.fullmatch(r'(\d+)\s*([dwmy日周月年天])', low)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit in ('m', '月'):
            # 月/年按日历月算, 不按 30/365 天折算 —— "3个月前"是 7月22日,
            # 不是 7月24日 (10月22减90天)。差两天不算错, 但用户心里的
            # "3个月前"是日历上的三个月。
            return _shift_months(today, -n)
        if unit in ('y', '年'):
            return _shift_months(today, -12 * n)
        days = {'d': 1, '日': 1, '天': 1, 'w': 7, '周': 7}[unit]
        return today - datetime.timedelta(days=n * days)
    m = re.search(r'(\d+)\s*天前', s)
    if m:
        return today - datetime.timedelta(days=int(m.group(1)))
    return None


def parse_until(spec, today=None):
    """--until 参数 → date (只认绝对日期)

    --until 是"不晚于某天", 跟 --since 的"往前 N 天"方向相反, 语义不能
    混: "--until 7d" 若按"7天前"解, 结果会变成"只要比 7 天前新的" ——
    跟用户想的"截至 7 天前"完全反了。所以 until 只收绝对日期
    (YYYY-MM-DD / YYYY/MM/DD / YYYY年M月D日), 相对写法一律不认。
    """
    today = today or datetime.date.today()
    s = (spec or '').strip()
    if not s:
        return None
    m = _RE_ISO.search(s) or _RE_CN_FULL.search(s)
    if m:
        return _mk(m.group(1), m.group(2), m.group(3))
    return None


def filter_by_date(results, ctx=None):
    """filter 插件入口: 按 --since/--until 过滤结果

    返回过滤后的列表。未知日期的条目默认保留 (见模块 docstring);
    --date-strict 时未知日期也剔掉。
    """
    args = (ctx or {}).get('args')
    since_spec = getattr(args, 'win_start', None) or getattr(args, 'since', None)
    until_spec = getattr(args, 'win_end', None) or getattr(args, 'until', None)
    strict = bool(getattr(args, 'date_strict', False))
    if not since_spec and not until_spec:
        return results

    today = datetime.date.today()
    try:
        from webtool.core.datewindow import parse_window
        since, until = parse_window(since_spec, until_spec, today)
    except ValueError:
        # 语法错就别硬过滤, 交给调用方报错
        return results
    except Exception:
        since = parse_since(since_spec, today)
        until = parse_until(until_spec, today)

    # 距离很远的 --since: 低置信的相对时间/无年月日不可信
    wide = since is not None and (today - since).days > 30

    kept = []
    for r in results:
        d, _src, low = item_date(r, today)
        if d is None:
            if strict:
                continue
            kept.append(r)
            continue
        if low and wide:
            # 低置信日期在很宽的窗口里不足以判死, 放行
            kept.append(r)
            continue
        if since is not None and d < since:
            continue
        if until is not None and d > until:
            continue
        kept.append(r)

    # 剔除条数回报给调用方 (args 是共享命名空间, 写在上面, 流水线读得到)。
    # 累加而非覆盖: 搜索流水线会在补量之后再过一遍本过滤器, 两次剔除的
    # 条数是不同批条目, 直接相加才是真实总量。
    dropped = len(results) - len(kept)
    try:
        args.date_filtered = getattr(args, 'date_filtered', 0) + dropped
    except AttributeError:
        pass
    return kept
