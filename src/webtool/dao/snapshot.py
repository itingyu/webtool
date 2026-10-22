"""页面快照存取: ~/.webtool/snapshots/<名>.json

一个名字对应一个页面, 里面按时间留多版正文 (默认留最近 KEEP 版)。存的是
`fetch` 已提取的纯文本, 不是 HTML —— diff 要比的是"页面说了什么变了", 不是
class 名改没改; 要原始 HTML 请自己 `fetch --raw` 落盘。

分层: dao 只做存取, 不 import core (见 tests/test_layering.py 的 UPPER 表);
URL → 文件名的规则也放这里, 免得 cli / diff 各写一份而不一致。
"""

import hashlib
import json
import os
import re
import time
from urllib.parse import unquote, urlparse

KEEP = 20                       # 每个名字留多少版历史
NAME_MAX = 80

_BAD = re.compile(r'[\\/:*?"<>|\s\x00-\x1f]+')


def base_dir():
    """快照根目录; 与 state.json / cache 同源 (WEBTOOL_DIR 可整体搬走)"""
    base = os.environ.get('WEBTOOL_DIR') or '~/.webtool'
    return os.path.join(os.path.expanduser(base), 'snapshots')


def slugify(url):
    """URL → 默认快照名: 主机 + 路径, 去掉协议/查询串/百分号编码噪音

    同一 URL 永远得到同一个名字 (快照能自然接上); 两个不同 URL 撞名时,
    调用方用 --name 区分 —— 撞了不静默覆盖, 见 save()。
    """
    p = urlparse(url if '//' in url else '//' + url)
    host = (p.netloc or '').lower().removeprefix('www.')
    path = unquote(p.path).strip('/')
    raw = (host + ('-' + path.replace('/', '-') if path else '')) or 'snapshot'
    raw = _BAD.sub('-', raw).strip('-')
    if not raw:
        raw = 'snapshot-' + hashlib.sha1(url.encode()).hexdigest()[:8]
    return raw[:NAME_MAX]


def _path(name):
    safe = _BAD.sub('-', str(name)).strip('-') or 'snapshot'
    return os.path.join(base_dir(), safe + '.json')


def _read(name):
    try:
        with open(_path(name), encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get('versions') else None
    except (OSError, ValueError):
        return None


def _write(doc):
    path = _path(doc['name'])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)


def save(url, content, title=None, name=None):
    """存一版 → dict(新增/未变, 版本信息)

    内容与上一版完全相同 (sha 相同) 就不追加, 只更新 checked 时间 —— 快照
    命令常被定时任务反复调用, 每次都塞一版会让历史全是重复。
    """
    name = name or slugify(url)
    doc = _read(name) or {'name': name, 'url': url, 'versions': []}
    sha = hashlib.sha1((content or '').encode('utf-8')).hexdigest()
    vs = doc['versions']
    now = int(time.time())
    if vs and vs[-1].get('sha') == sha:
        vs[-1]['checked'] = now
        _write(doc)
        return {'name': name, 'url': url, 'changed': False,
                'version': len(vs), 'ts': vs[-1]['ts'], 'chars': vs[-1]['chars']}
    vs.append({'ts': now, 'sha': sha, 'chars': len(content or ''),
               'title': title or '', 'content': content or ''})
    del vs[:-KEEP]                      # 只留最近 KEEP 版, 老内容真删掉
    doc['url'] = url
    _write(doc)
    return {'name': name, 'url': url, 'changed': True,
            'version': len(vs), 'ts': now, 'chars': len(content or '')}


def load(name, version=None):
    """取某名字的第 version 版 (负数从末尾数, None=最新) → dict 或 None"""
    doc = _read(name)
    if not doc:
        return None
    try:
        v = doc['versions'][version if version is not None else -1]
    except IndexError:
        return None
    return {'name': doc['name'], 'url': doc.get('url') or '',
            'ts': v.get('ts'), 'chars': v.get('chars'),
            'title': v.get('title') or '', 'content': v.get('content') or ''}


def versions(name):
    """某名字的版本列表 (只要元信息, 不带正文)"""
    doc = _read(name)
    if not doc:
        return []
    return [{'n': i + 1, 'ts': v.get('ts'), 'chars': v.get('chars'),
             'sha': v.get('sha'), 'title': v.get('title') or ''}
            for i, v in enumerate(doc['versions'])]


def exists(name):
    return _read(name) is not None


def listing():
    """所有快照 → [{name, url, versions, latest_ts, latest_chars}]"""
    d = base_dir()
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith('.json') or fn.endswith('.tmp'):
            continue
        doc = _read(fn[:-5])
        if not doc:
            continue
        vs = doc['versions']
        out.append({'name': doc.get('name') or fn[:-5],
                    'url': doc.get('url') or '',
                    'versions': len(vs),
                    'latest_ts': vs[-1].get('ts'),
                    'latest_chars': vs[-1].get('chars')})
    return out


def remove(name):
    try:
        os.unlink(_path(name))
        return True
    except OSError:
        return False
