# -*- coding: utf-8 -*-
"""feed 源健康登记表: ~/.webtool/feed_health.json

登记"官网 feed 挂了/被墙/壳化"的站点, 供 --health 查看、--retest 修复后
复查; 恢复后自动从登记表移除。来源两路:
1. 抓取失败时 cli 自动登记 (--health 时的 failed 即实时结果, 持久化在案)
2. 人工登记: --mark NAME 原因说明 (如官方 403 改走 RSSHub 后备注路由)

键: 源名或 URL; 值: {url, reason, status, last_seen, fails, since}
status = last observed 状态 ('403'/'404'/'dns'/'timeout'/'shell'JS壳/
'parse'非XML/'ok')。
"""
import json
import os
import time

PATH = os.path.expanduser('~/.webtool/feed_health.json')

# 源名 → 展示语义 (status 附加诊断), 人工 --mark 时也可传自由文本
REASON_HINTS = {
    '403': '拒绝访问(反爬/WAF)',
    '404': '不存在',
    'dns': 'DNS 解析失败',
    'timeout': '连接超时(墙/IP限制)',
    'shell': 'JS 壳页(需浏览器)',
    'parse': '返回非 RSS/Atom XML',
    'empty': 'feed 合法但 0 条',
}


def _load():
    try:
        with open(PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data):
    d = os.path.dirname(PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def record(key, url, status, reason=None):
    """登记一次失败 (同名累加 fails, 刷新 last_seen)"""
    d = _load()
    e = d.get(key) or {'url': url, 'since': time.strftime('%Y-%m-%d')}
    e.update({'url': url, 'status': str(status),
              'reason': reason or REASON_HINTS.get(str(status), ''),
              'fails': int(e.get('fails', 0)) + 1,
              'last_seen': time.strftime('%Y-%m-%d %H:%M')})
    d[key] = e
    _save(d)
    return e


def mark_ok(key):
    """源恢复 → 从登记表移除"""
    d = _load()
    if key in d:
        d.pop(key)
        _save(d)
        return True
    return False


def manual(key, url, note):
    """人工登记: --mark KEY [URL] 自由备注"""
    e = record(key, url or (key if key.startswith('http') else ''), 'manual',
               note)
    return e


def classify_error(err_msg):
    """从拉取错误串归类状态码语义 (feedhealth.record 用)"""
    s = str(err_msg)
    for code in ('403', '404', '429', '500', '502', '503'):
        if code in s:
            return code
    if 'Name or service not known' in s or 'getaddrinfo' in s or 'DNS' in s.upper():
        return 'dns'
    if 'timed out' in s or 'timeout' in s.lower() or 'Timeout' in s:
        return 'timeout'
    if '非 RSS/Atom XML' in s or '解析失败' in s:
        # JS 壳页返回 HTML 而非 XML
        return 'shell' if ('enablejs' in s or '<html' in s.lower()
                           or 'HTML' in s) else 'parse'
    return 'parse'


def entries():
    """返回 [(key, entry)] 按最近失败倒序"""
    d = _load()
    return sorted(d.items(), key=lambda kv: kv[1].get('last_seen', ''),
                  reverse=True)


def render_text():
    rows = entries()
    if not rows:
        return 'feed 源健康登记表: 空 (全部正常)'
    lines = [f'feed 源健康登记表 ({len(rows)} 项, 按最近失败排序):', '']
    w = max(len(k) for k, _ in rows) + 2
    for k, e in rows:
        lines.append(f'  {k:<{w}} [{e.get("status")}] {e.get("reason", "")}')
        if e.get('url'):
            lines.append(f'  {" " * w} {e["url"]}')
        lines.append(f'  {" " * w} 失败x{e.get("fails", 1)} 最近: '
                     f'{e.get("last_seen")} (自 {e.get("since")})')
        lines.append('')
    lines.append('复查恢复: webtool feed --retest KEY / 全量: --retest all')
    lines.append('人工登记: webtool feed --mark KEY [URL] "原因备注"')
    return '\n'.join(lines)
