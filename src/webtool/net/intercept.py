"""拦截与绕过: 一层抽象, 插件化

transport 不该知道"验证码"是什么 —— 它只该问两句:

    这次响应是不是被挡住了? (谁挡的、凭什么、要不要冷却)
    有没有绕法? (换通道 / 换指纹 / 补请求头 / 等一会儿重来)

于是检测与绕过都做成 `Interceptor` 插件, 人机验证(captcha)只是第一个实现。
再加"WAF 页"、"限流 429"、"登录墙"都是写一个类的事, 不用去改 transport。

插件只从配置注册: `plugins.json` 的 `interceptor` 段 (包内 `data/plugins.json` 提供
默认, `~/.webtool/plugins.json` 覆盖/追加, 按 mtime 热加载, 见 core.plugins)。
代码里没有内置清单 —— 配置里删掉或停用, 插件就真的不跑。`register()` 只用于测试
与临时插件, 同名时配置优先。

域名与检测成本:

    class WechatPoc(Interceptor):
        name, priority = 'wechat_poc', 15
        hosts = ('mp.weixin.qq.com',)   # 只在这个域名上被调用
        cools_down = False              # 不记冷却 → 不参与 preflight/note_ok

框架先按 `hosts` 分发 (没有 hosts 的通用插件才每个请求都看), 再执行命中候选的
处理器。别把域名判定写进 `inspect` 里 —— 那样框架就拦不住"每个请求扫全部插件"。

写一个插件:

    from webtool.net.intercept import Interceptor, Hit, Bypass

    class MyWall(Interceptor):
        name, priority = 'mywall', 30

        def inspect(self, ctx):                 # ctx 见 Ctx
            if ctx.status == 403 and '请稍候' in ctx.text:
                return Hit('waf', sign='403+请稍候', why='WAF 拦截')
            return None

        def bypass(self, ctx, hit):             # 想动手才实现
            return Bypass(how='换新闻通道', url=ctx.url.replace('/s?', '/n?'))

只判不绕也是合法实现 (captcha 现在就是): 那 transport 按冷却 + 降级梯走。
"""
import abc
import dataclasses
import datetime
import json
import os
import threading


@dataclasses.dataclass
class Ctx:
    """一次响应的现场 —— 拦截器能看到的全部信息

    只读: 拦截器不许改这里面的东西 (要改请求就返回 Bypass, 由 transport 执行)。
    """
    engine: str = ''
    url: str = ''
    status: int = 0
    text: str = ''
    headers: dict = dataclasses.field(default_factory=dict)
    profile: str = ''
    attempt: int = 0
    via: str = ''                   # 实际走的通道 (transport 给的 via)
    _low: str = dataclasses.field(default='', repr=False, compare=False)

    def host(self):
        u = self.url
        return u.split('/')[2] if '://' in u else u

    @property
    def site(self):
        """站点键 (主机名, 去端口): 冷却/日志按它分桶, 与引擎名无关

        一概而论: 不管这次请求挂的是搜索引擎还是 fetch, 被拦就是同一个站被拦,
        冷却记账不该因为走哪条代码路径而分裂。
        """
        h = self.host().split('@')[-1].lower()
        if h.startswith('['):
            return h.split(']')[0] + ']'
        return h.rsplit(':', 1)[0] if ':' in h else h

    def lower(self):
        """小写正文 (只算一次): 每个请求几 MB 的正文, 各插件各自 lower 一遍太亏"""
        if not self._low:
            self._low = (self.text or '').lower()
        return self._low


@dataclasses.dataclass
class Hit:
    """一次拦截命中"""
    kind: str                       # captcha / waf / ratelimit / login ...
    by: str = ''                    # 哪个插件判的 (inspect 里不用填, 注册表会盖章)
    sign: str = ''                  # 判定依据 (正文/状态里命中的特征, 进日志)
    why: str = '拦截'               # 人话, 用于报错: "xxx 验证页拦截(百度)"
    left: int = 0                   # 冷却剩余秒数 (preflight 用)


@dataclasses.dataclass
class Bypass:
    """绕过方案: 下一次重试怎么改请求

    没有绕过手段就返回 None —— 不要让调用方去猜"到底有没有"。
    """
    how: str = ''                   # 人话说明, 进日志
    url: str = ''                   # 换目标地址
    headers: dict = dataclasses.field(default_factory=dict)   # 加/改请求头
    profile: str = ''               # 换浏览器指纹
    delay: float = 0.0              # 重试前先等 (0 = 用默认退避)
    retry: bool = True              # False = 只记录不发生重试


class Interceptor(abc.ABC):
    """拦截绕过插件接口

    priority 小的先跑: 判得准的排前面, 兜底的排后面。
    优先级以 `plugins.json` 的 `interceptor` 段为准 (内置清单里写 10, 用户改了
    就听用户的); 类属性只是代码注册 (`register()`) 时的默认值。

    `hosts` 让框架先按域名分发: 声明了域名就只在这些域名上被调用, 空 = 通用
    (每个请求都看)。这不是性能微调, 是语义 —— 微信插件不该去判百度页。
    `cools_down` 表示插件自己记冷却; 只有这类插件才需要 preflight/note_ok。
    """
    name = ''
    priority = 50
    hosts = ()                      # 生效域名 (小写, 空 = 不限)
    cools_down = False              # 会累计冷却/计数 → 参与 preflight 与 note_ok

    @abc.abstractmethod
    def inspect(self, ctx):
        """这次响应被挡了吗? → Hit 或 None (抽象方法, 必须实现)"""

    def preflight(self, ctx):
        """动手之前问一句: 这个通道现在能不能用? → Hit 表示"先别发"

        对应"冷却中"。默认不管 —— 只有会累计封禁的拦截器 (验证码/限流) 才需要。
        """
        return None

    def bypass(self, ctx, hit):
        """有绕法吗? → Bypass 或 None (默认没有, 走冷却 + 降级梯)"""
        return None

    def note_ok(self, ctx):
        """这次没被拦 —— 复位计数 (连续失败才有意义的状态放这)"""

    def note_hit(self, ctx, hit):
        """确认被拦 —— 记冷却/记数 (captcha 在这里封冷却)

        记完把"还要等多久"写回 hit.left: 报错信息要用它, 而报错不该反过来
        认识具体插件 (transport 不认识 captcha)。
        """


_LOCK = threading.Lock()
_INST = {}                      # 类对象 → 实例 (插件热重载换了类, 自然换新实例)
_ERR = {}                       # 插件名 → 加载/运行错误 (让 describe 看得见)
_MISSING = {}                   # 配置有、代码缺的插件 (静默跳过, 不报错)
_CODE = {}                      # 代码内注册 (测试/临时插件): name → 类
_EXT = {}                       # 外部插件实例: name → ExternalInterceptor


def register(plugin):
    """注册一个拦截器 (可直接当装饰器用)

    正式插件走配置 (`plugins.json` 的 `interceptor` 段), 这里只留给测试、临时
    插件与需要动态构造的场景; 同名时配置优先。
    """
    if not (isinstance(plugin, type) and issubclass(plugin, Interceptor)):
        raise TypeError('拦截器要是 Interceptor 的子类, 收到 %r' % (plugin,))
    if not plugin.name:
        raise ValueError('拦截器必须给 name (配置里要靠它覆盖/停用)')
    _CODE[plugin.name] = plugin
    return plugin


def _mk(cls, name=None):
    key = (cls, name)               # 同一个类配成多个插件时各用各的实例
    inst = _INST.get(key)
    if inst is None:
        inst = _INST[key] = cls()
    return inst


def _is_external(spec):
    """声明里写了 type=external 的走外部进程适配器 (不需要 Python 代码)"""
    p = spec.get('params') or {}
    t = spec.get('type') or p.get('type') or ''
    return str(t).lower() in ('external', 'process', 'stdio')


def _from_config():
    """配置里的拦截器 —— 读不到就当没有, 不能因为配置坏了就整条链路瘫掉

    返回 name -> None (显式停用) / {'cls': 类, ...} / {'ext': 声明, ...}。
    优先级单独带出来: 它写在配置里, 而类属性是代码里的默认值。
    """
    try:
        from webtool.core import plugins
        # enabled_only=False: 默认过滤会把"显式停用"这件事吃掉, 我们就没法照办
        specs = plugins.table('interceptor', enabled_only=False)
    except Exception as e:                    # noqa: BLE001 配置/插件文件坏了
        _ERR['<配置>'] = str(e)[:120]
        return {}
    _MISSING.clear()
    out = {}
    for name, spec in (specs or {}).items():
        if spec.get('enabled') is False:
            out[name] = None                  # 显式停用
            continue
        fn = spec.get('fn')
        if getattr(fn, 'missing', False):
            _MISSING[name] = getattr(fn, 'reason', '')
            _ERR.pop(name, None)              # 缺失不是错误, 别混进运行期报错
        elif isinstance(fn, type) and issubclass(fn, Interceptor):
            out[name] = {'cls': fn, 'spec': spec, 'priority': spec.get('priority')}
        elif _is_external(spec):
            if not (spec.get('command') or (spec.get('params') or {}).get('command')):
                _MISSING[name] = '未配置 command'
            else:
                out[name] = {'ext': spec, 'priority': spec.get('priority')}
        elif fn is not None:
            _ERR[name] = '不是 Interceptor 的子类: %r' % (fn,)
    return out


def interceptors():
    """当前生效的拦截器 (按 priority 升序)

    来源 = 配置 (`plugins.json` 的 interceptor 段) + 代码内 register();
    同名以配置为准, 配置里 `enabled: false` 的剔除。
    """
    with _LOCK:
        entries = {}
        for name, cls in _CODE.items():
            entries[name] = ('cls', cls, None, None)
        for name, spec in _from_config().items():
            if spec is None:
                entries.pop(name, None)
                _ERR.pop(name, None)
                continue
            if 'cls' in spec:
                entries[name] = ('cls', spec['cls'], spec.get('priority'), spec.get('spec'))
            else:
                entries[name] = ('ext', spec['ext'], spec.get('priority'), spec['ext'])
            _MISSING.pop(name, None)
        ok = []
        for name, (kind, payload, prio, spec) in entries.items():
            try:
                if kind == 'cls':
                    inst = _mk(payload, name)
                    if spec is not None and hasattr(inst, 'configure'):
                        inst.configure(name, spec)
                else:
                    inst = _EXT.get(name)
                    if inst is None:
                        from webtool.net.extproc import ExternalInterceptor
                        inst = _EXT[name] = ExternalInterceptor()
                    inst.configure(name, payload)
            except Exception as e:            # noqa: BLE001 插件构造/配置失败
                _ERR[name] = '实例化失败: %s' % str(e)[:100]
                _EXT.pop(name, None)
                continue
            if isinstance(prio, int) and prio != getattr(inst, 'priority', None):
                inst.priority = prio          # 配置里的优先级盖过类属性
            ok.append(inst)
        for name in list(_EXT):
            if name not in entries:           # 配置删了/停用了 → 关掉子进程
                _EXT.pop(name).close()
        ok.sort(key=lambda p: (getattr(p, 'priority', 50), getattr(p, 'name', '')))
        return ok


def _run(plugin, method, *a):
    """调插件方法: 插件炸了只能让它自己掉队, 不能拖垮整条请求链路"""
    fn = getattr(plugin, method, None)
    if fn is None:
        return None
    name = getattr(plugin, 'name', '?')
    try:
        r = fn(*a)
    except Exception as e:                    # noqa: BLE001
        _ERR[name] = '%s() 出错: %s' % (method, str(e)[:100])
        return None
    _ERR.pop(name, None)                      # 恢复正常就别留着旧报错
    return r


def _host_of(url):
    """→ 小写主机名 (去端口; 无 scheme 时按原串)"""
    u = (url or '').strip()
    if '://' in u:
        u = u.split('/')[2]
    u = u.split('/')[0].lower()
    if u.startswith('['):
        return u.split(']')[0] + ']'
    return u.rsplit(':', 1)[0] if ':' in u else u


def _candidates(ctx):
    """按域名分发: 声明 hosts 的插件只在自己域名上被调用, 通用插件每次都看

    这一层只做字符串判等 —— 处理器到下一层才执行。新插件想收窄成本就声明
    `hosts`, 不要 `inspect` 里自己判域名 (那样框架就拦不住"每次跑全部插件")。
    """
    host = _host_of(ctx.url)
    out = []
    for p in interceptors():
        hs = getattr(p, 'hosts', ())
        if not hs or host in hs:
            out.append(p)
    return out


def _overrides(plugin, method):
    """插件自己实现了这个方法? (基类空实现不算)"""
    return getattr(type(plugin), method, None) is not getattr(Interceptor, method, None)


def preflight(ctx):
    """发请求之前问: 现在能发吗? → Hit 表示"先别发" (第一条命中的说了算)

    只问会记冷却的插件 (cools_down) 或自己实现了 preflight 的插件 —— 不记
    状态的插件没有"现在能不能发"这回事, 不必每请求都跑。
    """
    for p in _candidates(ctx):
        if not (getattr(p, 'cools_down', False) or _overrides(p, 'preflight')):
            continue
        h = _run(p, 'preflight', ctx)
        if h is not None:
            h.by = h.by or getattr(p, 'name', '')
            return h
    return None


def cooldown_of(engine, url=''):
    """这个引擎的通道现在被谁挡着? → Hit (带 left) 或 None

    给"冷却 N s, 请换引擎"这类文案用 —— 引擎侧要报剩余秒数, 但不该反过来
    认识具体插件 (谁封的、封多久由插件说了算)。
    """
    return preflight(Ctx(engine=engine, url=url))


def gate(engine, text, **kw):
    """引擎内部挨个试通道时的统一入口: 判定 + 记账一次做完 → (Hit|None, Ctx)

    这些路径没有 transport 的响应对象 (引擎自己造会话、自己读正文), 但同样
    该让所有拦截器过一遍 —— 否则新加的插件对这条路径莫名不生效。判定为"被挡"
    时顺手 note_hit 记账 (冷却/计数), 没挡则 note_ok 复位。
    """
    ctx = Ctx(engine=engine, text=text or '', **kw)
    hit = inspect(ctx)
    if hit is None:
        note_ok(ctx)
    else:
        note_hit(ctx, hit)
    return hit, ctx


def blocked_by(engine, text, **kw):
    """引擎自己探通道时的便捷入口 (只有正文可给): 返回 Hit 或 None

    专给"引擎内部挨个试通道"的场景用 (如 sogou 的 PC/移动双通道): 那边没有
    transport 的响应对象, 但同样该让所有拦截器过一遍 —— 否则新加的插件管不到
    这条路径, 表现为"新插件对某些引擎莫名不生效"。
    """
    return inspect(Ctx(engine=engine, text=text or '', **kw))


def inspect(ctx):
    """响应回来了, 是不是被挡了? → Hit 或 None (第一条命中的说了算)

    顺序有意义: priority 小的先判。判得准的插件该排前面, 兜底的排后面,
    否则宽规则会先吃掉窄规则的判定。只有域名匹配的候选会进处理器。
    """
    cands = _candidates(ctx)
    if not cands:
        return None
    for p in cands:
        h = _run(p, 'inspect', ctx)
        if h is not None:
            h.by = h.by or getattr(p, 'name', '')
            return h
    return None


def bypass(ctx, hit):
    """问绕法: 先问判定的那个, 再按序问同域名的其它插件 (兜底策略)"""
    if hit is None:
        return None
    hit_by = hit.by
    order = _candidates(ctx)
    order.sort(key=lambda p: 0 if getattr(p, 'name', '') == hit_by else 1)
    for p in order:
        bp = _run(p, 'bypass', ctx, hit)
        if bp is not None:
            bp.how = bp.how or getattr(p, 'name', '')
            return bp
    return None


def note_ok(ctx):
    """通过了: 只让会记账的插件复位 (否则每个成功请求都写一遍 state.json)"""
    for p in _candidates(ctx):
        if getattr(p, 'cools_down', False) or _overrides(p, 'note_ok'):
            _run(p, 'note_ok', ctx)


def note_hit(ctx, hit):
    """确认命中: 只通知判定的那个 (别让不相关的插件跟着记黑账)"""
    if hit is None:
        return
    for p in _candidates(ctx):
        if getattr(p, 'name', '') == hit.by:
            _run(p, 'note_hit', ctx, hit)


def describe():
    """诊断用: 当前有哪些拦截器、谁坏了"""
    out = []
    for p in interceptors():
        out.append({'name': getattr(p, 'name', '?'),
                    'priority': getattr(p, 'priority', 50),
                    'module': type(p).__module__,
                    'error': _ERR.get(getattr(p, 'name', ''), '')})
    return out


def problems():
    """有问题的拦截器 (加载/运行报错的), 给 config list 之类的地方显示"""
    return dict(_ERR)


def close_external():
    """关掉所有外部插件进程 (plugins reload / 退出前调用)"""
    with _LOCK:
        for inst in list(_EXT.values()):
            try:
                inst.close()
            except Exception:                 # noqa: BLE001
                pass
        _EXT.clear()


def missing():
    """配置里声明了、但代码里找不到的拦截器 (name → 原因); 静默跳过, 不报错"""
    _from_config()                     # 现扫一遍, 别等人先调 interceptors()
    return dict(_MISSING)


# ── 拦截日志 ─────────────────────────────────────────────────────────────
# 只记"判定过"的事件 (被拦/绕行/绕后成功/绕后仍败), 不记正常请求 —— 否则日志
# 被每条成功请求淹没, 真正要看的那几行反而找不到。
_LOG_LOCK = threading.Lock()
_LOG_MAX = 2 * 1024 * 1024          # 单文件上限, 超了轮转成 .1 (只留一份)


def log_path():
    """拦截日志位置: 跟 WEBTOOL_DIR 走, 与 state/config 同源"""
    base = os.environ.get('WEBTOOL_DIR') or '~/.webtool'
    return os.path.join(os.path.expanduser(base), 'intercept.log')


def log(ctx, hit=None, action='blocked', detail=''):
    """追加一条拦截记录 (JSONL)。日志失败不许影响请求。"""
    rec = {
        'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'action': action,
        'site': ctx.site,
        'url': (ctx.url or '')[:300],
        'status': ctx.status,
        'via': ctx.via,
    }
    if hit is not None:
        rec.update({'kind': hit.kind, 'sign': hit.sign, 'why': hit.why,
                    'by': hit.by})
        if hit.left:
            rec['left'] = hit.left
    if detail:
        rec['detail'] = str(detail)[:300]
    try:
        line = json.dumps(rec, ensure_ascii=False) + '\n'
        p = log_path()
        with _LOG_LOCK:
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)
            try:
                if os.path.getsize(p) > _LOG_MAX:
                    os.replace(p, p + '.1')
            except OSError:
                pass
            with open(p, 'a', encoding='utf-8') as f:
                f.write(line)
    except Exception:                      # noqa: BLE001
        pass


def reset():
    """清缓存 (测试与 plugins reload 用)"""
    with _LOCK:
        _INST.clear()
        _ERR.clear()
