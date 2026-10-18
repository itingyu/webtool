"""CLI 帮助文案小工具 (把多列文本原样喂给 click)"""


def verbatim(text: str) -> str:
    r"""给每个段落加一个 \b 前缀行, 让 click 原样输出, 不按宽度重排折行。

    尾注里的多列清单 (子命令目录, 示例对齐) 一旦被 click 当普通段落重排就散了;
    click 的约定是"段落首行是 \b 就原样输出"。这里按空行切段, 逐段加。
    """
    paras = [p for p in text.strip('\n').split('\n\n') if p.strip()]
    return '\n\n'.join('\b\n' + p for p in paras)
