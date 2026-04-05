"""命令行接口"""

import argparse
import sys

from .downloader import MediaDownloader


def main():
    parser = argparse.ArgumentParser(
        description="Twitter/X Media Downloader - Download videos and images from Twitter"
    )
    parser.add_argument("url", nargs="?", help="Twitter/X URL or tweet ID")
    parser.add_argument("-o", "--output", default="./downloads", help="Output directory (default: ./downloads)")
    parser.add_argument("-u", "--user", action="store_true", help="Download user's media timeline")
    parser.add_argument("-c", "--count", type=int, default=20, help="Number of tweets to fetch for user timeline (default: 20)")
    parser.add_argument("--web", action="store_true", help="Launch web GUI")
    parser.add_argument("--port", type=int, default=5000, help="Web GUI port (default: 5000)")
    parser.add_argument("--no-archive", action="store_true", help="Disable download archive (allow re-downloads)")

    args = parser.parse_args()

    if args.web:
        from .web import create_app
        app = create_app(output_dir=args.output)
        print(f"\n  Twitter Media Downloader")
        print(f"  Web GUI: http://127.0.0.1:{args.port}")
        print(f"  Output:  {args.output}\n")
        app.run(host="0.0.0.0", port=args.port, debug=False)
        return

    if not args.url:
        parser.print_help()
        sys.exit(1)

    def on_progress(data):
        event = data.get("event", "")
        msg = data.get("message", "")
        if msg:
            print(f"  [{event}] {msg}")

    with MediaDownloader(
        output_dir=args.output,
        use_archive=not args.no_archive,
        progress_callback=on_progress,
    ) as dl:
        if args.user:
            result = dl.download_user_media(args.url, count=args.count)
        else:
            result = dl.download_tweet(args.url)

    if result["success"]:
        files = result.get("files", [])
        success_count = sum(1 for f in files if f["status"] == "success")
        print(f"\n  Done! {success_count}/{len(files)} files downloaded.")
    else:
        print(f"\n  Error: {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
