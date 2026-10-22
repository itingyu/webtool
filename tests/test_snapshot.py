"""snapshot 存储 + diff 计算 + 渲染 的本地测试 (不联网)

跑法: python3 tests/test_snapshot.py
(脚本式, 与 test_events.py 同一约定; pytest 收集不到, 直接当脚本执行)

做法: 把 WEBTOOL_DIR 指到临时目录, 快照全写在那儿 —— 不碰用户真实快照。
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'src'))

fails = []


def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix='webtool-snap-')
    os.environ['WEBTOOL_DIR'] = tmp
    try:
        from webtool.dao import snapshot as store
        from webtool.core import difftxt
        from webtool.render.diffrender import render_diff

        # ── 名字生成 ────────────────────────────────────────────
        check(store.slugify('https://www.example.com/a/b') == 'example.com-a-b',
              'slug 去 www 与协议, 路径变连字符')
        check(store.slugify('https://example.com/') == 'example.com',
              '根路径不产生尾连字符')
        check(store.slugify('https://ex.com/%E4%B8%AD%E6%96%87') == 'ex.com-中文',
              '百分号编码还原成中文')
        check(store.slugify('https://example.com/?q=1') == 'example.com',
              '查询串不进名字')
        same = store.slugify('https://example.com/a/b')
        check(store.slugify('https://example.com/a/b') == same,
              '同一 URL 名字稳定')
        check(len(store.slugify('https://e.com/' + 'x' * 300)) <= 80,
              '超长名字被截断到 80')

        # ── 存 / 读 / 版本 ──────────────────────────────────────
        r1 = store.save('https://example.com/p', 'one\ntwo\nthree')
        check(r1['changed'] and r1['version'] == 1, '首次存档 = v1 且有变化')
        r2 = store.save('https://example.com/p', 'one\ntwo\nthree')
        check((not r2['changed']) and r2['version'] == 1,
              '内容相同不追加版本')
        r3 = store.save('https://example.com/p', 'one\nTWO\nthree\nfour')
        check(r3['changed'] and r3['version'] == 2, '内容变化 → v2')

        rows = store.versions('example.com-p')
        check(len(rows) == 2 and rows[-1]['n'] == 2, '版本列表有 2 版')
        s = store.load('example.com-p')
        check(s and 'four' in s['content'], 'load 默认取最新版')
        s1 = store.load('example.com-p', 0)
        check(s1 and 'two' in s1['content'], 'load 能取指定版本')
        check(store.load('example.com-p', -2)['content'].startswith('one'),
              '负索引从末尾数')
        check(store.load('nope') is None, '不存在的名字返回 None')
        check(store.exists('example.com-p'), 'exists 认得已存的名字')
        check(not store.exists('nope'), 'exists 对未存的返回 False')

        ls = store.listing()
        check(len(ls) == 1 and ls[0]['versions'] == 2, 'listing 汇总版数')
        check(store.remove('example.com-p') is True, '删除成功')
        check(store.remove('example.com-p') is False, '重复删除返回 False')

        # ── 版本上限 ────────────────────────────────────────────
        for i in range(store.KEEP + 5):
            store.save('https://example.com/rot', 'v%d' % i)
        check(len(store.versions('example.com-rot')) == store.KEEP,
              '历史版本只留最近 KEEP 版')
        store.remove('example.com-rot')

        # ── diff 计算 ───────────────────────────────────────────
        c = difftxt.compare('a\nb\nc', 'a\nB\nc')
        check(c['stats']['added'] == 1 and c['stats']['removed'] == 1,
              '替换计 1 增 1 删')
        check(len(c['hunks']) == 1, '相邻改动合成一个 hunk')
        check(difftxt.compare('a\nb', 'a\nb')['hunks'] == [], '相同文本无 hunk')
        check(difftxt.compare('a', 'a\nb')['stats']['added'] == 1, '纯新增')
        check(difftxt.compare('a\nb', 'a')['stats']['removed'] == 1, '纯删除')

        # 末尾空行不算差异
        check(difftxt.compare('a\nb\n', 'a\nb')['hunks'] == [],
              '末尾空行不产生差异')
        # CRLF 归一
        check(difftxt.compare('a\r\nb', 'a\nb')['hunks'] == [],
              'CRLF 与 LF 视为相同')
        # ignore_ws
        check(difftxt.compare('a  b', 'a b')['hunks'] != [],
              '默认空白差异算变化')
        check(difftxt.compare('a  b', 'a b', ignore_ws=True)['hunks'] == [],
              'ignore_ws 折叠空白后相同')
        # 大小写不当空白
        check(difftxt.compare('a', 'A', ignore_ws=True)['hunks'] != [],
              'ignore_ws 不忽略大小写')

        # 整页改版 → 相似度低
        big_old = '\n'.join('line %d' % i for i in range(50))
        big_new = '\n'.join('other %d' % i for i in range(50))
        ratio = difftxt.compare(big_old, big_new)['stats']['similarity']
        check(ratio < 0.3, '整页重写相似度低 (%.2f)' % ratio)
        check(difftxt.compare(big_old, big_old)['stats']['similarity'] == 1.0,
              '完全相同相似度 1.0')

        # hunk 行数字段
        h = c['hunks'][0]
        check(h['old_len'] == 3 and h['new_len'] == 3, 'hunk 带 old_len/new_len')
        check(h['old_start'] == 1 and h['new_start'] == 1, 'hunk 起始行 1-based')

        # 上下文行数
        wide = difftxt.compare('\n'.join('l%d' % i for i in range(30)),
                               '\n'.join(['l%d' % i for i in range(15)] +
                                         ['X'] +
                                         ['l%d' % i for i in range(16, 30)]),
                               context=1)
        ctx = [ln for ln in wide['hunks'][0]['lines'] if ln[0] == ' ']
        check(len(ctx) <= 2, 'context=1 只带 1 行上下文 (%d)' % len(ctx))

        # ── 渲染 ────────────────────────────────────────────────
        txt = render_diff(c, 'text', 'old', 'new')
        check('@@ -1,3 +1,3 @@' in txt, 'text 用标准 hunk 头')
        check('+ B' in txt and '- b' in txt, 'text 保留 +/- 标记')
        md = render_diff(c, 'markdown', 'old', 'new')
        check('```diff' in md, 'markdown 用 diff 代码块')
        js = json.loads(render_diff(c, 'json', 'old', 'new'))
        check(js['stats']['added'] == 1 and js['old'] == 'old',
              'json 带 stats 与两侧名字')
        empty = render_diff(difftxt.compare('a', 'a'), 'text')
        check('无差异' in empty, '无差异时明说')

        # 截断
        many = difftxt.compare('a', '\n'.join('n%d' % i for i in range(600)))
        cut = render_diff(many, 'text', max_lines=10)
        check('截断' in cut, '超行数上限时提示截断')
        full = json.loads(render_diff(many, 'json'))
        check(len(full['hunks'][0]['lines']) > 100, 'json 不受 max_lines 限制')

        # ── 落盘位置 ────────────────────────────────────────────
        check(store.base_dir().startswith(tmp), '快照落在 WEBTOOL_DIR 下')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        os.environ.pop('WEBTOOL_DIR', None)

    print('\n%d 项失败' % len(fails) if fails else '\nALL PASS')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
