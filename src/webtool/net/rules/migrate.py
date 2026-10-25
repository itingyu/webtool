"""规则表加载时的迁移: 命名代理里的明文密码 → 保险库密文

把 rules.json 的 proxies 段里带明文密码的 URL 迁进 proxy_auth 保险库,
文件里只留 `user@host`, 出网时由 resolve_auth 补回。幂等。
"""
import json
import os


def migrate_plaintext_proxies(spec, cfg_path=None):
    """把规则表 proxies 段里的**明文密码**迁进保险库, 返回 (spec, 迁移条数)

    命名代理的 URL 写在 rules.json 里, 而 rules.json 是要人工编辑的文件 ——
    密码写在里面就是明文落盘, 与 proxy_auth 保险库那套机制割裂了。这里在
    加载时迁移: 密码存进 config.json 的 proxy_auth (密文), rules.json
    只留 `user@host`, 出网时由 resolve_auth 补回 (上层两条通道都调它)。

    幂等: 迁完再读不会重复处理。没装 cryptography 时原样返回 —— 不能因为
    加密依赖缺失就让用户的规则彻底跑不起来, 那比明文更糟。
    """
    from webtool.core import secrets_store as _S
    from webtool.net.proxy import proxy_url_parts
    proxies = (spec or {}).get('proxies')
    if not isinstance(proxies, dict) or not _S.have_crypto():
        return spec, 0
    n = 0
    for name, entry in proxies.items():
        url = entry.get('url') if isinstance(entry, dict) else entry
        if not url or not isinstance(url, str):
            continue
        scheme, user, password, host, port = proxy_url_parts(url)
        if not password:
            continue                    # 已是 user@host, 无需迁移
        try:
            _S.store_password(f'{user}@{host}' + (f':{port}' if port else ''),
                              password)
        except Exception:
            continue                    # 存不进去就保持原样, 不丢配置
        clean = (f'{scheme}://{user}@{host}' + (f':{port}' if port else ''))
        if isinstance(entry, dict):
            entry['url'] = clean
        else:
            proxies[name] = clean
        n += 1
    if n and cfg_path and os.path.isfile(cfg_path):
        try:
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(spec, f, ensure_ascii=False, indent=2)
            os.chmod(cfg_path, 0o600)
        except OSError:
            pass
    return spec, n
