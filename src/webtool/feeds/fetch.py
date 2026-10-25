"""feed 拉取与官网/RSSHub 交叉校验

pull_one 单源按配置/路由表取 (不再有"直连优先再代理"); crosscheck 同时拉官网 feed 与 RSSHub 路由, 按 URL
集合的重叠率判定「官网能否等价替代路由」(RSSHub 侧为分母)。
"""

import re

import sys
import time

from webtool.core import urls
from webtool.engines.sites import _fetch, _headers
from webtool.feeds.parse import parse_feed
from webtool.net import proxyhelper

_norm_u = urls.norm_key      # URL 去重键 (比对同一篇文章)
_sec_of = urls.section_of   # URL 首段路径 = 栏目名


# ============================================================ 拉取

def pull_one(name, url, n, proxy, timeout):
    """拉单个 feed → 条目列表 (原序=发布时序; 请求头走 transport 统一指纹)"""
    headers = _headers(url, 'nav', {
        'Accept': 'application/rss+xml, application/atom+xml, '
                  'application/xml, text/xml, */*'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    return parse_feed(txt, name)[:n]


def instance_candidates(preferred, explicit, cfg):
    """取数用实例候选顺序: 显式指定 > 当前最快可用 > 其余可用 > 未探测。

    探活只验了一条路由, 不代表该实例支持所有路由, 所以要多备几个候选。
    """
    from webtool import radar as _radar
    lst = _radar.instances(proxy=cfg.get('proxy'), need=1)
    alive = [it['instance'].rstrip('/') for it in lst if it['ok']]
    unknown = [it['instance'].rstrip('/') for it in lst
               if not it['ok'] and it.get('err') == '未探测']
    out = []
    for x in (explicit.rstrip('/') if explicit else None, preferred,
              *alive, *unknown):
        if x and x not in out:
            out.append(x)
    return out


def _out(*a, **kw):
    """路由卡片等说明性输出走 stderr。

    cli 对 feed 走 redirect_stdout + emit, rc 非 0 时 emit 被跳过, 卡片走
    stdout 会在出错时整段消失。数据输出仍由 render_hot 写 stdout。
    """
    kw.setdefault('file', sys.stderr)
    print(*a, **kw)


def _pick_card(cards, pick):
    """按 --pick 选路由: 纯数字=列表序号(1起), 其它=模板/站名/路由名子串匹配"""
    if not pick:
        if len(cards) == 1:
            return 0, '唯一命中'
        # 多条命中且没指定: 取 heat 最高的, 并说明其余怎么换
        best = max(range(len(cards)), key=lambda i: cards[i]['heat'])
        others = [str(i + 1) for i in range(len(cards)) if i != best]
        return best, (f'未指定 --pick, 自动选 #{best + 1} (heat 最高); '
                      f'换别的用 --pick <{" / ".join(others)}>')
    s = str(pick).strip()
    if s.isdigit():
        i = int(s) - 1
        if not (0 <= i < len(cards)):
            raise SystemExit(f'--pick {s} 越界 (共 {len(cards)} 条)')
        return i, f'--pick {s}'
    hits = [i for i, c in enumerate(cards)
            if s.lower() in c['template'].lower()
            or s.lower() in (c['name'] or '').lower()]
    if not hits:
        raise SystemExit(f'--pick "{s}" 没匹配到任何路由')
    if len(hits) > 1:
        raise SystemExit(f'--pick "{s}" 命中多条 (#{" / ".join(str(i + 1) for i in hits)}), '
                         f'给序号更明确')
    return hits[0], f'--pick {s}'




def _crosscheck(official, rss_url, section, n, cfg, timeout=None,
                instances=None, base=None):
    """同时拉官网 feed 与 RSSHub 路由, 交叉校验官网能否给出该栏目。

    官网侧一条请求; RSSHub 侧候选实例全并发取先到, 避免串行轮换时每个
    挂掉的实例都等满超时。比对只取 URL 集合不比正文: RSSHub 的 link 常带
    utm 之类尾参 (_norm_u 已剥掉), 且 URL 比标题稳定。
    """
    from webtool import radar as _radar
    off_url, _off_n, _buckets = official
    tmo = timeout or cfg.get('timeout', 20)
    # 取数条数要比展示的 n 多, 否则两边窗口对不齐, 重叠率被小样本放大
    want = max(n, 10) * 3

    def pull(url, tag):
        """返回 (items, ms)。按配置/路由表取一次 (线路只由配置决定)。

        单线路: 走哪条由 proxyhelper/路由表决定, 失败原因不被掩盖 ——
        退直连重试会让"代理挂了"表现为"目标拒绝/超时"。
        """
        t0 = time.perf_counter()
        px = proxyhelper.resolve(cfg.get('proxy'), url)
        try:
            got = pull_one(tag, url, want, px, tmo)
        except Exception:
            got = []
        return got, int((time.perf_counter() - t0) * 1000)

    cands = [c for c in (instances or []) if c] or [None]
    t_all = time.perf_counter()
    # RSSHub 多实例并发, race() 收第一个成功的; 挂的随进程退出, 不 join
    path = rss_path(rss_url)
    jobs = {c: (lambda c=c: pull(c.rstrip('/') + path, '_rss')) for c in cands}
    # 官网单起线程, RSSHub 内部才 race: 官网几乎必成功, 进同一 race 会让
    # RSSHub 还没发出请求就被判结束
    import threading
    box = {}

    def run_off():
        box['r'] = pull(off_url, '_off')
    th_off = threading.Thread(target=run_off, daemon=True)
    th_off.start()
    got_all = _radar.race(jobs, ok=lambda r: bool(r and r[0]), timeout=None)
    th_off.join()                        # 官网这一路必须拿到结果才能比对
    off_items, off_ms = box.get('r', ([], 0))
    rss_hits = [(k, v) for k, v in got_all.items() if v and v[0]]
    if rss_hits:
        rss_from, (rss_items, rss_ms) = max(rss_hits, key=lambda kv: len(kv[1][0]))
    else:
        rss_from, rss_items, rss_ms = None, [], 0
    wall_ms = int((time.perf_counter() - t_all) * 1000)

    hit = ([i for i in off_items if _sec_of(i.get('url')) == section]
           if section else off_items)
    off_set = {_norm_u(i.get('url')) for i in hit if i.get('url')}
    rss_set = {_norm_u(i.get('url')) for i in rss_items if i.get('url')}
    overlap = len(off_set & rss_set)
    # 一致率以 RSSHub 侧为分母: 它是该栏目的权威定义
    consist = (overlap / len(rss_set)) if rss_set else 0.0

    if not off_items:
        verdict, use = '官网 feed 拉不到 (或无该栏目条目), 只能用 RSSHub 路由', False
    elif not section:
        verdict, use = ('官网 feed 是全站流, 无法判定是否等价于该路由, 保守用 RSSHub',
                        False)
    elif not hit:
        verdict, use = (f'官网 feed 里没有 /{section} 的条目, 必须用 RSSHub 路由',
                        False)
    elif not rss_set:
        # RSSHub 侧挂了就没法比对, 但官网侧已经确认含该栏目 —— 官网更稳, 用它
        verdict, use = (f'RSSHub 路由没拉到条目 (实例侧问题), 但官网 feed 确认含 '
                        f'/{section} ({len(hit)} 条) —— 用官网', True)
    elif consist >= 0.6:
        verdict, use = (f'官网 feed 的 /{section} 与 RSSHub 路由 {overlap}/{len(rss_set)} '
                        f'一致, 用官网 (免实例依赖)', True)
    else:
        verdict, use = (f'官网 feed 的 /{section} 与 RSSHub 路由 只有 {overlap}/'
                        f'{len(rss_set)} 一致 (官网给的是时序, 路由给的可能是热榜'
                        f'排序), 建议用 RSSHub 路由', False)
    return {'ok': True, 'official_url': off_url, 'official_items': len(off_items),
            'official_hit': len(hit), 'section': section,
            'rss_items': len(rss_items), 'rss_instance': rss_from,
            'official_ms': off_ms, 'rss_ms': rss_ms, 'wall_ms': wall_ms,
            'instances_tried': len(cands), 'rss_hits': len(rss_hits),
            'overlap': overlap, 'consistency': round(consist, 2),
            'verdict': verdict, 'use_official': use,
            # 条目一并带回: 校验已经把两边都拉下来了, 取数直接复用不必再拉
            'official_items_data': hit or off_items,
            'rss_items_data': rss_items}


def rss_path(full_url, base=None):
    """从完整 RSSHub URL 里剥出路径部分 (多实例并发时要各自拼前缀)"""
    u = re.sub(r'^https?://[^/]+', '', full_url or '')
    return u or '/'
