"""下载: 流式写盘 + 断点续传 + 进度 (原 net/download.py 拆为子包, P4)

二进制目标落盘本质就是个下载动作, 就得按下载的规矩办:

1. **边收边写** —— 不把整个文件读进内存。手机内存经不起一个 200MB 的视频,
   而且"先整段读、再写盘"在超大文件上必然失败, 那时你已经白下了九成。
2. **断了能续** —— `.part` 临时文件 + `Range` 续传, 并带 `If-Range` 验证器:
   没有验证器的续传是赌博, 服务端资源换了照样接着写, 拼出一个"前半旧后半新"的
   坏文件, 打开才知道。
3. **进度看得见** —— 长任务不吭声最难受。TTY 下原地刷一行 (带速率与 ETA),
   非 TTY (管道/日志/agent 抓取) 只报一句结果 —— 几百行 `\\r` 进度塞进日志是污染。

这个包不碰浏览器指纹/代理/TLS: 请求由调用方通过 `opener` 注入, 这里只负责
续传判断、写盘、进度。下载逻辑跟反爬纠缠在一起, 两边都没法单独测。

子模块:
  progress  进度显示 (human / _eta / Progress)
  resume    .part 现场元数据 + Range 请求头 + 校验/长度解析
  transfer  下载主体 (单连接 / 分片并发) + 熔断记账
"""
# `X as X` = 显式再导出 (ruff F401 认这个写法); 本模块只做再导出
from webtool.net.download.progress import Progress as Progress, _eta as _eta
from webtool.net.download.progress import human as human
from webtool.net.download.resume import (
    _META_SUFFIX as _META_SUFFIX, _drop_meta as _drop_meta,
    _meta_path as _meta_path, _save_meta as _save_meta, part_path as part_path,
    request_headers as request_headers, resume_state as resume_state,
    total_of as total_of, validator_of as validator_of)
from webtool.net.download.transfer import (
    CHUNK as CHUNK, JOBS_MAX as JOBS_MAX, MIN_SPLIT as MIN_SPLIT,
    _close as _close, _download_single as _download_single,
    _finish_progress as _finish_progress, _seg_meta as _seg_meta,
    _segments as _segments, _write_seg_meta as _write_seg_meta,
    download as download, download_parallel as download_parallel)

__all__ = [
    'CHUNK', 'JOBS_MAX', 'MIN_SPLIT', 'Progress', 'download',
    'download_parallel', 'human', 'part_path', 'request_headers',
    'resume_state', 'total_of', 'validator_of',
]
