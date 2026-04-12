FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl && rm -rf /var/lib/apt/lists/*

# 安装最新 yt-dlp CLI（比 pip 版本更新更快）
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/downloads

EXPOSE 8899

CMD ["python3", "main.py", "--web", "--port", "8899"]
