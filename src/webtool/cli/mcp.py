"""webtool mcp: 通用 MCP 客户端命令 (list/probe/call)

调度层, 协议实现见 net/mcpclient.py。三种动作:

    webtool mcp list <url>                 # 列工具 (先探测再动手)
    webtool mcp probe <url>                # 端点通不通体检
    webtool mcp call <url> <tool> '<json>' # 调工具

刻意不绑死任何 MCP server: URL 与 key 都是参数/环境变量, 换服务只换端点。
输出统一 JSON 走 adminfmt.adapt, 与其他管理命令同一套 -f 约定。
"""
import json
import os
import sys
import time

from webtool.core import config_data as _cfg_data
from webtool.net import mcpclient as _mc


def _endpoints():
    """端点表: ~/.webtool/mcp.json 覆盖内置 (mtime 热生效)

    格式 {"exa": {"url": "...", "api_key_env": "EXA_API_KEY"}, ...}
    只登记常用端点省去每次敲长 URL; 任意 URL 仍可直接传。
    """
    return _cfg_data.load('mcp', 'mcp.json')


def _resolve(args, cfg):
    """URL + key 解析: 直接给 URL 就用; 给别名查表。

    key 一律经环境变量名映射出值, 配置文件里不存明文。
    """
    target = (args.target or '').strip()
    table = _endpoints()
    spec = table.get(target) or {}
    url = spec.get('url') or target
    env = spec.get('api_key_env') or args.key_env or ''
    key = spec.get('api_key') or (os.environ.get(env, '') if env else '')
    if not url.startswith(('http://', 'https://')):
        known = ', '.join(sorted(table)) or '(无)'
        print(f'error: 未知端点 {target!r}; 需要 http(s) URL 或已登记别名: {known}',
              file=sys.stderr)
        return None, None
    proxy = _proxy_for(spec, args, cfg)
    return url, {'api_key': key, 'tools_filter': args.tools or '',
                 'timeout': args.timeout, 'proxy': proxy}


def _proxy_for(spec, args, cfg):
    """代理策略: 命令行 --no-proxy > 路由表, 端点表不参与决策。

    - 缺省 `'auto'` 交给路由表按域名/IP/协议分流
    - 端点需要直连: 在规则表里写它域名的 `direct` 规则
      (`webtool proxy rule add '{"domain":["..."]}' direct`)

    `spec` 保留是为了接口不变 (自建端点表若留了 proxy 字段, 删掉即可, 不报错)。
    """
    if getattr(args, 'no_proxy', False):
        return 'direct'    # 必须写字符串 'direct': None 与 'auto' 同义 (都交规则表)
    return 'auto'      # 交给路由表按域名/IP/协议分流


def _emit(out, args, ok=True):
    """统一输出: JSON → adminfmt.adapt 转目标格式。

    失败时走 stderr 而非 stdout: cli.app._run 对 rc!=0 的管理命令会丢弃
    stdout 缓冲, 错误信息必须走 stderr 才不会被吞掉 (同 plugins check 失败
    无输出的既有问题, 这里不扩大影响面)。
    """
    from webtool.cli.adminfmt import adapt
    text = adapt(json.dumps(out, ensure_ascii=False, indent=2), args.format)
    print(text, file=sys.stdout if ok else sys.stderr)


def _coerce(val):
    """把 --arg 传进来的字符串按 JSON 字面量猜类型。

    真 JSON / 数字 / 布尔 / null 直接解; 其余当字符串 (含中文、空格、URL)。
    猜错的风险由调用方承担 —— 实在要传纯字符串字面量就用位置 JSON 通道。
    """
    s = val.strip()
    if not s:
        return val
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return val


def _build_args(raw_json, pairs):
    """参数组装: 位置 JSON 与 --arg 两条通道合并。

    两者可并存 (--arg 覆盖同名键), 都为空则传空 dict —— 不少工具无参可调。
    """
    out = {}
    if raw_json:
        try:
            out = json.loads(raw_json)
        except json.JSONDecodeError as e:
            print(f'error: 参数不是合法 JSON ({e.msg}); 例: \'{{"query":"x"}}\'',
                  file=sys.stderr)
            return None
        if not isinstance(out, dict):
            print('error: JSON 参数必须是对象, 例 \'{"query":"x"}\'', file=sys.stderr)
            return None
    for p in (pairs or ()):
        if '=' not in p:
            print(f'error: --arg 需要 k=v 形式, 收到 {p!r}', file=sys.stderr)
            return None
        k, _, v = p.partition('=')
        k = k.strip()
        if not k:
            print(f'error: --arg 的键不能为空: {p!r}', file=sys.stderr)
            return None
        out[k] = _coerce(v)
    return out


def do_mcp(args, cfg):
    """分发 probe / list / call"""
    if not args.target:
        print('用法: webtool mcp <list|probe|call> <url|别名> ...', file=sys.stderr)
        return 2

    url, kw = _resolve(args, cfg)
    if not url:
        return 2

    if args.action == 'probe':
        out = _mc.probe(url, **kw)
        out['url'] = url
    elif args.action == 'list':
        t0 = time.time()
        r = _mc.list_tools(url, **kw)
        if 'error' in r:
            out = {'url': url, 'error': r['error']}
        else:
            out = {'url': url, 'total': r['total'],
                   'took_ms': int((time.time() - t0) * 1000), 'tools': r['tools']}
    else:  # call
        if not args.tool:
            print('error: call 需要工具名', file=sys.stderr)
            return 2
        arguments = _build_args(args.arguments, getattr(args, 'params', None))
        if arguments is None:
            return 2
        t0 = time.time()
        r = _mc.call_tool(url, args.tool, arguments, **kw)
        if 'error' in r:
            out = {'url': url, 'tool': args.tool, 'error': r['error']}
        else:
            out = {'url': url, 'tool': args.tool, 'is_error': r['is_error'],
                   'took_ms': int((time.time() - t0) * 1000), 'text': r['text']}

    ok = not (out.get('error') or out.get('is_error'))
    _emit(out, args, ok)
    return 0 if ok else 1
