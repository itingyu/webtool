# -*- coding: utf-8 -*-
"""重构前行为基线捕获: 跑一组固定 argv, 存 stdout/rc 快照到 /tmp/baseline.json

重构后用同一脚本比对 (ignoring 时间戳/耗时/缓存标记字段)。
用法: python3 _baseline.py save|check
"""
import io
import json
import os
import re
import subprocess
import sys

CASES = [
    ['--help'], ['search', '--help'], ['feed', '--help'], ['rank', '--help'],
    ['zen', '--help'], ['site', '--help'], ['engines', '--help'],
    ['fetch', '--help'], ['config', '--help'], ['blocklist', '--help'],
    ['engines', 'list'], ['cache', 'info'], ['proxy', 'get'],
    ['engines', 'test', 'bing'], ['engines', 'test', 'marginalia'],
    ['search', 'python教程', '-e', 'bing', '-n', '3'],
    ['search', 'python教程', '-e', 'sogou', '-n', '3'],
    ['search', 'python教程', '-e', 'baidu', '-n', '3'],
    ['search', 'python教程', '-e', 'marginalia', '-n', '3'],
    ['search', 'rust', '-e', 'bing', '-n', '3', '-f', 'text'],
    ['search', 'rust', '-e', 'bing', '-n', '3', '-f', 'md'],
    ['rank'], ['rank', 'zhihu', '-n', '3'], ['rank', 'hn_official', '-n', '3'],
    ['rank', 'github_trend', '-n', '3'], ['rank', 'weibo', '-n', '3'],
    ['feed'], ['feed', 'sspai', '-n', '3'], ['feed', 'ithome', '-n', '3'],
    ['feed', 'ifanr', '-n', '3'], ['feed', 'github_blog', '-n', '3'],
    ['site', '--help'], ['site', 'github', 'webtool', '-n', '3'],
    ['site', 'hn', 'python', '-n', '3'], ['site', 'arxiv', 'llm', '-n', '3'],
    ['site', 'wikipedia', 'python', '-n', '3'], ['site', 'npm', 'react', '-n', '3'],
    ['site', 'sspai', 'mac', '-n', '3'], ['site', 'juejin', 'vue', '-n', '3'],
    ['site', 'bilibili', 'python', '-n', '3'], ['site', 'so', 'python', '-n', '3'],
    ['fetch', 'https://example.com', '-f', 'text'],
    ['fetch', 'https://example.com', '-f', 'json'],
    ['fetch', 'https://example.com', '-f', 'html', '--raw'],
    ['zen', '--list-models'], ['zen', '--list-free'],
    ['zen', 'say hi', '--model', 'big-pickle', '--show-body'],
    ['blocklist', 'show'], ['config', 'list'],
]

# 不稳定字段: 耗时/时间戳/缓存态
NOISE = re.compile(r'"(took_ms|degraded_from|reason|cached_at|ts|_ts)"\s*:\s*[^,}]+')


def norm(s):
    s = NOISE.sub(r'"\1": X', s)
    s = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d+', 'TS', s)
    s = re.sub(r'\(\d+ms\)', '(Xms)', s)
    return s


def run(argv):
    env = dict(os.environ, PYTHONHASHSEED='0')
    p = subprocess.run(['/usr/bin/webtool'] + argv, capture_output=True,
                       text=True, env=env, timeout=180)
    return {'rc': p.returncode, 'out': norm(p.stdout), 'err': norm(p.stderr)}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'save'
    path = '/tmp/baseline.json'
    if mode == 'save':
        data = {json.dumps(c): run(c) for c in CASES}
        json.dump(data, open(path, 'w'), ensure_ascii=False)
        print(f'saved {len(data)} cases -> {path}')
        return 0
    base = json.load(open(path))
    same = diff = err = 0
    for c in CASES:
        k = json.dumps(c)
        cur = run(c)
        b = base.get(k)
        if not b:
            continue
        if b['out'] == cur['out'] and b['rc'] == cur['rc']:
            same += 1
        else:
            diff += 1
            b_out, c_out = b['out'].splitlines(), cur['out'].splitlines()
            only_b = [l for l in b_out if l not in c_out][:2]
            only_c = [l for l in c_out if l not in b_out][:2]
            print(f'DIFF {" ".join(c)[:60]}')
            print(f'  rc {b["rc"]}->{cur["rc"]}  len {len(b_out)}->{len(c_out)}')
            for l in only_b:
                print(f'  - {l[:100]}')
            for l in only_c:
                print(f'  + {l[:100]}')
    print(f'\n{same} 一致 / {diff} 差异')
    return 0


if __name__ == '__main__':
    sys.exit(main())