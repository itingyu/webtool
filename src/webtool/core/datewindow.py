"""--since/--until 统一解析: 相对时间与绝对日期都变成 date 窗口

认得:
  7d / 7天 / 近7天 / 2周 / 3个月 / 1y / 24h / 30min
  today/今天, yesterday/昨天, 前天, 本周, 上周, 本月, 上月, 今年, 去年
  2026-10-01 / 2026/10/1 / 2026.10.1 / 20261001
只给一端时: 只给 since 则 end=今天; 只给 until 则 start 留空。
"""
import datetime as dt
import re

_UNIT_DAYS = {
    '分钟': 1 / 1440, 'min': 1 / 1440, 'mins': 1 / 1440, 'minute': 1 / 1440,
    '小时': 1 / 24, 'h': 1 / 24, 'hr': 1 / 24, 'hour': 1 / 24,
    '天': 1, '日': 1, 'd': 1, 'day': 1,
    '周': 7, '星期': 7, 'w': 7, 'week': 7,
    '个月': 30, 'month': 30, 'mo': 30,
    '年': 365, 'y': 365, 'year': 365,
}
_RE_REL = re.compile(
    r'^(?:近|最近|past\s*)?(\d+)\s*'
    r'(分钟|小时|天|日|周|星期|个月|月|年|mins?|minutes?|h|hr|hours?|'
    r'd|days?|w|weeks?|months?|mo|y|years?)(?:前|ago)?$', re.I)
_RE_ABS = re.compile(r'^(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})$|^(20\d{2})(\d{2})(\d{2})$')

_KEYWORDS = {
    'today': 'today', '今天': 'today', '今日': 'today',
    'yesterday': 'yesterday', '昨天': 'yesterday', '昨日': 'yesterday',
    '前天': 'before_yesterday',
    '本周': 'this_week', '这周': 'this_week', 'this week': 'this_week',
    '上周': 'last_week', 'last week': 'last_week',
    '本月': 'this_month', '这个月': 'this_month', 'this month': 'this_month',
    '上月': 'last_month', '上个月': 'last_month', 'last month': 'last_month',
    '今年': 'this_year', 'this year': 'this_year',
    '去年': 'last_year', 'last year': 'last_year',
}


def _kw_date(tag, now):
    d = now.date() if isinstance(now, dt.datetime) else now
    if tag == 'today':
        return d
    if tag == 'yesterday':
        return d - dt.timedelta(days=1)
    if tag == 'before_yesterday':
        return d - dt.timedelta(days=2)
    if tag in ('this_week', 'last_week'):
        monday = d - dt.timedelta(days=d.weekday())
        return monday if tag == 'this_week' else monday - dt.timedelta(days=7)
    if tag in ('this_month', 'last_month'):
        first = d.replace(day=1)
        if tag == 'this_month':
            return first
        return (first - dt.timedelta(days=1)).replace(day=1)
    if tag == 'this_year':
        return d.replace(month=1, day=1)
    return d.replace(year=d.year - 1, month=1, day=1)


def parse_date(text, now=None):
    """单个值 → date; 认不出返回 None"""
    if not text:
        return None
    s = str(text).strip().lower()
    now = now or dt.datetime.now()
    if not s:
        return None
    if s in _KEYWORDS:
        return _kw_date(_KEYWORDS[s], now)
    m = _RE_REL.match(s)
    if m:
        num = int(m.group(1))
        unit = m.group(2).lower()
        days = _UNIT_DAYS.get(unit)
        if days is None:
            return None
        anchor = now if isinstance(now, dt.datetime) else dt.datetime.combine(now, dt.time())
        return (anchor - dt.timedelta(days=num * days)).date()
    m = _RE_ABS.match(s)
    if m:
        y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (
            m.group(4), m.group(5), m.group(6))
        try:
            return dt.date(int(y), int(mo), int(d))
        except ValueError:
            return None
    return None


def parse_window(since=None, until=None, now=None):
    """(since, until) → (start_date|None, end_date|None); 不合法抛 ValueError"""
    now = now or dt.datetime.now()
    if now.tzinfo is None:
        now = now.astimezone()
    start = parse_date(since, now)
    end = parse_date(until, now)
    if since and start is None:
        raise ValueError(f'认不出 --since "{since}" (用 7d/3周/2026-10-01 这种)')
    if until and end is None:
        raise ValueError(f'认不出 --until "{until}" (用 7d/3周/2026-10-01 这种)')
    if start and not end:
        end = now.date()
    if start and end and start > end:
        raise ValueError(f'--since {start} 晚于 --until {end}')
    return start, end


def to_epoch(d):
    """date → 当地零点的时间戳 (百度 gpc 用)"""
    return int(dt.datetime.combine(d, dt.time()).timestamp())


def gfmt(d):
    """Google/Bing 的 M/D/YYYY (不带前导零)"""
    return f'{d.month}/{d.day}/{d.year}'


def iso(d):
    return d.isoformat()
