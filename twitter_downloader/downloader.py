"""
媒体下载器 (灵感来源: gallery-dl + yt-dlp)
支持多平台：Twitter/X, Instagram, TikTok, YouTube, Bilibili
"""

import os
import re
import hashlib
import sqlite3
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse, unquote

import requests
import yt_dlp

from .scraper import TweetData, MediaItem, TwitterScraper


# 支持的平台及其 URL 模式
PLATFORM_PATTERNS = {
    "twitter": [
        r"(?:twitter\.com|x\.com)/\w+/status/\d+",
        r"(?:twitter\.com|x\.com)/\w+/?$",
        r"t\.co/\w+",
    ],
    "instagram": [
        r"instagram\.com/p/[\w-]+",
        r"instagram\.com/reel/[\w-]+",
        r"instagram\.com/stories/[\w-]+",
        r"instagram\.com/[\w.]+/?$",
    ],
    "tiktok": [
        r"tiktok\.com/@[\w.]+/video/\d+",
        r"tiktok\.com/t/\w+",
        r"vm\.tiktok\.com/\w+",
    ],
    "youtube": [
        r"youtube\.com/watch\?v=[\w-]+",
        r"youtube\.com/shorts/[\w-]+",
        r"youtu\.be/[\w-]+",
    ],
    "bilibili": [
        r"bilibili\.com/video/[BA]V\w+",
        r"b23\.tv/\w+",
    ],
    "reddit": [
        r"reddit\.com/r/\w+/comments/\w+",
        r"redd\.it/\w+",
    ],
}

# 画质映射
QUALITY_MAP = {
    "best": "best[ext=mp4]/best",
    "1080p": "best[height<=1080][ext=mp4]/best[height<=1080]",
    "720p": "best[height<=720][ext=mp4]/best[height<=720]",
    "480p": "best[height<=480][ext=mp4]/best[height<=480]",
    "audio": "bestaudio[ext=m4a]/bestaudio",
}


class DownloadArchive:
    """下载归档，避免重复下载"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS archive ("
            "  hash TEXT PRIMARY KEY,"
            "  url TEXT,"
            "  file_path TEXT,"
            "  platform TEXT,"
            "  downloaded_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        # 兼容旧数据库：如果缺少 platform 列则添加
        try:
            self.conn.execute("SELECT platform FROM archive LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE archive ADD COLUMN platform TEXT DEFAULT ''")
        self.conn.commit()

    def has(self, url: str) -> bool:
        h = hashlib.sha256(url.encode()).hexdigest()
        row = self.conn.execute("SELECT 1 FROM archive WHERE hash = ?", (h,)).fetchone()
        return row is not None

    def add(self, url: str, file_path: str, platform: str = ""):
        h = hashlib.sha256(url.encode()).hexdigest()
        self.conn.execute(
            "INSERT OR IGNORE INTO archive (hash, url, file_path, platform) VALUES (?, ?, ?, ?)",
            (h, url, file_path, platform),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


class MediaDownloader:
    """统一媒体下载器 - 多平台支持"""

    def __init__(
        self,
        output_dir: str = "./downloads",
        use_archive: bool = True,
        cookies: Optional[dict] = None,
        progress_callback: Optional[Callable] = None,
        quality: str = "best",
        cookies_from_browser=None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cookies = cookies or {}
        self.progress_callback = progress_callback
        self.quality = quality
        self.cookies_from_browser = cookies_from_browser
        self.scraper = TwitterScraper(cookies=cookies)

        self.archive = None
        if use_archive:
            archive_path = self.output_dir / ".download_archive.db"
            self.archive = DownloadArchive(str(archive_path))

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def _notify(self, event: str, **kwargs):
        if self.progress_callback:
            self.progress_callback({"event": event, **kwargs})

    @staticmethod
    def detect_platform(url: str) -> str:
        """检测链接所属平台"""
        url = url.strip().lower()
        for platform, patterns in PLATFORM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url):
                    return platform
        return "unknown"

    def _sanitize_filename(self, name: str) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = name.strip(". ")
        return name[:200] if name else "unknown"

    def _get_file_ext(self, url: str, media_type: str) -> str:
        parsed = urlparse(url)
        path = unquote(parsed.path)

        if media_type == "image":
            if "format=" in url:
                fmt = re.search(r"format=(\w+)", url)
                if fmt:
                    return f".{fmt.group(1)}"
            ext = Path(path).suffix
            return ext if ext else ".jpg"
        elif media_type == "video":
            return ".mp4"
        elif media_type == "gif":
            return ".mp4"
        return Path(path).suffix or ".bin"

    def _build_filename(self, tweet: TweetData, media: MediaItem, index: int) -> str:
        screen_name = self._sanitize_filename(tweet.user_screen_name or "unknown")
        ext = self._get_file_ext(media.url, media.type)
        suffix = f"_{index}" if index > 0 else ""
        return f"{screen_name}_{tweet.tweet_id}{suffix}{ext}"

    def download_image(self, url: str, save_path: str) -> bool:
        try:
            resp = self.session.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int(downloaded / total * 100)
                        self._notify("progress", downloaded=downloaded, total=total, percent=pct)
            return True
        except Exception as e:
            self._notify("error", message=f"Image download failed: {e}")
            return False

    def download_via_ytdlp(self, url: str, save_dir: str, filename_prefix: str = "") -> dict:
        """使用 yt-dlp 下载任意平台的媒体，优先使用系统 yt-dlp CLI"""
        fmt = QUALITY_MAP.get(self.quality, QUALITY_MAP["best"])

        outtmpl = os.path.join(save_dir, f"{filename_prefix}%(title).80s_%(id)s.%(ext)s")
        if filename_prefix:
            outtmpl = os.path.join(save_dir, f"{filename_prefix}.%(ext)s")

        # 优先使用系统 yt-dlp CLI (版本更新，支持更好)
        result = self._download_via_cli(url, save_dir, outtmpl, fmt)
        if result is not None:
            return result

        # 降级到 Python yt-dlp 库
        return self._download_via_lib(url, outtmpl, fmt)

    def _download_via_cli(self, url: str, save_dir: str, outtmpl: str, fmt: str) -> Optional[dict]:
        """使用系统 yt-dlp CLI 下载"""
        import subprocess
        import shutil

        ytdlp_path = shutil.which("yt-dlp")
        if not ytdlp_path:
            return None  # CLI 不可用，降级到库

        cmd = [
            ytdlp_path,
            "-f", fmt,
            "-o", outtmpl,
            "--merge-output-format", "mp4",
            "--no-write-info-json",
            "--no-write-thumbnail",
            "--print", "after_move:>>>%(filepath)s<<<%(title)s<<<%(duration)s<<<%(uploader)s",
        ]

        if self.cookies_from_browser:
            browser = self.cookies_from_browser[0] if isinstance(self.cookies_from_browser, tuple) else self.cookies_from_browser
            cmd.extend(["--cookies-from-browser", browser])

        cmd.append(url)

        try:
            self._notify("status", message="Using system yt-dlp CLI...")
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
            )

            if proc.returncode != 0:
                error_msg = ""
                if proc.stderr:
                    for line in proc.stderr.strip().split("\n"):
                        if "ERROR" in line:
                            error_msg = line
                            break
                    if not error_msg:
                        error_msg = proc.stderr.strip().split("\n")[-1]
                self._notify("error", message=f"CLI failed: {error_msg}")
                return None

            # 解析 --print 输出: >>>filepath<<<title<<<duration<<<uploader
            filename = ""
            title = ""
            duration = 0
            uploader = ""

            for line in proc.stdout.strip().split("\n"):
                if line.startswith(">>>"):
                    parts = line[3:].split("<<<")
                    if len(parts) >= 1:
                        filename = parts[0].strip()
                    if len(parts) >= 2:
                        title = parts[1].strip()
                    if len(parts) >= 3:
                        try:
                            duration = int(float(parts[2].strip()))
                        except (ValueError, TypeError):
                            pass
                    if len(parts) >= 4:
                        uploader = parts[3].strip()
                    break

            # 如果 --print 没拿到文件路径，扫描目录
            if not filename or not os.path.exists(filename):
                for f in sorted(Path(save_dir).glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
                    if f.is_file() and f.suffix in (".mp4", ".webm", ".mkv", ".m4a", ".mp3"):
                        filename = str(f)
                        break

            if filename and os.path.exists(filename):
                return {
                    "success": True,
                    "filename": os.path.basename(filename),
                    "path": filename,
                    "title": title,
                    "duration": duration,
                    "uploader": uploader,
                    "thumbnail": "",
                }

            return None
        except subprocess.TimeoutExpired:
            self._notify("error", message="CLI download timed out (10min)")
            return None
        except Exception:
            return None

    def _download_via_lib(self, url: str, outtmpl: str, fmt: str) -> dict:
        """使用 Python yt-dlp 库下载 (降级方案)"""
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": fmt,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "writeinfojson": False,
            "writethumbnail": False,
            "progress_hooks": [self._ytdlp_progress_hook],
        }

        if self.cookies_from_browser:
            if isinstance(self.cookies_from_browser, tuple):
                ydl_opts["cookiesfrombrowser"] = self.cookies_from_browser
            else:
                ydl_opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        elif self.cookies:
            ydl_opts["http_headers"] = {
                "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()),
            }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    return {"success": False, "error": "No info extracted"}

                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    base = os.path.splitext(filename)[0]
                    for ext in [".mp4", ".webm", ".mkv", ".m4a", ".mp3"]:
                        if os.path.exists(base + ext):
                            filename = base + ext
                            break

                return {
                    "success": True,
                    "filename": os.path.basename(filename),
                    "path": filename,
                    "title": info.get("title", ""),
                    "duration": info.get("duration", 0),
                    "uploader": info.get("uploader", ""),
                    "thumbnail": info.get("thumbnail", ""),
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _ytdlp_progress_hook(self, d):
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            self._notify("progress", message=f"Downloading... {pct} ({speed})")
        elif d["status"] == "finished":
            self._notify("status", message="Download finished, processing...")

    def download_media(self, url: str) -> dict:
        """统一入口 - 自动检测平台并下载"""
        platform = self.detect_platform(url)
        self._notify("status", message=f"Detected platform: {platform}")

        if platform == "twitter":
            return self.download_tweet(url)
        else:
            return self.download_generic(url, platform)

    def download_generic(self, url: str, platform: str) -> dict:
        """通用下载 - 通过 yt-dlp 支持 Instagram/TikTok/YouTube/Bilibili 等"""
        if self.archive and self.archive.has(url):
            self._notify("skip", message="Already downloaded")
            return {"success": True, "files": [], "skipped": True}

        platform_dir = self.output_dir / platform
        platform_dir.mkdir(parents=True, exist_ok=True)

        self._notify("download", message=f"Downloading from {platform}...")
        result = self.download_via_ytdlp(url, str(platform_dir))

        if result["success"]:
            if self.archive:
                self.archive.add(url, result.get("path", ""), platform)

            self._notify("complete", message=f"Downloaded: {result['filename']}")
            file_path = result.get("path", "")
            return {
                "success": True,
                "platform": platform,
                "title": result.get("title", ""),
                "files": [{
                    "filename": result["filename"],
                    "path": file_path,
                    "status": "success",
                    "type": "video",
                    "size": os.path.getsize(file_path) if file_path and os.path.exists(file_path) else 0,
                }],
            }
        else:
            self._notify("error", message=result.get("error", "Download failed"))
            return {
                "success": False,
                "platform": platform,
                "error": result.get("error", "Download failed"),
                "files": [],
            }

    def download_tweet(self, url: str) -> dict:
        """下载 Twitter 推文媒体"""
        tweet_id = TwitterScraper.extract_tweet_id(url)
        if not tweet_id:
            return {"success": False, "error": "Invalid Twitter URL", "files": []}

        self._notify("status", message=f"Fetching tweet {tweet_id}...")
        tweet = self.scraper.get_tweet(tweet_id)

        if not tweet:
            self._notify("status", message="API failed, trying yt-dlp directly...")
            return self._fallback_ytdlp(url, tweet_id)

        if not tweet.media:
            return {"success": False, "error": "No media found in this tweet", "files": []}

        results = []
        tweet_dir = self.output_dir / "twitter" / self._sanitize_filename(tweet.user_screen_name or "unknown")
        tweet_dir.mkdir(parents=True, exist_ok=True)

        for i, media in enumerate(tweet.media):
            filename = self._build_filename(tweet, media, i)
            save_path = str(tweet_dir / filename)

            if self.archive and self.archive.has(media.url):
                self._notify("skip", message=f"Already downloaded: {filename}")
                results.append({"filename": filename, "status": "skipped", "type": media.type})
                continue

            self._notify("download", message=f"Downloading {media.type}: {filename}")

            success = False
            if media.type == "image":
                success = self.download_image(media.url, save_path)
            elif media.type in ("video", "gif"):
                success = self.download_image(media.url, save_path)  # direct download
                if not success:
                    tweet_url = f"https://x.com/i/status/{tweet_id}"
                    r = self.download_via_ytdlp(tweet_url, str(tweet_dir), f"{tweet.user_screen_name}_{tweet_id}")
                    success = r.get("success", False)
                    if success:
                        save_path = r.get("path", save_path)

            if success:
                if self.archive:
                    self.archive.add(media.url, save_path, "twitter")
                results.append({
                    "filename": filename,
                    "path": save_path,
                    "status": "success",
                    "type": media.type,
                    "size": os.path.getsize(save_path) if os.path.exists(save_path) else 0,
                })
                self._notify("complete", message=f"Downloaded: {filename}")
            else:
                results.append({"filename": filename, "status": "failed", "type": media.type})

        return {
            "success": True,
            "platform": "twitter",
            "tweet_id": tweet.tweet_id,
            "user": tweet.user_screen_name,
            "text": tweet.text[:100],
            "media_count": len(tweet.media),
            "files": results,
        }

    def download_user_media(self, url: str, count: int = 20) -> dict:
        """下载用户媒体时间线（仅 Twitter）"""
        screen_name = TwitterScraper.extract_username(url)
        if not screen_name:
            screen_name = url.strip().lstrip("@")

        if not screen_name:
            return {"success": False, "error": "Invalid username or URL", "files": []}

        self._notify("status", message=f"Fetching media for @{screen_name}...")
        tweets = self.scraper.get_user_media(screen_name, count=count)

        if not tweets:
            return {"success": False, "error": f"No media found for @{screen_name}", "files": []}

        all_results = []
        for tweet in tweets:
            tweet_dir = self.output_dir / "twitter" / self._sanitize_filename(tweet.user_screen_name or "unknown")
            tweet_dir.mkdir(parents=True, exist_ok=True)

            for i, media in enumerate(tweet.media):
                filename = self._build_filename(tweet, media, i)
                save_path = str(tweet_dir / filename)

                if self.archive and self.archive.has(media.url):
                    continue

                success = False
                if media.type == "image":
                    success = self.download_image(media.url, save_path)
                elif media.type in ("video", "gif"):
                    success = self.download_image(media.url, save_path)

                if success and self.archive:
                    self.archive.add(media.url, save_path, "twitter")

                all_results.append({
                    "filename": filename,
                    "status": "success" if success else "failed",
                    "type": media.type,
                })

        return {
            "success": True,
            "platform": "twitter",
            "user": screen_name,
            "tweets_count": len(tweets),
            "files": all_results,
        }

    def _fallback_ytdlp(self, url: str, tweet_id: str) -> dict:
        save_dir = str(self.output_dir / "twitter" / "yt-dlp")
        os.makedirs(save_dir, exist_ok=True)
        result = self.download_via_ytdlp(url, save_dir, tweet_id)

        if result["success"]:
            return {
                "success": True,
                "platform": "twitter",
                "tweet_id": tweet_id,
                "files": [{
                    "filename": result["filename"],
                    "path": result.get("path", ""),
                    "status": "success",
                    "type": "video",
                }],
            }
        return {
            "success": False,
            "error": f"All methods failed: {result.get('error', '')}",
            "files": [],
        }

    def close(self):
        self.scraper.close()
        if self.archive:
            self.archive.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
