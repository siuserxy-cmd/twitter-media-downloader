<div align="center">

# Twitter Media Downloader

### 全平台社交媒体视频/图片下载工具

**一键下载 Twitter、Instagram、TikTok、YouTube、Bilibili、Reddit 的视频和图片**

[![GitHub stars](https://img.shields.io/github/stars/siuserxy-cmd/twitter-media-downloader?style=flat-square&color=1d9bf0)](https://github.com/siuserxy-cmd/twitter-media-downloader/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](Dockerfile)

[在线体验](https://twitter-media-downloader.onrender.com) · [快速开始](#-快速开始) · [功能介绍](#-功能特性) · [联系作者](#-联系作者)

</div>

---

## 这个工具能干嘛？

> 你是否经常在 Twitter/X 上刷到好看的图片和视频，想保存下来却不知道怎么下载？

**Media Downloader** 帮你一键搞定！粘贴链接，点击下载，就这么简单。

不仅支持 Twitter，**Instagram、TikTok、YouTube、Bilibili、Reddit** 也全部支持。

---

## 支持的平台

| 平台 | 视频 | 图片 | 批量 | 用户时间线 |
|:----:|:----:|:----:|:----:|:--------:|
| Twitter / X | ✅ | ✅ | ✅ | ✅ |
| Instagram | ✅ | ✅ | ✅ | - |
| TikTok | ✅ | - | ✅ | - |
| YouTube | ✅ | - | ✅ | - |
| Bilibili | ✅ | - | ✅ | - |
| Reddit | ✅ | ✅ | ✅ | - |

---

## 功能特性

### 核心功能

- **多平台下载** — 6 大主流平台，粘贴链接即可下载
- **博主主页浏览** — 输入 Twitter 用户名，展示媒体缩略图网格，勾选后下载
- **批量下载** — 多个链接一次性粘贴，队列管理，并发下载
- **画质选择** — Best / 1080p / 720p / 480p / 纯音频
- **ZIP 打包** — 批量文件一键打包下载

### 体验优化

- **深色/浅色主题** — 一键切换，自动记住偏好
- **中/英文切换** — 完整双语支持
- **平台自动识别** — 粘贴链接自动显示平台图标
- **拖拽下载** — 直接把链接拖到页面
- **剪贴板检测** — 复制链接后自动填入
- **快捷键** — `Enter` 下载，`Ctrl+B` 批量
- **Toast 通知** — 下载完成/失败实时提醒
- **移动端适配** — 手机也能用

### 高级功能

- **收藏博主** — 保存常用账号，一键浏览
- **下载历史** — 完整记录，随时查看
- **统计面板** — 下载次数、文件数、总大小、各平台统计
- **Cookie 导入** — 支持下载私密/年龄限制内容
- **自动重试** — 失败自动重试 3 次
- **下载归档** — 自动去重，不会重复下载

---

## 技术架构

整合了三个顶级开源项目的核心能力：

```
┌─────────────────────────────────────────────┐
│              Media Downloader               │
│         (Flask Web GUI + CLI)               │
├─────────────┬──────────────┬────────────────┤
│   yt-dlp    │  gallery-dl  │   twscrape     │
│  (154K ⭐)  │  (17.5K ⭐)  │   (2.3K ⭐)    │
│             │              │                │
│ 视频下载引擎 │ 图片批量下载  │ Twitter API    │
│ 格式/画质选择│ 归档去重     │ GraphQL 数据层  │
│ 流合并处理   │ 文件命名模板  │ 账号池管理      │
└─────────────┴──────────────┴────────────────┘
```

**不需要 API Key，不需要 Token，不花钱。**

原理：通过 Twitter Syndication API（嵌入接口）、GraphQL Guest Token（游客模式）、yt-dlp 网页解析三层降级策略获取媒体。

---

## 快速开始

### 方式一：在线使用（最简单）

直接访问：**https://twitter-media-downloader.onrender.com**

无需安装，打开即用。

### 方式二：本地运行

```bash
# 克隆项目
git clone https://github.com/siuserxy-cmd/twitter-media-downloader.git
cd twitter-media-downloader

# 安装依赖
pip install -r requirements.txt

# 启动 Web 界面
python main.py --web --port 8899

# 打开浏览器访问 http://127.0.0.1:8899
```

### 方式三：Docker 部署

```bash
docker build -t media-downloader .
docker run -p 8899:8899 media-downloader
```

### 方式四：命令行使用

```bash
# 下载单条推文
python main.py "https://x.com/user/status/123456789"

# 下载用户媒体时间线
python main.py -u "@username" -c 50

# 指定画质
python main.py "https://youtube.com/watch?v=xxx" --quality 720p
```

---

## 使用指南

### 1. 下载单条内容

粘贴任意平台的链接到输入框，点击 **Download**，等待完成。

### 2. 批量下载

点击 **Batch** 按钮，每行粘贴一个链接，点击开始。系统会自动排队、并发下载。

### 3. 浏览博主媒体

切换到 **Browse User** 页面，输入 Twitter 用户名（如 `@elonmusk`），系统会加载该用户的媒体内容，以缩略图网格展示。勾选想要的内容，点击下载。

### 4. 下载私密内容

进入 **Settings** 页面，导入浏览器 Cookie，即可访问需要登录才能看到的内容。

---

## CLI 参数

```
usage: python main.py [-h] [-o OUTPUT] [-u] [-c COUNT] [--web] [--port PORT] [--no-archive] [url]

positional arguments:
  url                   链接或推文 ID

optional arguments:
  -o, --output          输出目录 (默认: ./downloads)
  -u, --user            下载用户媒体时间线
  -c, --count           获取推文数量 (默认: 20)
  --web                 启动 Web 界面
  --port                Web 端口 (默认: 5000)
  --no-archive          禁用下载归档（允许重复下载）
```

---

## 项目结构

```
twitter-media-downloader/
├── main.py                          # 启动入口
├── requirements.txt                 # Python 依赖
├── Dockerfile                       # Docker 部署
├── render.yaml                      # Render 部署配置
├── setup.py                         # 包安装配置
└── twitter_downloader/
    ├── __init__.py
    ├── cli.py                       # 命令行接口
    ├── scraper.py                   # Twitter 数据抓取层
    ├── downloader.py                # 统一下载器（多平台）
    ├── web.py                       # Flask Web 服务
    └── templates/
        └── index.html               # Web GUI 前端
```

---

## 常见问题

**Q: 为什么不需要 API Key？**

A: 本工具不使用官方付费 API。通过 Twitter 的公开嵌入接口、网页端 Guest Token、以及 yt-dlp 的网页解析来获取媒体内容。就像你在浏览器里看到的内容一样，只是帮你把文件保存下来。

**Q: 能下载私密账号的内容吗？**

A: 需要在 Settings 里导入你的浏览器 Cookie。Cookie 只会保存在你的本地/服务器上，不会上传到任何第三方。

**Q: 下载速度慢怎么办？**

A: 免费版 Render 服务器在美国，国内访问可能较慢。建议本地运行（`python main.py --web`）或自行部署到国内服务器。

**Q: 支持哪些视频格式？**

A: 默认下载 MP4 格式。可以在画质选择中选择 "Audio" 仅下载音频（M4A 格式）。

---

## Star History

如果觉得好用，请给个 Star 支持一下！

[![Star History Chart](https://api.star-history.com/svg?repos=siuserxy-cmd/twitter-media-downloader&type=Date)](https://star-history.com/#siuserxy-cmd/twitter-media-downloader&Date)

---

## 联系作者

<div align="center">

<img src="docs/author.jpeg" width="280" style="border-radius: 12px;" />

**小伟**

独立开发者 / AI 应用探索者

</div>

> 欢迎交流技术、分享想法、反馈问题！

**微信号：`你的微信号`**（加好友请备注：GitHub）

如果你也对 AI 工具开发感兴趣，欢迎加我微信交流！

---

## License

[MIT](LICENSE) - 开源万岁，随意使用。

---

<div align="center">
<sub>Built with yt-dlp + gallery-dl + twscrape | Made by 小伟</sub>
</div>
