# -*- coding: utf-8 -*-
"""首次运行: 把包内默认配置与证书落到用户目录

pip 安装没有可靠的 post-install 钩子, 更没法在安装时确定用户的 HOME —— 所以
"装完就有一份可编辑的默认配置"由 CLI **首次启动**保证: 用户目录缺哪份就补
哪份, **已有的一律不动**。

只有需要用户直接编辑、且不参与"包内默认 + 用户覆盖"两层合并的文件才在这里
补 (rules.json 路由表只读用户目录那一份)。像 config.json / plugins.json
这类走两层合并的, 不补: 用户不写也生效, 凭空生成一份反而会盖住以后升级的默认值。

证书 (`certs/`) 整棵搬过来, 理由有两条:
  ① `certs/extra/` 是站点证书投放点 —— 目录不存在, 用户按报错里那句"丢进
     ~/.webtool/certs/extra/"去放只会扑空;
  ② `ca-bundle.pem` 落到用户目录后可以被增补 (把企业根 cat 进去), 缺了仍回落
     到包内那份。包目录在 site-packages 里, 升级整棵替换, 不是放东西的地方。
"""
import os
import shutil

from webtool.core.config_data import DATA_DIR, USER_DIR

# 需要以"整份文件"形态落到用户目录的默认配置 (缺失才补)
SEED_FILES = ('rules.json',)

# 证书目录: 整棵从包内搬到用户目录 (缺失才补, 升级不覆盖)
SEED_CERT_FILES = ('ca-bundle.pem', 'README.md')
SEED_CERT_DIRS = ('extra',)


def _copy_missing(src, dst, created):
    """缺失才补 —— 已有的一律不碰 (父目录不在就先建出来)"""
    if dst.exists() or not src.is_file():
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o600)
        created.append(str(dst))
    except OSError:
        pass


def ensure_user_files():
    """补齐缺失的用户配置与证书目录, 返回本次新建的路径列表。

    绝不因落地失败拦住命令: 读不了/写不了就静默跳过, 让上层照常跑。
    """
    created = []
    try:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(USER_DIR, 0o700)
    except OSError:
        return created
    for name in SEED_FILES:
        _copy_missing(DATA_DIR / name, USER_DIR / name, created)

    certs = USER_DIR / 'certs'
    for name in SEED_CERT_FILES:
        _copy_missing(DATA_DIR / 'certs' / name, certs / name, created)
    for sub in SEED_CERT_DIRS:
        dst_dir = certs / sub
        try:
            # 原来就有的目录不算"新建" —— 免得每次运行都往 created 里塞一遍
            existed = dst_dir.is_dir()
            dst_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if not existed:
            created.append(str(dst_dir) + os.sep)
        for src in sorted((DATA_DIR / 'certs' / sub).glob('*')):
            _copy_missing(src, dst_dir / src.name, created)
    return created
