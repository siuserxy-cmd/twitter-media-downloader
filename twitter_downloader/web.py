"""Web GUI 界面 (Flask) - 全功能版"""

import io
import os
import json
import time
import zipfile
import threading
from pathlib import Path
from collections import deque

from flask import Flask, render_template, request, jsonify, send_from_directory, send_file

from .downloader import MediaDownloader
from .scraper import TwitterScraper


# 全局状态
download_tasks = {}
task_counter = 0
task_lock = threading.Lock()
download_queue = deque()
queue_running = False
MAX_CONCURRENT = 3
MAX_RETRIES = 3

# 统计
stats = {
    "total_downloads": 0,
    "total_files": 0,
    "total_bytes": 0,
    "by_platform": {},
}
stats_lock = threading.Lock()

# Cookie 存储
saved_cookies = {}


def create_app(output_dir: str = "./downloads"):
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "templates", "static"),
    )
    app.config["OUTPUT_DIR"] = output_dir

    # ===== Pages =====

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/docs/<path:filepath>")
    def serve_docs(filepath):
        docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")
        return send_from_directory(docs_dir, filepath)

    # ===== Download APIs =====

    @app.route("/api/download", methods=["POST"])
    def api_download():
        global task_counter
        data = request.get_json()
        url = data.get("url", "").strip()
        mode = data.get("mode", "tweet")
        count = data.get("count", 20)
        quality = data.get("quality", "best")

        if not url:
            return jsonify({"error": "URL is required"}), 400

        with task_lock:
            task_counter += 1
            task_id = str(task_counter)

        download_tasks[task_id] = {
            "id": task_id,
            "url": url,
            "status": "running",
            "logs": [],
            "result": None,
            "created_at": time.time(),
            "retries": 0,
        }

        def run_download(tid=task_id, retries=0):
            logs = download_tasks[tid]["logs"]

            def on_progress(data):
                logs.append(data)

            try:
                with MediaDownloader(
                    output_dir=app.config["OUTPUT_DIR"],
                    progress_callback=on_progress,
                    quality=quality,
                    cookies=saved_cookies.get("global"),
                ) as dl:
                    if mode == "user":
                        result = dl.download_user_media(url, count=count)
                    else:
                        result = dl.download_media(url)

                if result.get("success"):
                    download_tasks[tid]["result"] = result
                    download_tasks[tid]["status"] = "done"
                    _update_stats(result)
                elif retries < MAX_RETRIES:
                    # 自动重试
                    download_tasks[tid]["retries"] = retries + 1
                    logs.append({"event": "retry", "message": f"Retrying... ({retries + 1}/{MAX_RETRIES})"})
                    time.sleep(2)
                    run_download(tid, retries + 1)
                else:
                    download_tasks[tid]["result"] = result
                    download_tasks[tid]["status"] = "error"
            except Exception as e:
                if retries < MAX_RETRIES:
                    download_tasks[tid]["retries"] = retries + 1
                    logs.append({"event": "retry", "message": f"Error, retrying... ({retries + 1}/{MAX_RETRIES})"})
                    time.sleep(2)
                    run_download(tid, retries + 1)
                else:
                    download_tasks[tid]["status"] = "error"
                    download_tasks[tid]["result"] = {"success": False, "error": str(e), "files": []}

        thread = threading.Thread(target=run_download, daemon=True)
        thread.start()

        return jsonify({"task_id": task_id})

    @app.route("/api/batch", methods=["POST"])
    def api_batch():
        global task_counter
        data = request.get_json()
        urls = data.get("urls", [])
        quality = data.get("quality", "best")

        if not urls:
            return jsonify({"error": "URLs required"}), 400

        task_ids = []
        for url in urls:
            url = url.strip()
            if not url:
                continue

            with task_lock:
                task_counter += 1
                task_id = str(task_counter)

            download_tasks[task_id] = {
                "id": task_id,
                "url": url,
                "status": "queued",
                "logs": [],
                "result": None,
                "created_at": time.time(),
                "retries": 0,
            }
            task_ids.append(task_id)
            download_queue.append((task_id, url, quality))

        _start_queue_processor(app.config["OUTPUT_DIR"])
        return jsonify({"task_ids": task_ids, "queued": len(task_ids)})

    def _start_queue_processor(output_dir):
        global queue_running
        if queue_running:
            return
        queue_running = True

        def process_queue():
            global queue_running
            active_threads = []

            while download_queue or active_threads:
                active_threads = [t for t in active_threads if t.is_alive()]

                while download_queue and len(active_threads) < MAX_CONCURRENT:
                    task_id, url, quality = download_queue.popleft()
                    download_tasks[task_id]["status"] = "running"

                    def run(tid=task_id, u=url, q=quality, retries=0):
                        logs = download_tasks[tid]["logs"]

                        def on_progress(data):
                            logs.append(data)

                        try:
                            with MediaDownloader(
                                output_dir=output_dir,
                                progress_callback=on_progress,
                                quality=q,
                                cookies=saved_cookies.get("global"),
                            ) as dl:
                                result = dl.download_media(u)

                            if result.get("success"):
                                download_tasks[tid]["result"] = result
                                download_tasks[tid]["status"] = "done"
                                _update_stats(result)
                            elif retries < MAX_RETRIES:
                                download_tasks[tid]["retries"] = retries + 1
                                logs.append({"event": "retry", "message": f"Retrying... ({retries + 1}/{MAX_RETRIES})"})
                                time.sleep(2)
                                run(tid, u, q, retries + 1)
                            else:
                                download_tasks[tid]["result"] = result
                                download_tasks[tid]["status"] = "error"
                        except Exception as e:
                            if retries < MAX_RETRIES:
                                download_tasks[tid]["retries"] = retries + 1
                                time.sleep(2)
                                run(tid, u, q, retries + 1)
                            else:
                                download_tasks[tid]["status"] = "error"
                                download_tasks[tid]["result"] = {"success": False, "error": str(e), "files": []}

                    t = threading.Thread(target=run, daemon=True)
                    t.start()
                    active_threads.append(t)

                time.sleep(0.5)

            queue_running = False

        threading.Thread(target=process_queue, daemon=True).start()

    # ===== User/Blogger Browse API =====

    @app.route("/api/user/preview", methods=["POST"])
    def api_user_preview():
        """获取博主的媒体预览（不下载，只获取元数据和缩略图）"""
        data = request.get_json()
        username = data.get("username", "").strip().lstrip("@")
        count = data.get("count", 30)

        if not username:
            return jsonify({"error": "Username is required"}), 400

        try:
            scraper = TwitterScraper(cookies=saved_cookies.get("global"))
            tweets = scraper.get_user_media(username, count=count)
            scraper.close()

            if not tweets:
                return jsonify({"error": f"No media found for @{username}", "items": []})

            items = []
            for tweet in tweets:
                for i, media in enumerate(tweet.media):
                    items.append({
                        "tweet_id": tweet.tweet_id,
                        "index": i,
                        "type": media.type,
                        "thumb_url": media.thumb_url or media.url,
                        "full_url": media.url,
                        "width": media.width,
                        "height": media.height,
                        "text": tweet.text[:80] if tweet.text else "",
                        "created_at": tweet.created_at,
                        "likes": tweet.like_count,
                        "retweets": tweet.retweet_count,
                    })

            return jsonify({
                "success": True,
                "username": username,
                "total": len(items),
                "items": items,
            })
        except Exception as e:
            return jsonify({"error": str(e), "items": []})

    @app.route("/api/user/download", methods=["POST"])
    def api_user_download():
        """下载博主选中的媒体"""
        global task_counter
        data = request.get_json()
        username = data.get("username", "").strip()
        selected = data.get("selected", [])  # list of {tweet_id, index, url, type}
        quality = data.get("quality", "best")

        if not selected:
            return jsonify({"error": "No items selected"}), 400

        with task_lock:
            task_counter += 1
            task_id = str(task_counter)

        download_tasks[task_id] = {
            "id": task_id,
            "url": f"@{username} ({len(selected)} items)",
            "status": "running",
            "logs": [],
            "result": None,
            "created_at": time.time(),
            "retries": 0,
        }

        def run_selected_download():
            logs = download_tasks[task_id]["logs"]
            results = []

            with MediaDownloader(
                output_dir=app.config["OUTPUT_DIR"],
                quality=quality,
                cookies=saved_cookies.get("global"),
            ) as dl:
                user_dir = Path(app.config["OUTPUT_DIR"]) / "twitter" / dl._sanitize_filename(username)
                user_dir.mkdir(parents=True, exist_ok=True)

                for item in selected:
                    url = item.get("url", "")
                    media_type = item.get("type", "image")
                    tweet_id = item.get("tweet_id", "unknown")
                    index = item.get("index", 0)

                    ext = ".jpg" if media_type == "image" else ".mp4"
                    suffix = f"_{index}" if index > 0 else ""
                    filename = f"{username}_{tweet_id}{suffix}{ext}"
                    save_path = str(user_dir / filename)

                    if dl.archive and dl.archive.has(url):
                        logs.append({"event": "skip", "message": f"Skipped: {filename}"})
                        results.append({"filename": filename, "status": "skipped", "type": media_type})
                        continue

                    logs.append({"event": "download", "message": f"Downloading: {filename}"})

                    success = False
                    if media_type == "image":
                        success = dl.download_image(url, save_path)
                    else:
                        success = dl.download_image(url, save_path)
                        if not success:
                            tweet_url = f"https://x.com/i/status/{tweet_id}"
                            r = dl.download_via_ytdlp(tweet_url, str(user_dir), f"{username}_{tweet_id}")
                            success = r.get("success", False)

                    if success:
                        if dl.archive:
                            dl.archive.add(url, save_path, "twitter")
                        size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
                        results.append({
                            "filename": filename,
                            "path": save_path,
                            "status": "success",
                            "type": media_type,
                            "size": size,
                        })
                        logs.append({"event": "complete", "message": f"Done: {filename}"})
                    else:
                        results.append({"filename": filename, "status": "failed", "type": media_type})

            download_tasks[task_id]["result"] = {
                "success": True,
                "platform": "twitter",
                "user": username,
                "files": results,
            }
            download_tasks[task_id]["status"] = "done"
            _update_stats(download_tasks[task_id]["result"])

        threading.Thread(target=run_selected_download, daemon=True).start()
        return jsonify({"task_id": task_id})

    # ===== File Serving & ZIP =====

    @app.route("/api/files")
    def api_files():
        output = Path(app.config["OUTPUT_DIR"])
        files = []
        if output.exists():
            for f in sorted(output.rglob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.is_file() and not f.name.startswith("."):
                    files.append({
                        "name": f.name,
                        "path": str(f.relative_to(output)),
                        "size": f.stat().st_size,
                        "folder": f.parent.name if f.parent != output else "",
                    })
        return jsonify(files[:200])

    @app.route("/downloads/<path:filepath>")
    def serve_file(filepath):
        return send_from_directory(app.config["OUTPUT_DIR"], filepath, as_attachment=True)

    @app.route("/api/zip", methods=["POST"])
    def api_zip():
        """打包多个文件为 ZIP 下载"""
        data = request.get_json()
        file_paths = data.get("files", [])

        if not file_paths:
            return jsonify({"error": "No files specified"}), 400

        output = Path(app.config["OUTPUT_DIR"])
        buf = io.BytesIO()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in file_paths:
                full_path = output / fp
                if full_path.exists() and full_path.is_file():
                    zf.write(full_path, fp)

        buf.seek(0)
        timestamp = int(time.time())
        return send_file(
            buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"media_download_{timestamp}.zip",
        )

    # ===== Status & History =====

    @app.route("/api/status/<task_id>")
    def api_status(task_id):
        task = download_tasks.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)

    @app.route("/api/queue")
    def api_queue():
        tasks = sorted(download_tasks.values(), key=lambda t: t.get("created_at", 0), reverse=True)
        return jsonify(tasks[:50])

    @app.route("/api/history")
    def api_history():
        tasks = [t for t in download_tasks.values() if t["status"] in ("done", "error")]
        tasks.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        return jsonify(tasks[:100])

    # ===== Stats =====

    @app.route("/api/stats")
    def api_stats():
        with stats_lock:
            return jsonify(stats)

    def _update_stats(result):
        with stats_lock:
            stats["total_downloads"] += 1
            files = result.get("files", [])
            for f in files:
                if f.get("status") == "success":
                    stats["total_files"] += 1
                    stats["total_bytes"] += f.get("size", 0)

            platform = result.get("platform", "unknown")
            if platform not in stats["by_platform"]:
                stats["by_platform"][platform] = 0
            stats["by_platform"][platform] += 1

    # ===== Cookie Management =====

    @app.route("/api/cookies", methods=["POST"])
    def api_set_cookies():
        """导入 Cookies（用于访问私密内容）"""
        data = request.get_json()
        cookie_str = data.get("cookies", "").strip()

        if not cookie_str:
            saved_cookies.pop("global", None)
            return jsonify({"success": True, "message": "Cookies cleared"})

        cookies = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

        saved_cookies["global"] = cookies
        return jsonify({"success": True, "count": len(cookies)})

    @app.route("/api/cookies", methods=["GET"])
    def api_get_cookies():
        has_cookies = bool(saved_cookies.get("global"))
        count = len(saved_cookies.get("global", {}))
        return jsonify({"has_cookies": has_cookies, "count": count})

    # ===== Platform Detection =====

    @app.route("/api/detect", methods=["POST"])
    def api_detect():
        data = request.get_json()
        url = data.get("url", "").strip()
        platform = MediaDownloader.detect_platform(url)
        return jsonify({"platform": platform})

    return app
