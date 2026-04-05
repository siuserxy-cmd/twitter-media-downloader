"""Web GUI 界面 (Flask)"""

import os
import json
import threading
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory

from .downloader import MediaDownloader


# 全局下载状态
download_tasks = {}
task_counter = 0
task_lock = threading.Lock()


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
        global task_counter
        data = request.get_json()
        url = data.get("url", "").strip()
        mode = data.get("mode", "tweet")  # "tweet" or "user"
        count = data.get("count", 20)

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
        }

        def run_download():
            logs = download_tasks[task_id]["logs"]

            def on_progress(data):
                logs.append(data)

            try:
                with MediaDownloader(
                    output_dir=app.config["OUTPUT_DIR"],
                    progress_callback=on_progress,
                ) as dl:
                    if mode == "user":
                        result = dl.download_user_media(url, count=count)
                    else:
                        result = dl.download_tweet(url)

                download_tasks[task_id]["result"] = result
                download_tasks[task_id]["status"] = "done" if result.get("success") else "error"
            except Exception as e:
                download_tasks[task_id]["status"] = "error"
                download_tasks[task_id]["result"] = {"success": False, "error": str(e), "files": []}

        thread = threading.Thread(target=run_download, daemon=True)
        thread.start()

        return jsonify({"task_id": task_id})

    @app.route("/api/status/<task_id>")
    def api_status(task_id):
        task = download_tasks.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)

    @app.route("/api/files")
    def api_files():
        """列出已下载的文件"""
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
