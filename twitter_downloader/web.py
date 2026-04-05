"""Web GUI 界面 (Flask) - 支持多平台、批量下载、队列管理"""

import os
import json
import time
import threading
from pathlib import Path
from collections import deque

from flask import Flask, render_template, request, jsonify, send_from_directory

from .downloader import MediaDownloader


# 全局下载状态
download_tasks = {}
task_counter = 0
task_lock = threading.Lock()

# 下载队列
download_queue = deque()
queue_running = False
MAX_CONCURRENT = 2


def create_app(output_dir: str = "./downloads"):
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "templates", "static"),
    )
    app.config["OUTPUT_DIR"] = output_dir

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/download", methods=["POST"])
    def api_download():
        """单条下载"""
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
        }

        def run_download():
            logs = download_tasks[task_id]["logs"]

            def on_progress(data):
                logs.append(data)

            try:
                with MediaDownloader(
                    output_dir=app.config["OUTPUT_DIR"],
                    progress_callback=on_progress,
                    quality=quality,
                ) as dl:
                    if mode == "user":
                        result = dl.download_user_media(url, count=count)
                    else:
                        result = dl.download_media(url)

                download_tasks[task_id]["result"] = result
                download_tasks[task_id]["status"] = "done" if result.get("success") else "error"
            except Exception as e:
                download_tasks[task_id]["status"] = "error"
                download_tasks[task_id]["result"] = {"success": False, "error": str(e), "files": []}

        thread = threading.Thread(target=run_download, daemon=True)
        thread.start()

        return jsonify({"task_id": task_id})

    @app.route("/api/batch", methods=["POST"])
    def api_batch():
        """批量下载 - 多个链接加入队列"""
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
            }
            task_ids.append(task_id)
            download_queue.append((task_id, url, quality))

        # 启动队列处理器
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
                # 清理已完成的线程
                active_threads = [t for t in active_threads if t.is_alive()]

                # 启动新任务
                while download_queue and len(active_threads) < MAX_CONCURRENT:
                    task_id, url, quality = download_queue.popleft()
                    download_tasks[task_id]["status"] = "running"

                    def run(tid=task_id, u=url, q=quality):
                        logs = download_tasks[tid]["logs"]

                        def on_progress(data):
                            logs.append(data)

                        try:
                            with MediaDownloader(
                                output_dir=output_dir,
                                progress_callback=on_progress,
                                quality=q,
                            ) as dl:
                                result = dl.download_media(u)

                            download_tasks[tid]["result"] = result
                            download_tasks[tid]["status"] = "done" if result.get("success") else "error"
                        except Exception as e:
                            download_tasks[tid]["status"] = "error"
                            download_tasks[tid]["result"] = {"success": False, "error": str(e), "files": []}

                    t = threading.Thread(target=run, daemon=True)
                    t.start()
                    active_threads.append(t)

                time.sleep(0.5)

            queue_running = False

        threading.Thread(target=process_queue, daemon=True).start()

    @app.route("/api/status/<task_id>")
    def api_status(task_id):
        task = download_tasks.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)

    @app.route("/api/queue")
    def api_queue():
        """获取所有任务状态"""
        tasks = sorted(download_tasks.values(), key=lambda t: t.get("created_at", 0), reverse=True)
        return jsonify(tasks[:50])

    @app.route("/api/history")
    def api_history():
        """下载历史"""
        tasks = [
            t for t in download_tasks.values()
            if t["status"] in ("done", "error")
        ]
        tasks.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        return jsonify(tasks[:100])

    @app.route("/api/detect", methods=["POST"])
    def api_detect():
        """检测链接平台"""
        data = request.get_json()
        url = data.get("url", "").strip()
        platform = MediaDownloader.detect_platform(url)
        return jsonify({"platform": platform})

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
        return jsonify(files[:100])

    @app.route("/downloads/<path:filepath>")
    def serve_file(filepath):
        return send_from_directory(app.config["OUTPUT_DIR"], filepath)

    return app
