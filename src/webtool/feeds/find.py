"""订阅源模糊搜索: 键名 / 站名 / 域名 / 描述 / 分类

覆盖三层源: 预设种子 + 自定义 + RSSHub 派生 (4000+), 全量清单不刷屏,
靠这里按关键词找。匹配是大小写无关的子串; 排序 = 精确键名 > 前缀 >
键名命中 > 其它字段命中, 同档按热度降序。
"""
import urllib.parse


def _domain(url):
    try:
        host = urllib.parse.urlparse(str(url or '')).netloc.lower()
    except Exception:
        return ''
    host = host.split(':')[0]
    return host[4:] if host.startswith('www.') else host


def _rank(key, q, fields):
    k = key.lower()
    if k == q:
        return 0
    if k.startswith(q):
        return 1
    if q in k:
        return 2
    if any(q in f for f in fields):
        return 3
    return 9


def search(user, derived, word, limit=20, cat=None):
    """返回 [{key, desc, origin, params, url, heat}], 已排序截断"""
    q = (word or '').strip().lower()
    if not q:
        return []
    rows = []
    for key, v in ([] if cat else (user or {}).items()):
        desc = (v.get('desc') or '') if isinstance(v, dict) else ''
        url = (v.get('url') or '') if isinstance(v, dict) else str(v)
        dom = _domain(url)
        fields = [desc.lower(), dom, url.lower()]
        r = _rank(key, q, fields)
        if r < 9:
            rows.append((r, 0, key, {'key': key, 'desc': desc, 'origin': 'custom',
                                     'params': [], 'url': url, 'heat': 0}))
    for key, e in (derived or {}).items():
        if key in (user or {}):
            continue
        cats = [c.lower() for c in (e.get('categories') or [])]
        if cat and cat.lower() not in cats:
            continue
        fields = [str(e.get('desc') or '').lower(),
                  str(e.get('site') or '').lower(),
                  str(e.get('group') or '').lower(),
                  str(e.get('domain') or '').lower(),
                  str(e.get('route_name') or '').lower(),
                  str(e.get('doc') or '').lower()] + cats
        r = _rank(key, q, fields)
        if r < 9:
            rows.append((r, -(e.get('heat') or 0), key,
                         {'key': key, 'desc': e.get('desc') or '',
                          'origin': 'radar',
                          'params': list((e.get('params') or {}).keys()),
                          'url': e.get('template') or '',
                          'heat': e.get('heat') or 0}))
    rows.sort(key=lambda x: (x[0], x[1], x[2]))
    return [x[3] for x in rows[:max(int(limit or 20), 1)]]
