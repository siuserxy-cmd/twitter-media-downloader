from setuptools import setup, find_packages

setup(
    name="twitter-media-downloader",
    version="1.0.0",
    description="Twitter/X Media Downloader - Download videos and images from Twitter",
    author="siuserxy-cmd",
    packages=find_packages(),
    install_requires=[
        "yt-dlp>=2024.01.01",
        "flask>=3.0.0",
        "requests>=2.31.0",
        "httpx>=0.27.0",
        "beautifulsoup4>=4.12.0",
    ],
    entry_points={
        "console_scripts": [
            "twitter-dl=twitter_downloader.cli:main",
        ],
    },
    python_requires=">=3.8",
)
