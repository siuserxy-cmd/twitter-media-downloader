"""
媒体下载器 (灵感来源: gallery-dl + yt-dlp)
支持图片直接下载 + yt-dlp 视频下载，带进度回调、去重、归档
"""

import os
import re
import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse, unquote

import requests
import yt_dlp

from .scraper import TweetData, MediaItem, TwitterScraper


class DownloadArchive:
    """下载归档 (灵感来源: gallery-dl 的 archive 机制)
    使用 SQLite 记录已下载的文件，避免重复下载
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS archive ("
            "  hash TEXT PRIMARY KEY,"
            "  url TEXT,"
            "  file_path TEXT,"
            "  tweet_id TEXT,"
            "  downloaded_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        self.conn.commit()

    def has(self, url: str) -> bool:
        h = hashlib.sha256(url.encode()).hexdigest()
        row = self.conn.execute("SELECT 1 FROM archive WHERE hash = ?", (h,)).fetchone()
        return row is not None

    def add(self, url: str, file_path: str, tweet_id: str = ""):
        h = hashlib.sha256(url.encode()).hexdigest()
        self.conn.execute(
            "INSERT OR IGNORE INTO archive (hash, url, file_path, tweet_id) VALUES (?, ?, ?, ?)",
            (h, url, file_path, tweet_id),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


class MediaDownloader:
    """统一媒体下载器"""

    def __init__(
        self,
        output_dir: str = "./downloads",
        use_archive: bool = True,
        cookies: Optional[dict] = None,
        progress_callback: Optional[Callable] = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cookies = cookies or {}
        self.progress_callback = progress_callback
        self.scraper = TwitterScraper(cookies=cookies)

        # 归档
        self.archive = None
        if use_archive:
            archive_path = self.output_dir / ".download_archive.db"
            self.archive = DownloadArchive(str(archive_path))

        # requests session
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def _notify(self, event: str, **kwargs):
        """发送进度通知"""
        if self.progress_callback:
            self.progress_callback({"event": event, **kwargs})

    def _sanitize_filename(self, name: str) -> str:
        """清理文件名"""
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = name.strip(". ")
        return name[:200] if name else "unknown"

    def _get_file_ext(self, url: str, media_type: str) -> str:
        """从 URL 获取文件扩展名"""
        parsed = urlparse(url)
        path = unquote(parsed.path)

        if media_type == "image":
            # Twitter 图片 URL 带 format 参数
            if "format=" in url:
                fmt = re.search(r"format=(\w+)", url)
                if fmt:
                    return f".{fmt.group(1)}"
            ext = Path(path).suffix
            return ext if ext else ".jpg"
        elif media_type == "video":
            return ".mp4"
        elif media_type == "gif":
            return ".mp4"  # Twitter GIF 实际是 mp4
        return Path(path).suffix or ".bin"

    def _build_filename(self, tweet: TweetData, media: MediaItem, index: int) -> str:
        """构建文件名 (灵感来源: gallery-dl 的模板系统)"""
        screen_name = self._sanitize_filename(tweet.user_screen_name or "unknown")
        ext = self._get_file_ext(media.url, media.type)
        suffix = f"_{index}" if index > 0 else ""

        return f"{screen_name}_{tweet.tweet_id}{suffix}{ext}"

    def download_image(self, url: str, save_path: str) -> bool:
        """直接下载图片"""
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
                        self._notify("progress", downloaded=downloaded, total=total)

            return True
        except Exception as e:
            self._notify("error", message=f"Image download failed: {e}")
            return False

    def download_video_ytdlp(self, tweet_url: str, save_path: str) -> bool:
        """使用 yt-dlp 下载视频 (最强视频下载能力)"""
        save_dir = str(Path(save_path).parent)
        save_name = Path(save_path).stem

        ydl_opts = {
            "outtmpl": os.path.join(save_dir, f"{save_name}.%(ext)s"),
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

        if self.cookies:
            ydl_opts["http_headers"] = {
                "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()),
            }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([tweet_url])
            return True
        except Exception as e:
            self._notify("error", message=f"yt-dlp download failed: {e}")
            return False

    def download_video_direct(self, url: str, save_path: str) -> bool:
        """直接下载视频（当已有直链时）"""
        return self.download_image(url, save_path)  # 同样的流式下载逻辑

    def download_tweet(self, url: str) -> dict:
        """下载单条推文的所有媒体"""
        tweet_id = TwitterScraper.extract_tweet_id(url)
        if not tweet_id:
            return {"success": False, "error": "Invalid Twitter URL", "files": []}

        self._notify("status", message=f"Fetching tweet {tweet_id}...")
        tweet = self.scraper.get_tweet(tweet_id)

        if not tweet:
            # 如果 API 获取失败，尝试 yt-dlp 直接下载视频
            self._notify("status", message="API failed, trying yt-dlp directly...")
            return self._fallback_ytdlp(url, tweet_id)

        if not tweet.media:
            return {"success": False, "error": "No media found in this tweet", "files": []}

        results = []
        tweet_dir = self.output_dir / self._sanitize_filename(tweet.user_screen_name or "unknown")
        tweet_dir.mkdir(parents=True, exist_ok=True)

        for i, media in enumerate(tweet.media):
            filename = self._build_filename(tweet, media, i)
            save_path = str(tweet_dir / filename)

            # 检查归档
            if self.archive and self.archive.has(media.url):
                self._notify("skip", message=f"Already downloaded: {filename}")
                results.append({
                    "filename": filename,
                    "status": "skipped",
                    "type": media.type,
                })
                continue

            self._notify("download", message=f"Downloading {media.type}: {filename}")

            success = False
            if media.type == "image":
                success = self.download_image(media.url, save_path)
            elif media.type in ("video", "gif"):
                # 优先使用直链下载（更快），失败则用 yt-dlp
                success = self.download_video_direct(media.url, save_path)
                if not success:
                    tweet_url = f"https://x.com/i/status/{tweet_id}"
                    success = self.download_video_ytdlp(tweet_url, save_path)

            if success:
                if self.archive:
                    self.archive.add(media.url, save_path, tweet.tweet_id)
                results.append({
                    "filename": filename,
                    "path": save_path,
                    "status": "success",
                    "type": media.type,
                    "size": os.path.getsize(save_path) if os.path.exists(save_path) else 0,
                })
                self._notify("complete", message=f"Downloaded: {filename}")
            else:
                results.append({
                    "filename": filename,
                    "status": "failed",
                    "type": media.type,
                })

        return {
            "success": True,
            "tweet_id": tweet.tweet_id,
            "user": tweet.user_screen_name,
            "text": tweet.text[:100],
            "media_count": len(tweet.media),
            "files": results,
        }

    def download_user_media(self, url: str, count: int = 20) -> dict:
        """下载用户媒体时间线"""
        screen_name = TwitterScraper.extract_username(url)
        if not screen_name:
            # 也可能直接传入用户名
            screen_name = url.strip().lstrip("@")

        if not screen_name:
            return {"success": False, "error": "Invalid username or URL", "files": []}

        self._notify("status", message=f"Fetching media for @{screen_name}...")
        tweets = self.scraper.get_user_media(screen_name, count=count)

        if not tweets:
            return {"success": False, "error": f"No media found for @{screen_name}", "files": []}

        all_results = []
        for tweet in tweets:
            result = self._download_tweet_media(tweet)
            all_results.extend(result)

        return {
            "success": True,
            "user": screen_name,
            "tweets_count": len(tweets),
            "files": all_results,
        }

    def _download_tweet_media(self, tweet: TweetData) -> list:
        """下载一条推文的媒体"""
        results = []
        tweet_dir = self.output_dir / self._sanitize_filename(tweet.user_screen_name or "unknown")
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
                success = self.download_video_direct(media.url, save_path)

            if success and self.archive:
                self.archive.add(media.url, save_path, tweet.tweet_id)

            results.append({
                "filename": filename,
                "status": "success" if success else "failed",
                "type": media.type,
            })

        return results

    def _fallback_ytdlp(self, url: str, tweet_id: str) -> dict:
        """当 API 失败时，直接用 yt-dlp 下载"""
        save_dir = str(self.output_dir / "yt-dlp")
        os.makedirs(save_dir, exist_ok=True)

        ydl_opts = {
            "outtmpl": os.path.join(save_dir, f"{tweet_id}.%(ext)s"),
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "merge_output_format": "mp4",
            "writeinfojson": False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)

            return {
                "success": True,
                "tweet_id": tweet_id,
                "files": [{
                    "filename": os.path.basename(filename),
                    "path": filename,
                    "status": "success",
                    "type": "video",
                }],
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"All download methods failed: {e}",
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
