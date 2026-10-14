"""
巨潮 fetcher
============
沙盒验证：公司简介（3718B）/ 公告 POST（13136B）通
关键：orgId 必须先查 stockList 拿（硬编码前缀 gssh/szsh 不全）

数据流：
  1. 启动时拉一次 szse_stock.json → {code: orgId} 缓存
  2. announcements 用 orgId 调 hisAnnouncement/query
  3. 失败兜底：硬编码前缀（不保证全准）
"""
from datetime import datetime, timedelta
import threading

from webtool.stock.skill.scripts._common import std_session, log


# ============================================================
#  orgId 缓存（thread-safe lazy load）
# ============================================================
_ORG_ID_CACHE = {}
_ORG_ID_LOCK = threading.Lock()
_ORG_ID_LOADED = False


def _load_org_id_cache():
    """从 cninfo 公开接口拉一次 stockList，构建 {code: orgId} 缓存"""
    global _ORG_ID_LOADED
    try:
        s = std_session()
        r = s.get(
            "https://www.cninfo.com.cn/new/data/szse_stock.json",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.cninfo.com.cn/",
            },
            timeout=12,
        )
        if r.status_code != 200:
            return
        j = r.json()
        for st in j.get("stockList", []):
            code = st.get("code")
            org = st.get("orgId")
            if code and org:
                _ORG_ID_CACHE[code] = org
        _ORG_ID_LOADED = True
        log(f"cninfo orgId 缓存 {len(_ORG_ID_CACHE)} 条", level="INFO")
    except Exception as e:
        log(f"cninfo orgId 缓存加载失败: {e}", level="WARN")


def _get_org_id(code):
    """根据 6 位 A 股代码拿 orgId（lazy load）"""
    if code in _ORG_ID_CACHE:
        return _ORG_ID_CACHE[code]
    with _ORG_ID_LOCK:
        if not _ORG_ID_LOADED:
            _load_org_id_cache()
    if code in _ORG_ID_CACHE:
        return _ORG_ID_CACHE[code]
    # 兜底：硬编码前缀（旧逻辑，命中率低）
    if code.startswith(("600", "601", "603", "688", "9", "5")):
        return f"gssh{code}"
    if code.startswith(("000", "002", "300", "301", "8")):
        return f"szsh{code}"
    return f"gssh{code}"


# ============================================================
#  公司简介
# ============================================================
def company_intro(code):
    """
    公司基本资料
    code: 6 位 A 股代码
    """
    try:
        r = std_session().get(
            f"https://www.cninfo.com.cn/data20/companyOverview/"
            f"getCompanyIntroduction?scode={code}",
            timeout=10,
        )
        if r.status_code != 200:
            log(f"巨潮 company_intro {code} HTTP {r.status_code}", "WARN")
            return {}
        data = r.json()
        # 接口实际返回 {"path": ..., "data": {...真实数据...}, "code": "..."}
        inner = data.get("data") if isinstance(data, dict) else None
        if not inner:
            log(f"巨潮 company_intro {code} 返回空 data", "WARN")
            return {}
        return data
    except Exception as e:
        log(f"巨潮 company_intro {code} 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return {}


# ============================================================
#  公告列表
# ============================================================
def announcements(code, days=30, searchkey=None):
    """
    公司公告（最近 N 天）
    code: 6 位 A 股代码
    days: 回溯天数（默认 30）

    返回: [{title, time, url, type}]
    """
    try:
        org_id = _get_org_id(code)
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # 必须先访问详情页拿 cookies（cninfo 反爬）
        s = std_session()
        s.get(
            f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )

        r = s.post(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data={
                "stock": f"{code},{org_id}",
                "tabName": "fulltext",
                "pageSize": "30",
                "pageNum": "1",
                "column": "sse",
                "category": "",
                "plate": "",
                "seDate": f"{start}~{end}",
                "searchkey": searchkey or "",
                "secid": "",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            },
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://www.cninfo.com.cn",
                "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            },
            timeout=12,
        )
        if r.status_code != 200:
            log(f"巨潮 announcements {code} HTTP {r.status_code}", "WARN")
            return []
        anns = r.json().get("announcements") or []
        if not anns:
            log(f"巨潮 announcements {code} {days}天内 0 条公告", "INFO")
            return []
        out = []
        for a in anns:
            out.append({
                "title": a.get("announcementTitle"),
                "time": a.get("announcementTime"),
                # 2026-08 巨潮 PDF 域名已迁移：www → static（API 仍走 www）
                "url": "https://static.cninfo.com.cn/" + a.get("adjunctUrl", ""),
                "type": a.get("adjunctType"),
            })
        return out
    except Exception as e:
        log(f"巨潮 announcements {code} 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return []
