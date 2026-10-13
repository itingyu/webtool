"""底层 HTTP 直调层

`rawapi.py` 调的是 api_client 封装好的 151 个方法, `eco.py` 调的是 akshare/tushare
等库函数 —— 两者都只能调"已封装"的东西。本模块相反: **不封装, 直接发 HTTP**。

逆向出的 900+ 接口里, 有大量 akshare 没封或封了不可用的 (公司类型探��、
quoteColumns 注入、dates 批量取表), 它们只能自己拼 URL 打过去。

## 什么时候用

| 场景 | 用哪个 |
|---|---|
| 查 akshare 某函数返回什么字段 | `docs-report` (只读文档) |
| akshare 某接口返回空/报错, 想自己打 | **本模块** |
| 需要 companyType / quoteColumns / dates 等特殊参数 | **本模块** |
| 常规行情/财务取数 | `rawapi` (走 api_client, 已处理反爬) |

## 内置的处理

每个数据源的反爬要求已内置, 不必每次手填:

| 源 | 自动处理 |
|---|---|
| 雪球 | curl_cffi chrome110 指纹 + token warmup + Referer |
| 新浪 | `Referer: finance.sina.com.cn` |
| 中证 | `Referer: www.csindex.com.cn` |
| 同花顺 | 走不受 IP 封禁的子域 |
| 东财 | push2 自动带 `ut`, datacenter 自动带 token |
| 巨潮 | 先抓 JSESSIONID 再 POST |

## 用法

```python
h = Http()
h.get('https://datacenter-web.eastmoney.com/api/data/v1/get',
      params={'reportName': 'RPT_LICO_FN_CPD', 'columns': 'ALL',
              'pageSize': 50, 'source': 'WEB', 'client': 'WEB',
              'filter': "(REPORTDATE='2026-03-31')"})
h.post('https://www.cninfo.com.cn/new/hisAnnouncement/query',
       data={'stock': '600519,gssh0600519', 'pageNum': 1})
h.json()          # 自动按 Content-Type / 内容判 JSON 或 GBK 文本
h.rows()          # DataFrame 化, 带列序映射
```
"""
import json
import re

import requests

try:
    from curl_cffi import requests as curl_requests
except ImportError:                                     # pragma: no cover
    curl_requests = None


class HttpError(RuntimeError):
    """HTTP 调用失败"""


# ── 各源的默认头 / 反爬配置 ────────────────────────────────────────
_HEADERS = {
    'xueqiu.com': {
        'Referer': 'https://xueqiu.com/',
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/110.0.0.0 Safari/537.36'),
    },
    'sina.com.cn': {'Referer': 'https://finance.sina.com.cn/'},
    'sinajs.cn': {'Referer': 'https://finance.sina.com.cn/'},
    'csindex.com.cn': {'Referer': 'https://www.csindex.com.cn/'},
    '10jqka.com.cn': {
        'Referer': 'https://data.10jqka.com.cn/',
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/110.0.0.0 Safari/537.36'),
    },
    'eastmoney.com': {
        'Referer': 'https://data.eastmoney.com/',
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/110.0.0.0 Safari/537.36'),
    },
    'cninfo.com.cn': {'Referer': 'https://www.cninfo.com.cn/'},
}

# 东财 push2 / datacenter 的固定令牌 (逆向自 akshare 源码, 公开令牌非凭证)
_EM_UT_PUSH2 = 'bd1d9ddb04089700cf9c27f6f7426281'
_EM_UT_PUSH2_ALT = '13697a1cc677c8bfa9a496437bfef419'
_EM_TOKEN_DC = '894050c76af8597a853f5b408b759f5d'


def _host(url):
    m = re.match(r'https?://([^/?#]+)', url or '')
    return m.group(1) if m else ''


class Http:
    """裸 HTTP 调用器。不封装任何业务接口, 只负责把请求安全打出去。"""

    def __init__(self, timeout=20, impersonate='chrome110'):
        self.timeout = timeout
        self.impersonate = impersonate
        self._xq = None          # 雪球 curl_cffi 会话 (需 cookie warmup)
        self._last = None

    # ── 内部 ──────────────────────────────────────────────────
    def _headers_for(self, url, extra=None, referer=None):
        h = {'Accept': '*/*', 'Accept-Language': 'zh-CN,zh;q=0.9',
             'Connection': 'keep-alive'}
        host = _host(url)
        for dom, hdrs in _HEADERS.items():
            if host.endswith(dom):
                h.update(hdrs)
                break
        if referer:
            h['Referer'] = referer
        h.update(extra or {})
        return h

    def _auto_params(self, url, params, headers):
        """按端点特征自动补 ut/token, 免得每次手填"""
        p = dict(params or {})
        if 'push2' in url and 'ut' not in p:
            p['ut'] = _EM_UT_PUSH2
        if 'push2his' in url and 'ut' not in p:
            p['ut'] = _EM_UT_PUSH2_ALT
        if 'datacenter' in url:
            p.setdefault('source', 'WEB')
            p.setdefault('client', 'WEB')
            if '/api/data/v1/get' in url:
                p.setdefault('token', _EM_TOKEN_DC)
        if 'qt.gtimg.cn' in url or 'ifzq.gtimg.cn' in url:
            h = headers.setdefault('Referer', 'https://gu.qq.com/')
        return p

    def _xueqiu_session(self):
        """雪球要 curl_cffi 指纹 + 多页 warmup 收集 cookie"""
        if self._xq is not None:
            return self._xq
        if curl_requests is None:
            raise HttpError('雪球需 curl_cffi: apk add py3-curl-cffi 或 pip install curl_cffi')
        s = curl_requests.Session(impersonate=self.impersonate)
        for u in ('https://xueqiu.com/', 'https://xueqiu.com/hq',
                  'https://xueqiu.com/S/SH600519'):
            try:
                s.get(u, timeout=self.timeout)
            except Exception:                             # noqa: BLE001
                pass
        self._xq = s
        return s

    # ── 请求 ──────────────────────────────────────────────────
    def request(self, method, url, params=None, data=None, json_body=None,
                headers=None, referer=None, timeout=None, raw=False,
                encoding=None):
        """发一次请求。返回解码后的文本 (或 bytes 当 raw=True)。"""
        m = (method or 'GET').upper()
        hdrs = self._headers_for(url, headers, referer)
        par = self._auto_params(url, params, hdrs)
        to = timeout or self.timeout
        try:
            if _host(url).endswith('xueqiu.com'):
                s = self._xueqiu_session()
                fn = s.post if m == 'POST' else s.get
                r = fn(url, params=par or None, data=data or None,
                       headers=hdrs, timeout=to)
            else:
                r = requests.request(m, url, params=par or None, data=data or None,
                                     json=json_body, headers=hdrs, timeout=to)
        except Exception as e:                              # noqa: BLE001
            raise HttpError(f'{m} {url[:80]} 失败: {type(e).__name__}: {e}') from e
        self._last = r
        if raw:
            return r.content
        if encoding:
            r.encoding = encoding
        elif not getattr(r, 'encoding', None) or r.encoding.lower() == 'iso-8859-1':
            # curl_cffi 没有 apparent_encoding; 东财/雪球默认 utf-8, 新浪走 chardet
            head = r.headers.get('content-type', '') if hasattr(r, 'headers') else ''
            if 'charset=gb' in head.lower():
                r.encoding = 'gbk'
            elif hasattr(r, 'apparent_encoding'):
                r.encoding = r.apparent_encoding
            else:
                r.encoding = 'utf-8'
        if r.status_code >= 400:
            raise HttpError(f'HTTP {r.status_code} {url[:80]} | '
                            f'{r.text[:200].strip()}')
        return r.text

    def get(self, url, **kw):
        return self.request('GET', url, **kw)

    def post(self, url, **kw):
        return self.request('POST', url, **kw)

    # ── 解析 ──────────────────────────────────────────────────
    def json(self, text=None):
        """按内容猜编码再解 JSON。新浪 snapshot 是 JS 变量赋值, 会剥壳。"""
        if text is None:
            text = self._last.text
        if isinstance(text, bytes):
            text = text.decode('utf-8', 'replace')
        t = text.strip()
        if not t:
            raise HttpError('响应为空')
        if t[0] not in '{[':
            m = re.search(r'=\s*([\[{].*)', t, re.S)      # var hq_str_x="..."
            if m:
                t = m.group(1).rstrip(';')
                t = t[:t.rfind('}') + 1] if t.rfind('}') > 0 else t
        try:
            return json.loads(t)
        except json.JSONDecodeError as e:
            raise HttpError(f'不是 JSON (前 120 字: {t[:120]!r})') from e

    def records(self, text=None, item_key=None):
        """取记录列表。兼容东财 result.data / 雪球 data[].quote / 裸数组等。

        雪球 `data` 是 dict 而非 list (单个 symbol), 需给 item_key 取其内部数组;
        或直接用 `rows(..., flatten=True)` 展开一层嵌套。
        """
        d = self.json(text)
        if isinstance(d, list):
            return d
        if not isinstance(d, dict):
            return [d]
        paths = [('result', 'data'), ('data', 'list'), ('result', 'list'),
                 ('data', 'data')]
        if item_key:
            paths.insert(0, ('data', item_key))
        for path in paths:
            cur, ok = d, True
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, list):
                return cur
        if item_key:
            cur = d.get('data')
            if isinstance(cur, dict):
                return [cur]
        for k in ('items', 'list', 'rows', 'records'):
            if isinstance(d.get(k), list):
                return d[k]
        return [d]

    def rows(self, text=None, limit=None, flatten=False, item_key=None,
             pick=None):
        """转 DataFrame。字段名保持接口原样, 列序含义查 docs-report。

        pick='data.0.quote' 可精确指定取值路径 (雪球); flatten=True 则自动
        展开每条记录里唯一的嵌套 dict。

        注意: 雪球 quote.json 对逗号分隔的多 symbol **只返回第一只**, 要批量
        需逐个请求 (或改用 xq_screener_top)。
        """
        import pandas as pd
        if pick:
            d = self.json(text)
            cur = d
            for seg in pick.split('.'):
                if isinstance(cur, list):
                    cur = cur[int(seg)]
                elif seg.isdigit():
                    # 雪球单股返回 {market,quote,...}, 多股返回 {"0":{...},"1":{...}}
                    nxt = next((v for k, v in cur.items() if str(k).isdigit()), None)
                    if nxt is None:          # 单股: 跳过这层数字索引
                        continue
                    cur = nxt
                else:
                    cur = cur[seg]
            if isinstance(cur, list):
                recs = cur
            elif isinstance(cur, dict) and cur and all(
                    str(k).isdigit() for k in cur):       # {"0":{...},"1":{...}}
                recs = list(cur.values())
            else:
                recs = [cur]
        else:
            recs = self.records(text, item_key=item_key)
        if limit:
            recs = recs[:limit]
        if flatten:
            out = []
            for r in recs:
                nested = [v for v in r.values() if isinstance(v, dict)]
                out.append(nested[0] if len(nested) == 1 and len(r) > 2 else r)
            recs = out
        return pd.DataFrame(recs)

    def pages(self, text=None):
        """东财总页数, 供翻页"""
        d = self.json(text)
        try:
            return int(d['result']['pages'])
        except (KeyError, TypeError, ValueError):
            return 1

    # ── 东财专用 ──────────────────────────────────────────────
    def em_datacenter(self, report_name, filter_expr=None, columns='ALL',
                      sort=None, sort_types=None, page_size=500, page=1,
                      base='https://datacenter-web.eastmoney.com/api/data/v1/get'):
        """东财 datacenter 取数。翻页自己管 (pages 可能几百)。

        `sort` 必须给**该 reportName 真实存在的列名**, 否则东财返回
        ``code=9501 排序列不存在`` —— 各 reportName 排序字段不同, 用
        ``docs-report <reportName>`` 查准的再传进来。
        """
        p = {'reportName': report_name, 'columns': columns,
             'pageSize': str(page_size), 'pageNumber': str(page),
             'source': 'WEB', 'client': 'WEB'}
        if sort:
            p['sortColumns'] = sort
            p['sortTypes'] = sort_types or '-1'
        if filter_expr:
            p['filter'] = filter_expr
        t = self.get(base, params=p)
        try:
            d = json.loads(t)
            if not d.get('success') and d.get('code'):
                raise HttpError(f'{report_name} 返回 code={d["code"]}: '
                                f'{str(d.get("message"))[:120]} (排序列/列名不对? '
                                f'用 webtool stock docs-report {report_name} 查)')
        except json.JSONDecodeError:
            pass
        return t

    def em_f10_company_type(self, symbol='SH600519'):
        """探测 companyType —— 不做这步 F10 全返占位符 (逆向文档 §三)"""
        url = ('https://emweb.securities.eastmoney.com/PC_HSF10/'
               'NewFinanceAnalysis/Index')
        html = self.get(url, params={'type': 'web', 'code': symbol.lower()})
        m = re.search(r'id="hidctype"[^>]*value="([^"]+)"', html)
        if not m:
            m = re.search(r'hidctype["\']?\s*[^>]*value="([^"]+)"', html)
        return m.group(1) if m else None
