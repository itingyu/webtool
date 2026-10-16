# -*- coding: utf-8 -*-
"""K 线渲染单测 (纯本地, 不联网)

覆盖三件容易悄悄坏掉的事:
1. 各源 K 线形状不一 (腾讯给你 list, 东财给 dict) —— 归一必须两者都吃
2. 生成的 SVG 必须能被 XML 解析器读通 (手写字符串最容易漏闭合)
3. 均线在样本不足时不能算 (算出来是假值, 比不画更糟)

跑法: python3 tests/test_kline.py
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from webtool.render.kline_svg import (normalize_rows, render_kline_svg,
                                      write_kline_svg)

fails = []


def check(cond, msg, detail=''):
    if cond:
        print(f'PASS {msg}')
    else:
        print(f'FAIL {msg} {detail}')
        fails.append(msg)


TENCENT = [['2026-10-13', '1287.00', '1274.89', '1288.48', '1268.11', '26573'],
           ['2026-10-14', '1270.10', '1286.00', '1286.75', '1266.00', '23773'],
           ['2026-10-15', '1286.00', '1302.00', '1317.76', '1282.00', '37870']]
EM = [{'date': '2026-10-14', 'open': 1270.1, 'close': 1286.0, 'high': 1286.75,
       'low': 1266.0, 'volume': 23773},
      {'date': '2026-10-15', 'open': 1286.0, 'close': 1302.0, 'high': 1317.76,
       'low': 1282.0, 'volume': 37870}]

rows_t = normalize_rows(TENCENT)
rows_e = normalize_rows(EM)
check(len(rows_t) == 3 and rows_t[-1]['close'] == 1302.0, '腾讯 list 形状可归一')
check(len(rows_e) == 2 and rows_e[0]['open'] == 1270.1, '东财 dict 形状可归一')

bad = normalize_rows([['2026-10-15', '1', 'x', '2', '0.5', '3'], None, 'junk'])
check(len(bad) == 0, '脏行被丢掉而不是崩掉', f'got {bad}')

swapped = normalize_rows([['2026-10-15', '1', '2', '0.5', '3', '9']])
check(swapped[0]['high'] == 3 and swapped[0]['low'] == 0.5, '高低颠倒时自愈')

# 样本不足: MA 一律不画 (画出来是假值, 比缺更糟)
svg_short = render_kline_svg(rows_t, title='贵州茅台 600519', ma=(5, 20))
check('MA5' not in svg_short and 'MA20' not in svg_short
      and 'polyline' not in svg_short, '样本不足时均线全缺')

# 样本够: 两条均线都要出
long_rows = rows_t + [dict(r, date=f'2026-09-{i:02d}') for i, r in
                      enumerate(rows_t * 8, start=1)]
svg_ma = render_kline_svg(long_rows, title='贵州茅台 600519', ma=(5, 10))
check('MA5' in svg_ma and 'MA10' in svg_ma
      and svg_ma.count('<polyline') == 2, '样本够时均线齐全')

svg_full = svg_ma
try:
    ET.fromstring(svg_full)
    ok_xml = True
except ET.ParseError as e:
    ok_xml = False
    print('  XML 错误:', e)
check(ok_xml, 'SVG 可被 XML 解析 (闭合完整)')
check(svg_full.count('<rect') >= 40
      and 'polyline' in svg_full and '<title>' in svg_full, '含蜡烛/均线/量能')
check('nan' not in svg_full.lower() and 'inf' not in svg_full.lower(), '无 nan/inf 泄漏')

empty = render_kline_svg([], title='空')
check('无数据' in empty and '<svg' in empty, '空数据给出可读占位')
try:
    ET.fromstring(empty)
    check(True, '空数据 SVG 也是合法 XML')
except ET.ParseError:
    check(False, '空数据 SVG 也是合法 XML')

# 中文/特殊字符不得破坏 XML
esc = render_kline_svg(rows_t, title='万科A & <测试>')
try:
    ET.fromstring(esc)
    check(True, '标题里的 & < > 被转义')
except ET.ParseError:
    check(False, '标题里的 & < > 被转义')

out = '/tmp/_kline_test.svg'
write_kline_svg(out, rows_t, title='落盘')
check(os.path.getsize(out) > 200, '落盘可写')
os.path.exists(out) and os.remove(out)

print('\n' + ('ALL PASS' if not fails else f'FAILED: {fails}'))
sys.exit(1 if fails else 0)
