"""终端渲染: 图片 / 字符大字 / 视频 / 音乐 —— 同一族, 合成一个入口"""
import typer

from webtool.cli.app import app
from webtool.cli.commands.banner import banner_cmd
from webtool.cli.commands.media import music_cmd, video_cmd
from webtool.cli.commands.pic import pic_cmd

render_app = typer.Typer(
    add_completion=False, no_args_is_help=True, rich_markup_mode=None,
    help='终端渲染: render image <图> | render text <字> | render video <视频> | render music <音频>',
    context_settings={'help_option_names': ['-h', '--help']})

render_app.command('image')(pic_cmd)
render_app.command('text')(banner_cmd)
render_app.command('video')(video_cmd)
render_app.command('music')(music_cmd)
app.add_typer(render_app, name='render')
