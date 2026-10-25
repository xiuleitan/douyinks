import asyncio
import logging
import time
from datetime import datetime, timedelta

import click
import httpx
from rich.console import Console

from .browser import check_daemon
from .commands import MAX_DOWNLOAD_COUNT, DownloadCommand
from .config import CUSTOM_HEADER, Settings
from .downloader import DownloadService
from .reports import load_summary, save_summary

console = Console(stderr=True)

HELP_EXAMPLES = """\b
常用操作：
  douyinks                              启动后台，在第一个终端保持运行
  douyinks douyin download 300           下载抖音点赞内容
  douyinks kuaishou capture start        启动快手点赞监听
  douyinks kuaishou count                查询已捕获的视频数量
  douyinks kuaishou download 300         下载快手监听结果
  douyinks kuaishou summary              查看最近一次快手下载汇总

\b
快手先启动监听，再在网页刷新、进入点赞页并滚动加载，然后查询数量、下载。
下载数量为 1–500；已下载内容会跳过。Chrome、扩展和登录状态需要保持可用。
查看命令参数：
  douyinks help douyin download
  douyinks douyin download --help
"""


def command_help_rows(group, ctx, prefix):
    for name in group.list_commands(ctx):
        command = group.get_command(ctx, name)
        if command is None or command.hidden:
            continue
        child_ctx = click.Context(command, info_name=name, parent=ctx)
        path = f"{prefix} {name}"
        if isinstance(command, click.Group):
            yield from command_help_rows(command, child_ctx, path)
        else:
            arguments = [piece for piece in command.collect_usage_pieces(child_ctx) if piece != "[OPTIONS]"]
            yield " ".join([path, *arguments]), command.get_short_help_str()


class LocalCommandGroup(click.Group):
    def format_commands(self, ctx, formatter):
        rows = [("douyinks", "启动本地后台，保持此终端运行。")]
        rows.extend(command_help_rows(self, ctx, "douyinks"))
        with formatter.section("可用命令（完整命令行）"):
            formatter.write_dl(rows)


def configure_logging(level: str = "INFO") -> None:
    configured_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=configured_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    network_level = logging.DEBUG if configured_level <= logging.DEBUG else max(logging.WARNING, configured_level)
    for name in ("httpx", "httpcore", "aiohttp.access"):
        logging.getLogger(name).setLevel(network_level)


def run_async(coro):
    try:
        return asyncio.run(coro)
    except Exception as exc:
        logging.getLogger("douyinks.main").debug("Command failed", exc_info=True)
        raise click.ClickException(str(exc)) from exc


def load_settings() -> Settings:
    try:
        return Settings.load()
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def start_daemon(host=None, port=None, log_level="INFO"):
    from .daemon import main as daemon_main

    configure_logging(log_level)
    settings = load_settings()
    console.print("本地后台启动中。请保持此终端运行，在另一个终端执行下载命令；Ctrl+C 停止。")
    console.print("运行 douyinks help 查看全部命令和常用示例。")
    daemon_main(host=host or settings.daemon_host, port=port or settings.daemon_port)


@click.group(name="douyinks", cls=LocalCommandGroup, invoke_without_command=True, epilog=HELP_EXAMPLES)
@click.version_option(version="0.1.0")
@click.option("--log-level", default="INFO", show_default=True, help="日志级别，例如 DEBUG、INFO、WARNING。")
@click.pass_context
def cli(ctx, log_level):
    """Mac 本地抖音 / 快手下载工具。直接运行 douyinks 启动后台。"""
    if ctx.invoked_subcommand is None:
        start_daemon(log_level=log_level)


@cli.command("help")
@click.argument("command_path", nargs=-1)
@click.pass_context
def show_help(ctx, command_path):
    """列出全部命令；追加命令路径可查看详细参数。"""
    target_ctx = ctx.find_root()
    for name in command_path:
        group = target_ctx.command
        command = group.get_command(target_ctx, name) if isinstance(group, click.Group) else None
        if command is None:
            raise click.UsageError(
                f"未知命令路径: {' '.join(command_path)}。运行 douyinks help 查看全部命令。",
                ctx=ctx,
            )
        target_ctx = click.Context(command, info_name=name, parent=target_ctx)
    click.echo(target_ctx.get_help())


@cli.command()
@click.option("--host", default=None, help="覆盖 DOUYINKS_DAEMON_HOST。")
@click.option("--port", default=None, type=click.IntRange(1, 65535), help="覆盖 DOUYINKS_DAEMON_PORT。")
@click.option("--log-level", default="INFO", show_default=True, help="日志级别，例如 DEBUG、INFO、WARNING。")
def daemon(host, port, log_level):
    """启动本地后台（与直接运行 douyinks 相同）。"""
    start_daemon(host=host, port=port, log_level=log_level)


@cli.command()
def status():
    """检查 daemon 和扩展连接状态。"""
    async def _status():
        settings = load_settings()
        if not await check_daemon(settings.daemon_host, settings.daemon_port):
            raise RuntimeError("本地后台未运行，请先在另一个终端执行 douyinks。")
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(
                settings.daemon_status_url,
                headers={CUSTOM_HEADER: "1"},
                timeout=5.0,
            )
            response.raise_for_status()
            data = response.json()
        if data.get("extensionConnected"):
            console.print(f"[green]Daemon 运行中，扩展已连接 ({data.get('extensionVersion', 'unknown')})[/green]")
        else:
            console.print("[yellow]Daemon 运行中，但扩展未连接[/yellow]")

    run_async(_status())


def print_download_result(result, *, raise_on_failure=True):
    console.print()
    console.rule("[bold]下载汇总[/bold]")
    available = result.get("available")
    if available is not None:
        console.print(f"实际获取: {available} 条内容")
    if available is not None and available < result["requested"]:
        console.print(f"[yellow]请求 {result['requested']} 条，当前仅获取到 {available} 条内容。[/yellow]")
    console.print(
        f"下载完成: 请求 {result['requested']}，成功 {result['success']}，"
        f"失败 {result['failed']}，跳过 {result['skipped']}。"
    )
    console.print(f"保存目录: {result['output_dir']}")
    if "elapsed_seconds" in result:
        console.print(f"耗时: {timedelta(seconds=int(result['elapsed_seconds']))}")
    if "completed_at" in result:
        completed = datetime.fromisoformat(result["completed_at"]).astimezone()
        console.print(f"完成时间: {completed:%Y-%m-%d %H:%M:%S %Z}")
    if result.get("platform"):
        console.print(f"再次查看: douyinks {result['platform']} summary")
    console.rule()
    if raise_on_failure and result["failed"]:
        raise click.ClickException(f"有 {result['failed']} 项下载失败，可重新执行命令重试。")


def print_download_progress(completed, total, counters):
    console.print(
        f"下载进度 {completed}/{total} | 成功 {counters['success']} | "
        f"失败 {counters['failed']} | 跳过 {counters['skipped']}"
    )


def show_saved_summary(platform):
    try:
        summary = load_summary(load_settings(), platform)
        console.print("最近一次已完成的下载任务：")
        print_download_result(summary, raise_on_failure=False)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def run_download(platform, source, count, log_level, *, start=1):
    configure_logging(log_level)
    command = DownloadCommand(
        platform=platform,
        source=source,
        count=count,
        range_start=start if start != 1 else None,
        range_end=start + count - 1 if start != 1 else None,
    )
    settings = load_settings()
    console.print(f"开始下载 {platform} 点赞内容，数量: {count}。")
    console.print("进度和最终汇总会显示在本终端；后台窗口用于保持浏览器桥接连接。")
    started = time.monotonic()
    result = run_async(DownloadService(settings, progress=print_download_progress).run(command))
    result = {**result, "platform": platform, "source": source, "elapsed_seconds": time.monotonic() - started}
    try:
        result = save_summary(settings, platform, result, result["elapsed_seconds"])
    except OSError as exc:
        console.print(f"[yellow]未能保存汇总文件: {exc}[/yellow]")
    print_download_result(result)


@click.group(name="douyin")
@click.version_option(version="0.1.0")
def douyin_cli():
    """在 Mac 本机下载抖音点赞内容。"""


@douyin_cli.command("download")
@click.argument("count", type=click.IntRange(1, MAX_DOWNLOAD_COUNT))
@click.option("--start", default=1, show_default=True, type=click.IntRange(1), help="从点赞列表的第几条开始。")
@click.option("--log-level", default="INFO", show_default=True)
def douyin_download(count, start, log_level):
    """下载 COUNT 条抖音点赞内容。"""
    run_download("douyin", "like", count, log_level, start=start)


@douyin_cli.command("summary")
def douyin_summary():
    """查看最近一次已完成的抖音下载统计。"""
    show_saved_summary("douyin")


@click.group(name="kuaishou")
@click.version_option(version="0.1.0")
def kuaishou_cli():
    """在 Mac 本机监听和下载快手点赞内容。"""


@kuaishou_cli.group("capture")
def kuaishou_capture():
    """监听浏览器中加载的快手点赞列表。"""


@kuaishou_capture.command("start")
@click.option("--log-level", default="INFO", show_default=True)
def kuaishou_capture_start(log_level):
    """启动监听，然后在快手网页刷新、进入点赞页并滚动。"""
    configure_logging(log_level)
    result = run_async(DownloadService(load_settings()).start_kuaishou_liked_capture())
    console.print(
        "快手点赞监听已启动。请刷新快手网页，进入点赞页并向下滚动加载；"
        "运行 douyinks kuaishou count 查询数量，再运行 douyinks kuaishou download 300 下载。"
    )
    if result.get("url"):
        console.print(f"监听页面: {result['url']}")


@kuaishou_cli.command("count")
@click.option("--log-level", default="INFO", show_default=True)
def kuaishou_count(log_level):
    """查询监听已捕获的唯一视频数量。"""
    configure_logging(log_level)
    summary = run_async(DownloadService(load_settings()).count_kuaishou_liked_capture())
    console.print(f"已捕获视频: {summary['video_count']} 条（去重后）")
    console.print(
        f"响应: {summary['response_count']}，等待中: {summary['pending_response_count']}，"
        f"读取失败: {summary['error_count']}，超出缓存: {summary['dropped_response_count']}。"
    )


@kuaishou_cli.command("download")
@click.argument("count", type=click.IntRange(1, MAX_DOWNLOAD_COUNT))
@click.option("--source", type=click.Choice(["captured", "like"]), default="captured", show_default=True,
              help="captured 下载监听结果；like 通过接口直接读取点赞列表。")
@click.option("--log-level", default="INFO", show_default=True)
def kuaishou_download(count, source, log_level):
    """下载 COUNT 条快手点赞视频。"""
    run_download("kuaishou", source, count, log_level)


@kuaishou_cli.command("summary")
def kuaishou_summary():
    """查看最近一次已完成的快手下载统计。"""
    show_saved_summary("kuaishou")


cli.add_command(douyin_cli)
cli.add_command(kuaishou_cli)


@cli.command("download-links")
@click.argument("links_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("line_range", required=False, metavar="[LINE_RANGE]")
@click.option("--delay", default=1.0, show_default=True, type=float, help="每条链接之间等待的秒数。")
@click.option("--progress-file", default=None, type=click.Path(dir_okay=False), help="断点进度 JSON 文件路径。")
@click.option("--detail-retries", default=3, show_default=True, type=int, help="详情接口 Failed to fetch 时的单条重试次数。")
@click.option("--max-consecutive-detail-failures", default=10, show_default=True, type=int, help="连续详情请求失败多少条后停止。")
@click.option("--log-level", default="INFO", show_default=True, help="日志级别，例如 DEBUG、INFO、WARNING。")
def download_links(links_file, line_range, delay, progress_file, detail_retries, max_consecutive_detail_failures, log_level):
    """从链接列表批量下载抖音视频和 note。"""
    from .platforms.douyin.link_batch import download_links_file

    configure_logging(log_level)
    settings = load_settings()
    try:
        result = run_async(
            download_links_file(
                settings,
                links_file,
                delay=delay,
                progress_path=progress_file,
                detail_retries=detail_retries,
                max_consecutive_detail_failures=max_consecutive_detail_failures,
                line_range=line_range,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        "下载完成: "
        f"请求 {result['requested']}，"
        f"本次处理 {result['processed']}，"
        f"已跳过进度 {result['already_done']}，"
        f"成功 {result['success']}，"
        f"失败 {result['failed']}，"
        f"跳过 {result['skipped']}。"
    )
    console.print(f"保存目录: {result['output_dir']}")
    console.print(f"进度文件: {result['progress_file']}")


@cli.command("export-kuaishou-liked")
@click.argument("output_file", type=click.Path(dir_okay=False))
@click.option("--limit", default=0, show_default=True, type=int, help="最多导出多少条，0 表示不限制。")
@click.option("--max-pages", default=0, show_default=True, type=int, help="最多抓取多少页，0 表示不限制。")
@click.option("--page-delay", default=4.0, show_default=True, type=float, help="每页 liked 请求之间等待的秒数。")
@click.option("--fresh", is_flag=True, help="重新导出并覆盖已有清单，不从已有文件续跑。")
@click.option("--log-level", default="INFO", show_default=True, help="日志级别，例如 DEBUG、INFO、WARNING。")
def export_kuaishou_liked(output_file, limit, max_pages, page_delay, fresh, log_level):
    """导出快手喜欢列表为 JSONL 清单。"""
    from .platforms.kuaishou.liked_batch import export_liked_file

    configure_logging(log_level)
    settings = load_settings()
    result = run_async(
        export_liked_file(
            settings,
            output_file,
            limit=limit,
            max_pages=max_pages,
            page_delay=page_delay,
            resume=not fresh,
        )
    )
    console.print(
        "导出完成: "
        f"已有 {result.get('existing', 0)}，"
        f"页数 {result['pages']}，"
        f"条目 {result['exported']}。"
    )
    console.print(f"清单文件: {result['output_file']}")
    if result.get("stopped_reason"):
        console.print(f"[yellow]提前停止: {result['stopped_reason']}[/yellow]")


@cli.command("download-kuaishou-liked")
@click.argument("liked_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("line_range", required=False, metavar="[LINE_RANGE]")
@click.option("--delay", default=1.0, show_default=True, type=float, help="每条视频之间等待的秒数。")
@click.option("--log-level", default="INFO", show_default=True, help="日志级别，例如 DEBUG、INFO、WARNING。")
def download_kuaishou_liked(liked_file, line_range, delay, log_level):
    """从快手 JSONL 清单分批下载喜欢视频。"""
    from .platforms.kuaishou.liked_batch import download_liked_file

    configure_logging(log_level)
    settings = load_settings()
    try:
        result = run_async(
            download_liked_file(
                settings,
                liked_file,
                line_range=line_range,
                delay=delay,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        "下载完成: "
        f"请求 {result['requested']}，"
        f"本次处理 {result['processed']}，"
        f"成功 {result['success']}，"
        f"失败 {result['failed']}，"
        f"跳过 {result['skipped']}。"
    )
    console.print(f"保存目录: {result['output_dir']}")


# Preserve the existing local capture entry points.
cli.add_command(kuaishou_capture_start, "start-kuaishou-liked-capture")
cli.add_command(kuaishou_download, "download-kuaishou-captured")


@cli.command("redownload-unknown-history")
@click.argument("history_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("platform", type=click.Choice(["douyin", "kuaishou", "all"]))
@click.argument("line_range", required=False, metavar="[LINE_RANGE]")
@click.option("--output-dir", default=None, type=click.Path(file_okay=False), help="单独保存目录，默认 DOWNLOAD_ROOT/redownload_unknown。")
@click.option("--delay", default=1.0, show_default=True, type=float, help="每条记录之间等待的秒数。")
@click.option("--log-level", default="INFO", show_default=True, help="日志级别，例如 DEBUG、INFO、WARNING。")
def redownload_unknown_history_cmd(history_file, platform, line_range, output_dir, delay, log_level):
    """从 download_history 中重新下载 unknown 前缀记录。"""
    from .unknown_redownload import redownload_unknown_history

    configure_logging(log_level)
    settings = load_settings()
    try:
        result = run_async(
            redownload_unknown_history(
                settings,
                history_file,
                platform=platform,
                line_range=line_range,
                output_dir=output_dir,
                delay=delay,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        "重新下载完成: "
        f"请求 {result['requested']}，"
        f"本次处理 {result['processed']}，"
        f"成功 {result['success']}，"
        f"失败 {result['failed']}，"
        f"跳过 {result['skipped']}。"
    )
    console.print(f"保存目录: {result['output_dir']}")


if __name__ == "__main__":
    cli()
