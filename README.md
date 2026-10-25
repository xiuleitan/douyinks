# douyinks

[English](README.en.md)

![macOS](https://img.shields.io/badge/macOS-local-blue)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![uv](https://img.shields.io/badge/uv-managed-green)
![Chrome Extension](https://img.shields.io/badge/Chrome-extension-green)

在 Mac 本机通过命令行下载抖音和快手的点赞内容。第一个终端运行 `douyinks` 启动本地浏览器桥接后台，第二个终端执行下载命令。下载文件直接保存在 Mac。

## 安装

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Chrome（或兼容的 Chromium 浏览器）。

在项目目录安装命令：

```bash
uv tool install --editable .
```

确保 `~/.local/bin` 位于 `PATH` 中；如果安装提示命令目录不在 PATH 中，可运行 `uv tool update-shell`，然后重新打开终端。安装后可在任意目录使用统一入口 `douyinks`。如果以前在 `~/.zshrc` 中定义过指向 `douyinks bot` 的同名函数，请删除旧函数并重新打开终端。

在 `chrome://extensions` 开启开发者模式，点击“加载已解压的扩展程序”，选择本项目的 `extension/` 目录。保持 Chrome 运行，并在浏览器中登录需要下载的平台。

## 日常使用

随时运行以下命令，列出全部可用命令和常用示例：

```bash
douyinks help
```

查看某条命令的参数，例如：

```bash
douyinks help douyin download
```

第一个终端启动后台，并保持运行：

```bash
douyinks
```

后台默认监听 `127.0.0.1:19826`，持续运行至按 `Ctrl+C` 停止。它负责连接本机 Chrome 扩展；下载任务在第二个终端中运行，终端会显示结果。下载期间保持两个终端和 Chrome 打开。

第二个终端检查连接状态：

```bash
douyinks status
```

下载抖音点赞内容：

```bash
douyinks douyin download 300
```

命令会打开抖音自己的点赞列表并自动滚动读取。需要分段时，可指定从第几条开始，例如下载第 60–100 条：

```bash
douyinks douyin download 41 --start 60
```

快手使用“监听网页加载结果”的方式。先在 Chrome 中打开已登录的快手网页，然后启动监听：

```bash
douyinks kuaishou capture start
```

刷新快手网页，进入自己的点赞页面并向下滚动加载视频。查询已捕获的唯一视频数量：

```bash
douyinks kuaishou count
```

数量足够、等待中的响应处理完成后，下载：

```bash
douyinks kuaishou download 300
```

`count` 查询的是本次监听捕获的数量，不是账号全部点赞数量。下载默认读取监听缓存；重新加载扩展或关闭监听页面后，可能需要重新启动监听并加载。只有需要重新收集列表时才再次运行 `douyinks kuaishou capture start`。

也保留快手直接通过接口读取点赞列表的方式：

```bash
douyinks kuaishou download 300 --source like
```

下载数量沿用每次 **1–500** 条的限制。`300` 表示最多选取 300 条点赞内容进行处理；已下载的内容会跳过，列表不足、内容不可用或请求失败时实际新增文件会更少。抖音图文和混合内容可能对应多个媒体文件。两个平台的下载命令请依次运行。

## 下载进度与汇总

进度和最终汇总显示在**执行下载命令的终端**。运行 `douyinks` 的第一个终端负责浏览器桥接；其中的 HTTP 200 日志只表示请求成功，不代表视频已经下载完。

下载时会持续显示已处理数量，以及成功、失败、跳过计数。任务结束后会输出醒目的“下载汇总”，包括请求数量、实际获取数量、成功、失败、跳过、耗时和保存目录。默认收起 HTTP 请求日志，需要排查时可加 `--log-level DEBUG`。

每次按数量下载的任务结束后，会保存最近一次结果；部分视频失败时也会保存。之后可以随时查询：

```bash
douyinks kuaishou summary
douyinks douyin summary
```

汇总文件分别为 `DOWNLOAD_ROOT/kuaishou_last_download.json` 和 `DOWNLOAD_ROOT/douyin_last_download.json`。`summary` 显示最近一次已完成任务的统计和完成时间；进行中的任务请查看下载终端进度。升级前已启动的任务继续使用原有逻辑，新的进度显示和汇总保存从下次启动任务起生效。

## 配置

开发目录安装默认读取项目根目录的 `.env`，不受终端当前目录影响。配置文件可选；已有 `.env` 中的下载目录继续生效。新环境可以复制 `.env.example` 后修改：

```bash
cp .env.example .env
```

已有 `.env` 时请直接编辑，避免覆盖原来的下载目录。普通非 editable 安装默认读取 `~/.config/douyinks/.env`。可通过 `DOUYINKS_ENV_FILE=/absolute/path/to/.env` 指定其他配置文件；两个终端使用同一份配置。系统环境变量优先于配置文件。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOWNLOAD_ROOT` | `~/Downloads/douyinks` | 下载、历史记录和批量进度的根目录。支持 `~`；相对路径以配置文件目录为基准。 |
| `DOUYINKS_DAEMON_HOST` | `127.0.0.1` | 本地桥接地址。 |
| `DOUYINKS_DAEMON_PORT` | `19826` | 本地桥接端口。Chrome 扩展默认使用此端口。 |
| `DOWNLOAD_DELAY_SECONDS` | `3` | 按数量下载时，媒体项之间的等待秒数。 |

扩展固定连接 `localhost:19826`；通常保持默认地址和端口即可。如果调试时修改端口，需要同时修改 `extension/background.js` 中的端口并重新加载扩展。也可运行 `douyinks daemon --host 127.0.0.1 --port 19826` 显式启动后台。

输出目录：

- `DOWNLOAD_ROOT/douyin/likes`
- `DOWNLOAD_ROOT/kuaishou/likes`
- `DOWNLOAD_ROOT/download_history.json`：成功下载历史，用于去重。

## 保留的批量下载命令

这些命令也在本机执行。需要访问网页的命令应先启动 `douyinks` 并连接扩展。

```bash
# 下载抖音链接列表；可指定行号范围
douyinks download-links douyin_links.txt
douyinks download-links douyin_links.txt 1-20

# 导出快手点赞清单；中断后执行相同命令续跑
douyinks export-kuaishou-liked kuaishou_liked.jsonl

# 从快手清单分段下载
douyinks download-kuaishou-liked kuaishou_liked.jsonl 1-100

# 将历史中 unknown 前缀的文件重新下载到单独目录
douyinks redownload-unknown-history /path/to/download_history.json douyin 1-20 --output-dir /path/to/redownload
```

链接列表任务的默认进度文件为 `DOWNLOAD_ROOT/douyin_links_progress.json`，可通过 `--progress-file` 指定。`redownload-unknown-history` 的范围作用于筛选出的 unknown 记录；快手记录需要包含 `play_url`。

兼容原有本地命令 `douyinks start-kuaishou-liked-capture` 和 `douyinks download-kuaishou-captured 300`；所有命令统一使用 `douyinks` 前缀。

## 开发与排查

```bash
uv sync --extra dev
uv run pytest
node --test tests/extension/cdp.test.mjs
```

不安装全局命令时，可使用 `uv run douyinks`、`uv run douyinks douyin download 300`、`uv run douyinks kuaishou count` 等命令。

查看帮助或开启详细日志：

```bash
douyinks --help
douyinks douyin download --help
douyinks kuaishou --help
douyinks --log-level DEBUG
douyinks douyin download 20 --log-level DEBUG
```

后台未运行时，下载命令会提示先在另一终端运行 `douyinks`。扩展未连接时，请检查 Chrome 和扩展是否已开启；按数量下载发生失败时，命令会输出错误并返回非零退出码。
