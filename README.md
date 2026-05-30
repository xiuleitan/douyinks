# douyinks

[English](README.en.md)

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![uv](https://img.shields.io/badge/uv-managed-green)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)
![Matrix](https://img.shields.io/badge/Matrix-bot-blue)
![Chrome Extension](https://img.shields.io/badge/Chrome-extension-green)

douyinks 是一个通过 Matrix 消息触发的抖音和快手视频下载工具。它包含命令行程序、本地浏览器桥接 daemon 和 Chrome 扩展，用于在已登录的浏览器会话中读取页面与接口数据。

## 功能

- 从准备好的抖音链接列表下载喜欢的视频、图文 note 和图片。
- 将快手喜欢列表导出为可续跑的 JSONL 清单。
- 根据导出的快手 JSONL 清单分段下载视频。
- 在允许的 Matrix 房间中发送文本命令触发下载。
- 在 `DOWNLOAD_ROOT` 下记录进度、历史和 Matrix 同步状态，方便续跑和去重。
- 通过本地 Chrome 扩展桥接已登录的抖音/快手浏览器会话。

## 环境要求

- Python 3.12 或更新版本
- [uv](https://docs.astral.sh/uv/) 依赖和虚拟环境管理工具
- Google Chrome 或 Chromium 系浏览器，用于加载扩展桥接
- 一个 Matrix 账号，用于 bot 模式
- 已登录的抖音/快手浏览器会话，用于需要账号状态的平台操作

## 安装与配置

安装依赖和开发工具：

```bash
uv sync --extra dev
```

复制示例环境变量文件，并填写本地配置：

```bash
cp .env.example .env
```

在 `chrome://extensions` 中加载 `extension/` 目录。打开开发者模式，选择“加载已解压的扩展程序”，然后选择项目里的 `extension` 目录。

## 配置项

`douyinks` 默认从 `.env` 读取配置。请把 `.env` 作为本地私密文件保存，仓库里只提交 `.env.example`。

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `MATRIX_HOMESERVER_URL` | 是 | Matrix homeserver 地址。 |
| `MATRIX_USERNAME` | 是 | Matrix bot 账号。 |
| `MATRIX_PASSWORD` | 是 | Matrix bot 账号密码。 |
| `MATRIX_ALLOWED_ROOM_IDS` | 是 | 允许触发下载的 Matrix 房间 ID，多个值用英文逗号分隔。 |
| `DOWNLOAD_ROOT` | 是 | 下载文件、进度、历史和同步状态的根目录。 |
| `DOUYINKS_DAEMON_HOST` | 否 | 本地 daemon 监听地址，默认 `127.0.0.1`。 |
| `DOUYINKS_DAEMON_PORT` | 否 | 本地 daemon 端口，默认 `19826`。 |
| `DOWNLOAD_DELAY_SECONDS` | 否 | Matrix 触发下载时每条之间的等待秒数，默认 `3`。 |
| `SYNC_SERVER_ENABLED` | 否 | 是否启用手机端拉取用的同步服务，默认 `false`。 |
| `SYNC_SERVER_HOST` | 否 | 同步服务监听地址；局域网访问通常设为 `0.0.0.0`。 |
| `SYNC_SERVER_PORT` | 否 | 同步服务端口，默认 `19827`。 |
| `SYNC_TOKEN` | 否 | 手机 APP 调用同步接口时使用的固定 Bearer Token。 |
| `TRANSIENT_SERVICE_IDLE_SECONDS` | 否 | bot 临时启动 daemon 和 sync-server 后的空闲保留秒数，默认 `1800`。 |

示例：

```env
MATRIX_HOMESERVER_URL=https://matrix.example
MATRIX_USERNAME=@douyinks:example
MATRIX_PASSWORD=replace-with-your-matrix-password
MATRIX_ALLOWED_ROOM_IDS=!roomid:example
DOWNLOAD_ROOT=/path/to/downloads
DOUYINKS_DAEMON_HOST=127.0.0.1
DOUYINKS_DAEMON_PORT=19826
DOWNLOAD_DELAY_SECONDS=3
SYNC_SERVER_ENABLED=false
SYNC_SERVER_HOST=0.0.0.0
SYNC_SERVER_PORT=19827
SYNC_TOKEN=replace-with-a-long-random-sync-token
TRANSIENT_SERVICE_IDLE_SECONDS=1800
```

## 使用方法

请在项目根目录运行命令。

启动浏览器桥接 daemon：

```bash
uv run douyinks daemon
```

显式指定监听地址和端口：

```bash
uv run douyinks daemon --host 127.0.0.1 --port 19826
```

检查 daemon 是否运行、扩展是否已连接：

```bash
uv run douyinks status
```

下载准备好的抖音链接列表：

```bash
uv run douyinks download-links douyin_links.txt
```

只下载链接列表中的指定行号范围：

```bash
uv run douyinks download-links douyin_links.txt 1-20
uv run douyinks download-links douyin_links.txt 21-40
```

设置自定义间隔或进度文件：

```bash
uv run douyinks download-links douyin_links.txt --delay 2 --progress-file /path/to/progress.json
```

重新下载历史记录中 `unknown` 前缀的文件到单独目录：

```bash
uv run douyinks redownload-unknown-history /path/to/downloads/download_history.json douyin 1-20 --output-dir /path/to/downloads/redownload_unknown
```

这里的 `1-20` 是在筛选出 `unknown` 记录后的序号范围，不是原始 JSON 文件行号。命令会按平台保存到独立子目录，例如 `redownload_unknown/douyin`。如果选择 `kuaishou`，历史记录中必须带有可下载的 `play_url`，否则无法只凭历史记录重新下载。

导出快手喜欢列表：

```bash
uv run douyinks export-kuaishou-liked kuaishou_liked.jsonl
```

如果导出中断，重新运行同一条命令即可续跑。只有在需要覆盖已有清单并重新开始时才使用 `--fresh`。

分段下载快手清单：

```bash
uv run douyinks download-kuaishou-liked kuaishou_liked.jsonl 1-100
uv run douyinks download-kuaishou-liked kuaishou_liked.jsonl 101-200
```

启动 Matrix bot：

```bash
uv run douyinks bot
```

日常使用时推荐只常驻 Matrix bot。收到下载命令后，bot 会临时启动浏览器桥接 daemon；如果 `SYNC_SERVER_ENABLED=true`，也会临时启动手机同步服务。下载完成后会保留 `TRANSIENT_SERVICE_IDLE_SECONDS` 秒，默认半小时，方便手机 APP 拉取新增文件；空闲时间到后会自动停止由 bot 启动的 daemon 和 sync-server。

排查问题时可开启 debug 日志：

```bash
uv run douyinks bot --log-level DEBUG
```

如需调试，也可以一次启动浏览器桥接 daemon、Matrix bot 和手机同步服务：

```bash
uv run douyinks serve
```

启动手机 APP 局域网拉取用的同步服务：

```bash
uv run douyinks sync-server
```

手机端接口说明见 [Mobile Sync API](docs/mobile-sync-api.md)。同步服务使用 `Authorization: Bearer <SYNC_TOKEN>` 保护接口；手机 APP 端手动填写笔记本同步服务地址，例如 `http://192.168.1.23:19827`。如果局域网 IP 变化，可以在 Matrix 房间发送 `ip` 或 `查询 ip` 获取当前地址。

同步服务第一次启动时会把已有下载记录作为基线处理，不会把历史文件全部列为待同步；之后新增下载才会出现在手机端的 pending 列表中。

## Matrix 命令

在允许的 Matrix 房间中发送以下消息：

```text
download douyin like 20
download kuaishou like 20
ip
```

数量必须是正整数，且不能超过 `200`。

发送 `ip` 或 `查询 ip` 时，bot 会返回当前笔记本的局域网 IP。如果 `SYNC_SERVER_ENABLED=true`，回复中也会包含手机 APP 可填写的同步服务地址，例如 `http://192.168.1.23:19827`。

## 输出与续跑文件

下载文件会保存到：

- `DOWNLOAD_ROOT/douyin/likes`
- `DOWNLOAD_ROOT/kuaishou/likes`

运行状态也会写入 `DOWNLOAD_ROOT`：

- `download_history.json` 记录已成功下载的文件，用于去重。
- `matrix_sync_state.json` 保存 Matrix 同步 token，避免重启后重复处理旧消息。
- `douyin_links_progress.json` 记录抖音链接列表批量任务的续跑进度，除非命令中指定了其他进度文件。

## 开发

运行测试：

```bash
uv run pytest
```

查看命令行帮助：

```bash
uv run douyinks --help
```

项目使用 `uv.lock` 锁定依赖；如果依赖变更是有意的，请一并提交该文件。

如果希望打开终端后在任意目录直接启动，可以在 `~/.zshrc` 中添加一个函数，让它自动进入项目目录再运行：

```bash
douyinks-serve() {
  cd /path/to/douyinks && uv run douyinks bot
}
```

重新打开终端，或运行 `source ~/.zshrc` 后，即可直接执行：

```bash
douyinks-serve
```

这种方式比单纯把命令加入 PATH 更适合当前项目，因为 `douyinks` 默认从项目目录读取 `.env`。日常推荐启动 `bot`；它会在收到下载命令后按需拉起 daemon 和 sync-server。

## 隐私与安全

- 不要提交 `.env`，其中包含 Matrix 凭据和本地路径。
- 不要提交导出的喜欢列表清单、浏览器页面快照、已下载视频、进度文件或历史文件。这些文件可能暴露账号活动、喜欢内容、带签名的媒体 URL、本地路径或个人偏好。
- 同步服务会在局域网暴露下载文件拉取接口，请设置足够长的 `SYNC_TOKEN`，并只在可信网络中开启。
- Chrome 扩展申请了 `debugger`、`tabs`、`cookies` 和 `<all_urls>` 权限，用于桥接已登录浏览器会话。请只从可信的本地代码加载该扩展。
- 如果真实凭据曾经进入 git 历史，请在发布前轮换这些凭据。

## 许可证

当前仓库尚未包含许可证文件。如果希望他人使用、修改或分发本项目，请在发布前添加许可证。
