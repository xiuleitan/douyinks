import asyncio
import logging

import click
from rich.console import Console

from .browser import check_daemon
from .config import CUSTOM_HEADER, Settings
from .supervisor import build_service_commands, supervise_services

console = Console(stderr=True)


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def run_async(coro):
    return asyncio.run(coro)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Douyinks Matrix downloader."""


@cli.command()
@click.option("--log-level", default="INFO", show_default=True, help="日志级别，例如 DEBUG、INFO、WARNING。")
def bot(log_level):
    """启动 Matrix 下载机器人。"""
    from .bot import MatrixDownloadBot
    from .transient_services import TransientRuntimeServices

    configure_logging(log_level)
    settings = Settings.load()
    logging.getLogger("douyinks.main").info("Starting bot command")
    run_async(MatrixDownloadBot(settings, runtime_services=TransientRuntimeServices(settings, log_level=log_level)).start())


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=19826, show_default=True)
def daemon(host, port):
    """启动浏览器桥接 daemon。"""
    from .daemon import main as daemon_main

    daemon_main(host=host, port=port)


@cli.command()
@click.option("--log-level", default="INFO", show_default=True, help="bot 和 sync-server 的日志级别。")
def serve(log_level):
    """同时启动 daemon、bot 和手机同步服务。"""
    configure_logging(log_level)
    settings = Settings.load()
    supervise_services(build_service_commands(settings, log_level=log_level))


@cli.command("sync-server")
@click.option("--host", default=None, help="覆盖 SYNC_SERVER_HOST。")
@click.option("--port", default=None, type=int, help="覆盖 SYNC_SERVER_PORT。")
@click.option("--log-level", default="INFO", show_default=True, help="日志级别，例如 DEBUG、INFO、WARNING。")
def sync_server(host, port, log_level):
    """启动手机端局域网拉取用的 HTTP 同步服务。"""
    from dataclasses import replace

    from .sync_server import run_sync_server

    configure_logging(log_level)
    settings = Settings.load()
    if host is not None or port is not None:
        settings = replace(
            settings,
            sync_server_host=host if host is not None else settings.sync_server_host,
            sync_server_port=port if port is not None else settings.sync_server_port,
        )
    run_sync_server(settings)


@cli.command()
def status():
    """检查 daemon 和扩展连接状态。"""
    import httpx

    async def _status():
        settings = Settings.load()
        if not await check_daemon(settings.daemon_host, settings.daemon_port):
            console.print("[red]Daemon 未运行[/red]")
            return
        async with httpx.AsyncClient() as client:
            response = await client.get(
                settings.daemon_status_url,
                headers={CUSTOM_HEADER: "1"},
                timeout=5.0,
            )
            data = response.json()
        if data.get("extensionConnected"):
            console.print(f"[green]Daemon 运行中，扩展已连接 ({data.get('extensionVersion', 'unknown')})[/green]")
        else:
            console.print("[yellow]Daemon 运行中，但扩展未连接[/yellow]")

    run_async(_status())


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
    settings = Settings.load()
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
    settings = Settings.load()
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
    settings = Settings.load()
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
    settings = Settings.load()
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
