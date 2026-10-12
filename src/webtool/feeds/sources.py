"""feed 源清单: 随包精选种子 + 用户增删, 两层合并后落 ~/.webtool/feeds.json

种子 (data/feeds.seed.json) 只增不覆盖 —— 用户 --add/--del 过的同名项以
用户版本为准; 写盘失败静默, 种子只是便利, 挂了不该让命令报错。
"""

import os

from webtool.core import config_data
from webtool.core import jsonfmt

FEEDS_FILE = os.path.expanduser('~/.webtool/feeds.json')
FEED_STATE_FILE = os.path.expanduser('~/.webtool/feed_state.json')
# 随包分发的精选源种子 (~/.webtool/feeds.json 不存在时自动落盘)
SEED_FILE = str(config_data.DATA_DIR / 'feeds.seed.json')


def load_seed_feeds():
    """随包精选源: data/feeds.seed.json {name: {url, desc}}"""
    d = jsonfmt.read(SEED_FILE)
    return {k: (v if isinstance(v, dict) else {'url': v}) for k, v in d.items()}


def _seed_user_feeds(user):
    """把 seed 里用户还没有的源并入 ~/.webtool/feeds.json。

    只增不覆盖: 用户 --add/--del 过的同名项以用户版本为准。写盘失败一律
    静默 —— 种子只是便利, 挂了不该让命令报错。
    """
    seed = load_seed_feeds()
    added = [k for k in seed if k not in user]
    if not added:
        return user
    merged = dict(seed)
    merged.update(user)          # 用户同名项优先
    try:
        save_user_feeds(merged)
    except Exception:
        return user
    return merged


def load_user_feeds():
    """用户自定义源: ~/.webtool/feeds.json {name: {url, desc}}"""
    d = jsonfmt.read(FEEDS_FILE)
    user = {k: (v if isinstance(v, dict) else {'url': v}) for k, v in d.items()}
    return _seed_user_feeds(user)


def save_user_feeds(d):
    jsonfmt.write(FEEDS_FILE, d)
