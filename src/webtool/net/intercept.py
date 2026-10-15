"""拦截与绕过: 一层抽象, 插件化

transport 不该知道"验证码"是什么 —— 它只该问两句:

    这次响应是不是被挡住了? (谁挡的、凭什么、要不要冷却)
    有没有绕法? (换通道 / 换指纹 / 补请求头 / 等一会儿重来)

于是检测与绕过都做成 `Interceptor` 插件, 人机验证(captcha)只是第一个实现。
再加"WAF 页"、"限流 429"、"登录墙"都是写一个类的事, 不用去改 transport。

插件两处来源, 同名以配置为准:
  1. 内置 (本模块 `_BUILTIN`): 保底, 用户配置里没有也能用
  2. 配置 `~/.webtool/plugins.json` 的 `interceptor` 段 (热加载, 见 core.plugins)

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

    def host(self):
        u = self.url
        return u.split('/')[2] if '://' in u else u


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
    """
    name = ''
    priority = 50

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


_BUILTIN_SPEC = (
    'webtool.net.captcha:CaptchaInterceptor',
)

_LOCK = threading.Lock()
_INST = {}                      # 类对象 → 实例 (插件热重载换了类, 自然换新实例)
_ERR = {}                       # 插件名 → 加载/运行错误 (让 describe 看得见)
_BUILTIN = {}                   # 内置插件: name → 类 (register 往里塞)
_LOADED = []                    # 内置清单是否已经拉过 (只拉一次)


def register(plugin):
    """注册一个拦截器 (可直接当装饰器用)"""
    if not (isinstance(plugin, type) and issubclass(plugin, Interceptor)):
        raise TypeError('拦截器要是 Interceptor 的子类, 收到 %r' % (plugin,))
    if not plugin.name:
        raise ValueError('拦截器必须给 name (配置里要靠它覆盖/停用)')
    _BUILTIN[plugin.name] = plugin
    return plugin


def _mk(cls):
    inst = _INST.get(cls)
    if inst is None:
        inst = _INST[cls] = cls()
    return inst


def _from_config():
    """配置里的拦截器 —— 读不到就当没有, 不能因为配置坏了就整条链路瘫掉

    返回 name -> None (显式停用) 或 {'cls': 类, 'priority': 优先级或 None}。
    优先级单独带出来: 它写在配置里, 而类属性是代码里的默认值。
    """
    try:
        from webtool.core import plugins
        # enabled_only=False: 默认过滤会把"显式停用"这件事吃掉, 我们就没法照办
        specs = plugins.table('interceptor', enabled_only=False)
    except Exception as e:                    # noqa: BLE001 配置/插件文件坏了
        _ERR['<配置>'] = str(e)[:120]
        return {}
    out = {}
    for name, spec in (specs or {}).items():
        if spec.get('enabled') is False:
            out[name] = None                  # 显式停用
            continue
        fn = spec.get('fn')
        if isinstance(fn, type) and issubclass(fn, Interceptor):
            out[name] = {'cls': fn, 'priority': spec.get('priority')}
        elif fn is not None:
            _ERR[name] = '不是 Interceptor 的子类: %r' % (fn,)
    return out


def _builtins():
    """拉一次内置插件 (延迟导入: 免得 intercept 一被 import 就拖起半条 net 栈)"""
    if not _LOADED:
        _LOADED.append(1)
        for path in _BUILTIN_SPEC:
            mod, _, attr = path.partition(':')
            try:
                import importlib
                cls = getattr(importlib.import_module(mod), attr)
                register(cls)
            except Exception as e:            # noqa: BLE001
                _ERR[attr or path] = '内置插件拉不起来: %s' % str(e)[:100]
    return dict(_BUILTIN)


def interceptors():
    """当前生效的拦截器 (按 priority 升序); 配置覆盖内置, 显式停用的剔除"""
    with _LOCK:
        table = _builtins()               # name -> 类
        prio = {}
        for name, spec in _from_config().items():
            if spec is None:
                table.pop(name, None)
                _ERR.pop(name, None)
            else:
                table[name] = spec['cls']
                prio[name] = spec.get('priority')
        ok = []
        for name, cls in table.items():
            try:
                inst = _mk(cls)
            except Exception as e:            # noqa: BLE001 插件构造失败
                _ERR[name] = '实例化失败: %s' % str(e)[:100]
                continue
            p = prio.get(name)
            if isinstance(p, int) and p != getattr(inst, 'priority', None):
                inst.priority = p             # 配置里的优先级盖过类属性
            ok.append(inst)
        ok.sort(key=lambda p: (getattr(p, 'priority', 50), getattr(p, 'name', '')))
        return ok


def _run(plugin, method, *a):
    """调插件方法: 插件炸了只能让它自己掉队, 不能拖垮整条请求链路"""
    fn = getattr(plugin, method, None)
    if fn is None:
        return None
    try:
        return fn(*a)
    except Exception as e:                    # noqa: BLE001
        _ERR[getattr(plugin, 'name', '?')] = '%s() 出错: %s' % (method, str(e)[:100])
        return None


def preflight(ctx):
    """发请求之前问: 现在能发吗? → Hit 表示"先别发" (第一条命中的说了算)"""
    for p in interceptors():
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
    否则宽规则会先吃掉窄规则的判定。
    """
    for p in interceptors():
        h = _run(p, 'inspect', ctx)
        if h is not None:
            h.by = h.by or getattr(p, 'name', '')
            return h
    return None


def bypass(ctx, hit):
    """问绕法: 先问判定的那个, 再按序问其它 (兜底策略), 第一个给出方案的赢"""
    if hit is None:
        return None
    hit_by = hit.by
    order = interceptors()
    order.sort(key=lambda p: 0 if getattr(p, 'name', '') == hit_by else 1)
    for p in order:
        bp = _run(p, 'bypass', ctx, hit)
        if bp is not None:
            bp.how = bp.how or getattr(p, 'name', '')
            return bp
    return None


def note_ok(ctx):
    for p in interceptors():
        _run(p, 'note_ok', ctx)


def note_hit(ctx, hit):
    """确认命中: 只通知判定的那个 (别让不相关的插件跟着记黑账)"""
    if hit is None:
        return
    for p in interceptors():
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


def reset():
    """清缓存 (测试与 plugins reload 用)"""
    with _LOCK:
        _INST.clear()
        _ERR.clear()
