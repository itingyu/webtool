# -*- coding: utf-8 -*-
"""首次运行: 把包内默认配置文件落到用户目录

pip 安装没有可靠的 post-install 钩子, 更没法在安装时确定用户的 HOME —— 所以
"装完就有一份可编辑的默认配置"由 CLI **首次启动**保证: 用户目录缺哪份就补
哪份, **已有的一律不动**。

只有需要用户直接编辑、且不参与"包内默认 + 用户覆盖"两层合并的文件才在这里
补 (目前是 rules.json —— 路由表只读用户目录那一份)。像 config.json / plugins.json
这类走两层合并的, 不补: 用户不写也生效, 凭空生成一份反而会盖住以后升级的默认值。
"""
import os
import shutil

from webtool.core.config_data import DATA_DIR, USER_DIR

# 需要以"整份文件"形态落到用户目录的默认配置 (缺失才补)
SEED_FILES = ('rules.json',)


def ensure_user_files():
    """补齐缺失的用户配置文件, 返回本次新建的文件路径列表。

    绝不因落地失败拦住命令: 读不了/写不了就静默跳过, 让上层照常跑。
    """
    created = []
    try:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(USER_DIR, 0o700)
    except OSError:
        return created
    for name in SEED_FILES:
        dst = USER_DIR / name
        src = DATA_DIR / name
        if dst.exists() or not src.is_file():
            continue                    # 用户已有 → 永不覆盖
        try:
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)
            created.append(str(dst))
        except OSError:
            continue
    return created
