# Twitter Media Downloader

Download videos and images from Twitter/X with ease.

Combines the best of three open-source projects:
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** - Best-in-class video downloading engine
- **[gallery-dl](https://github.com/mikf/gallery-dl)** - Image batch download & archive system
- **[twscrape](https://github.com/vladkens/twscrape)** - Twitter GraphQL API data layer

## Features

- Download images (original quality, 4K) and videos from tweets
- Batch download user's media timeline
- Web GUI with real-time progress
- CLI for automation and scripting
- Smart archive to skip already-downloaded files
- Multiple fallback methods (Syndication API -> GraphQL -> yt-dlp)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# CLI: Download a tweet
python main.py "https://x.com/user/status/123456789"

# CLI: Download user's media
python main.py -u "@username" -c 50

# Web GUI
python main.py --web
# Then open http://127.0.0.1:5000
```

## CLI Usage

```
usage: python main.py [-h] [-o OUTPUT] [-u] [-c COUNT] [--web] [--port PORT] [--no-archive] [url]

positional arguments:
  url                   Twitter/X URL or tweet ID

optional arguments:
  -o, --output          Output directory (default: ./downloads)
  -u, --user            Download user's media timeline
  -c, --count           Number of tweets to fetch (default: 20)
  --web                 Launch web GUI
  --port                Web GUI port (default: 5000)
  --no-archive          Disable download archive
```

## Install as CLI tool

```bash
pip install -e .
twitter-dl "https://x.com/user/status/123456789"
twitter-dl --web
```

## How It Works

1. **Data Layer** (twscrape-inspired): Fetches tweet metadata via Twitter's Syndication API and GraphQL endpoints
2. **Image Download** (gallery-dl-inspired): Direct HTTP download with archive tracking and deduplication
3. **Video Download** (yt-dlp-powered): Uses yt-dlp as the video download engine with format selection
4. **Smart Fallback**: If one method fails, automatically tries the next

## License

MIT
