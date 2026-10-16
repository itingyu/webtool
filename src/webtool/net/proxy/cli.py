"""proxy 子命令分发: webtool proxy <子命令> → 各 handler"""
import sys

from webtool.net.proxy.auth import _delpass, _passwd, _setpass
from webtool.net.proxy.geo import _asn, _geoip, _geosite
from webtool.net.proxy.pool import _get, _named, _noproxy, _set, _test, _unset
from webtool.net.proxy.rules_cli import _ruleadd, _ruledel, _rules, _tidy


def handle(args, cfg):
    """webtool proxy <子命令>"""
    action = args.action
    # `proxy rule add <JSON> <动作>` 是三层, 这里拆成 _ruleadd/_ruledel
    if action == 'rule':
        sub = getattr(args, 'value', None)
        if sub == 'del':
            return _ruledel(args, cfg)
        if sub == 'add':
            return _ruleadd(args, cfg)
        print('用法: webtool proxy rule add \'<match JSON>\' <动作> | '
              'webtool proxy rule del <序号>', file=sys.stderr)
        return 2
    fn = _ACTIONS.get(action)
    if fn is None:
        print('usage: webtool proxy ' + '|'.join(sorted(_ACTIONS)),
              file=sys.stderr)
        return 2
    if action in ('setpass', 'delpass'):
        # 这两个子命令的位置参数顺序是 `<用户名> [<密码>]`, 落到 value/user 上;
        # 而 _setpass/_delpass 按 user=用户名 / value=密码 取。这里对齐, 否则
        # `proxy setpass bob` 会被当成没给用户名, 直接打 usage。
        args.value, args.user = args.user, args.value
    return fn(args, cfg)


_ACTIONS = {
    'get': _get,
    'set': _set,
    'unset': _unset,
    'test': _test,
    'setpass': _setpass,
    'delpass': _delpass,
    'named': _named,
    'passwd': _passwd,
    'rules': _rules,
    'tidy': _tidy,
    'rule': _ruleadd,       # rule add (deld 走 app 层分发)
    'ruledel': _ruledel,
    'geoip': _geoip,
    'geosite': _geosite,
    'asn': _asn,
    'noproxy': _noproxy,
}
