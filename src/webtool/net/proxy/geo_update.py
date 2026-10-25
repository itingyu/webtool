"""geo 数据 (geosite/geoip) 的在线更新

上游 Loyalsoldier/v2ray-rules-dat 的 release 资产: geoip.dat / geosite.dat。
落点与 bootstrap 首次运行时一致 —— 用户目录 ~/.webtool/geo/ (包内那份只读,
升级 pip 包不碰用户数据)。

三个要点:
1. **先下到临时名, 校验格式再改名**。上游 302 到一个 CDN, 网络抽风时可能只
   拿回一个 HTML 错误页; 直接顶着正式文件名落盘 = 把好好的库换成一坨垃圾。
   download() 自身已是 `.part` → 正式名的原子改名, 这里再多一层"格式对不上
   就不换"。
2. **走 webtool 自己的线路决策**。下载 opener 用 build_opener(proxy='auto'),
   github release 在国内基本要代理, 规则表说了算, 不走环境变量那套。
3. **复用 net.download**: 断点续传、进度、熔断都是现成的, 不另起一套。
"""
import os

from webtool.net import geodata as _gd

__all__ = ['update', 'update_all', 'GEO_KINDS']

GEO_KINDS = ('geosite', 'geoip')


def _expect(kind):
    """kind → 该库应有的格式集合 (detect_format 的返回值)"""
    return {'geosite': ('geosite',), 'geoip': ('geoip', 'mmdb')}[kind]


def update(kind, path=None, proxy='auto', jobs=1):
    """更新单个库 → dict {ok, kind, url, path, size?|error?}"""
    if kind not in GEO_KINDS:
        return {'ok': False, 'kind': kind,
                'error': f'未知的 geo 类型 {kind!r} (可选: {"/".join(GEO_KINDS)})'}
    url = _gd.source_of(kind)
    if not url:
        return {'ok': False, 'kind': kind,
                'error': f'没有 {kind} 的下载源 (可用 WEBTOOL_GEO_SOURCE_'
                         f'{kind.upper()} 指定)'}
    dst = os.path.expanduser(path) if path else _gd.user_path(kind)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dst)) or '.', exist_ok=True)
    except OSError as e:
        return {'ok': False, 'kind': kind, 'error': f'建目录失败: {e}', 'path': dst}

    from webtool.core.resilient import open_stream
    from webtool.net.download import download

    tmp = dst + '.new'

    def _open(headers):
        # download 的 opener 契约是 callable(headers) -> (resp, status, via, headers),
        # 不是 urllib 的 OpenerDirector。proxy='auto' 交给 proxyhelper 问规则表
        # (github release 在国内基本要代理)。
        return open_stream(url, proxy=proxy, headers=headers)

    try:
        r = download(url, tmp, _open, jobs=jobs)
    except Exception as e:                                   # noqa: BLE001
        return {'ok': False, 'kind': kind, 'url': url, 'path': dst,
                'error': f'下载失败: {e}'}
    if r.get('error'):
        return {'ok': False, 'kind': kind, 'url': url, 'path': dst,
                'error': r['error']}

    fmt = _gd.detect_format(tmp)
    if fmt not in _expect(kind):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {'ok': False, 'kind': kind, 'url': url, 'path': dst,
                'error': f'下载到的不是 {kind} 库 (认出格式: {fmt or "未知"}), '
                         f'已保留原库不动'}

    os.replace(tmp, dst)                # 同目录原子改名
    return {'ok': True, 'kind': kind, 'url': url, 'path': dst,
            'size': r.get('size')}


def update_all(paths=None, proxy='auto', jobs=1):
    """更新所有库 → {kind: result}"""
    paths = paths or {}
    return {k: update(k, path=paths.get(k), proxy=proxy, jobs=jobs)
            for k in GEO_KINDS}
