"""
Twitter/X 数据抓取层 (灵感来源: twscrape)
通过 Twitter 的 GraphQL API 和 syndication API 获取推文数据和媒体 URL
"""

import re
import json
import time
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx


# Twitter Bearer Token (公开的 guest token 机制)
BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

# GraphQL 端点
GRAPHQL_TWEET_DETAIL = "https://api.twitter.com/graphql/xOhkmRac04YFZmOzU9PJHg/TweetResultByRestId"
GRAPHQL_USER_TWEETS = "https://api.twitter.com/graphql/V7H0Ap3_Hh2FyS75OCDO3Q/UserTweets"
GRAPHQL_USER_MEDIA = "https://api.twitter.com/graphql/oMVVrI5kt3kOpyHHTTKf5Q/UserMedia"
GRAPHQL_USER_BY_SCREEN_NAME = "https://api.twitter.com/graphql/G3KGOASz96M-Qu0nwmGXNg/UserByScreenName"

# Syndication API (无需认证，更稳定)
SYNDICATION_API = "https://cdn.syndication.twimg.com/tweet-result"


@dataclass
class MediaItem:
    """媒体项"""
    url: str
    type: str  # "image" | "video" | "gif"
    width: int = 0
    height: int = 0
    bitrate: int = 0
    duration_ms: int = 0
    thumb_url: str = ""


@dataclass
class TweetData:
    """推文数据"""
    tweet_id: str
    user_name: str = ""
    user_screen_name: str = ""
    text: str = ""
    created_at: str = ""
    media: list = field(default_factory=list)
    reply_count: int = 0
    retweet_count: int = 0
    like_count: int = 0


class TwitterScraper:
    """Twitter 数据抓取器"""

    def __init__(self, cookies: Optional[dict] = None):
        self.cookies = cookies or {}
        self.guest_token = None
        self.guest_token_time = 0
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def _get_guest_token(self) -> str:
        """获取 guest token"""
        now = time.time()
        if self.guest_token and (now - self.guest_token_time) < 7200:
            return self.guest_token

        resp = self.client.post(
            "https://api.twitter.com/1.1/guest/activate.json",
            headers={"Authorization": f"Bearer {BEARER_TOKEN}"},
        )
        resp.raise_for_status()
        self.guest_token = resp.json()["guest_token"]
        self.guest_token_time = now
        return self.guest_token

    def _graphql_headers(self) -> dict:
        """构建 GraphQL 请求头"""
        headers = {
            "Authorization": f"Bearer {BEARER_TOKEN}",
            "Content-Type": "application/json",
        }
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            if "ct0" in self.cookies:
                headers["X-Csrf-Token"] = self.cookies["ct0"]
        else:
            headers["X-Guest-Token"] = self._get_guest_token()
        return headers

    @staticmethod
    def extract_tweet_id(url: str) -> Optional[str]:
        """从 URL 中提取推文 ID"""
        patterns = [
            r"(?:twitter\.com|x\.com)/\w+/status/(\d+)",
            r"(?:t\.co|twitter\.com)/i/web/status/(\d+)",
            r"^(\d{10,})$",  # 纯数字 ID
        ]
        for pattern in patterns:
            match = re.search(pattern, url.strip())
            if match:
                return match.group(1)
        return None

    @staticmethod
    def extract_username(url: str) -> Optional[str]:
        """从 URL 中提取用户名"""
        match = re.search(r"(?:twitter\.com|x\.com)/(@?\w+)/?$", url.strip())
        if match:
            name = match.group(1)
            return name.lstrip("@")
        return None

    def get_tweet_via_syndication(self, tweet_id: str) -> Optional[TweetData]:
        """通过 syndication API 获取推文（无需认证，最稳定）"""
        try:
            token = hashlib.md5(tweet_id.encode()).hexdigest()[:12]
            resp = self.client.get(
                SYNDICATION_API,
                params={
                    "id": tweet_id,
                    "lang": "en",
                    "token": token,
                },
                headers={
                    "Referer": "https://platform.twitter.com/",
                    "Origin": "https://platform.twitter.com",
                },
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            return self._parse_syndication_tweet(data)
        except Exception:
            return None

    def get_tweet_via_graphql(self, tweet_id: str) -> Optional[TweetData]:
        """通过 GraphQL API 获取推文详情"""
        variables = {
            "tweetId": tweet_id,
            "withCommunity": False,
            "includePromotedContent": False,
            "withVoice": False,
        }
        features = {
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "premium_content_api_read_enabled": False,
            "tweetypie_unmention_optimization_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "responsive_web_home_pinned_timelines_enabled": True,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }

        try:
            resp = self.client.get(
                GRAPHQL_TWEET_DETAIL,
                params={
                    "variables": json.dumps(variables),
                    "features": json.dumps(features),
                },
                headers=self._graphql_headers(),
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            result = data.get("data", {}).get("tweetResult", {}).get("result", {})
            return self._parse_graphql_tweet(result)
        except Exception:
            return None

    def get_tweet(self, tweet_id: str) -> Optional[TweetData]:
        """获取推文数据，自动尝试多种方式"""
        # 先尝试 syndication（不需要认证）
        tweet = self.get_tweet_via_syndication(tweet_id)
        if tweet and tweet.media:
            return tweet

        # 再尝试 GraphQL
        tweet = self.get_tweet_via_graphql(tweet_id)
        if tweet:
            return tweet

        return None

    def get_user_id(self, screen_name: str) -> Optional[str]:
        """获取用户 ID"""
        variables = {
            "screen_name": screen_name,
            "withSafetyModeUserFields": True,
        }
        features = {
            "hidden_profile_subscriptions_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        }

        try:
            resp = self.client.get(
                GRAPHQL_USER_BY_SCREEN_NAME,
                params={
                    "variables": json.dumps(variables),
                    "features": json.dumps(features),
                },
                headers=self._graphql_headers(),
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            return data["data"]["user"]["result"]["rest_id"]
        except Exception:
            return None

    def get_user_media(self, screen_name: str, count: int = 20) -> list:
        """获取用户媒体时间线"""
        user_id = self.get_user_id(screen_name)
        if not user_id:
            return []

        variables = {
            "userId": user_id,
            "count": count,
            "includePromotedContent": False,
            "withClientEventToken": False,
            "withBirdwatchNotes": False,
            "withVoice": True,
            "withV2Timeline": True,
        }
        features = {
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "tweetypie_unmention_optimization_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }

        try:
            resp = self.client.get(
                GRAPHQL_USER_MEDIA,
                params={
                    "variables": json.dumps(variables),
                    "features": json.dumps(features),
                },
                headers=self._graphql_headers(),
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            tweets = []
            timeline = data.get("data", {}).get("user", {}).get("result", {}).get("timeline_v2", {}).get("timeline", {})
            instructions = timeline.get("instructions", [])

            for instruction in instructions:
                entries = instruction.get("entries", [])
                for entry in entries:
                    content = entry.get("content", {})
                    items = content.get("items", [])
                    # 单条推文
                    tweet_result = (
                        content.get("itemContent", {})
                        .get("tweet_results", {})
                        .get("result", {})
                    )
                    if tweet_result:
                        tweet = self._parse_graphql_tweet(tweet_result)
                        if tweet and tweet.media:
                            tweets.append(tweet)
                    # 多条推文（模块）
                    for item in items:
                        tweet_result = (
                            item.get("item", {})
                            .get("itemContent", {})
                            .get("tweet_results", {})
                            .get("result", {})
                        )
                        if tweet_result:
                            tweet = self._parse_graphql_tweet(tweet_result)
                            if tweet and tweet.media:
                                tweets.append(tweet)

            return tweets
        except Exception:
            return []

    def _parse_syndication_tweet(self, data: dict) -> Optional[TweetData]:
        """解析 syndication API 返回的推文数据"""
        try:
            tweet = TweetData(
                tweet_id=str(data.get("id_str", data.get("id", ""))),
                text=data.get("text", ""),
                created_at=data.get("created_at", ""),
            )

            user = data.get("user", {})
            tweet.user_name = user.get("name", "")
            tweet.user_screen_name = user.get("screen_name", "")

            # 解析媒体
            media_details = data.get("mediaDetails", [])
            for media in media_details:
                media_type = media.get("type", "")

                if media_type == "photo":
                    url = media.get("media_url_https", "")
                    if url:
                        # 获取最高质量
                        tweet.media.append(MediaItem(
                            url=f"{url}?format=jpg&name=4096x4096",
                            type="image",
                            width=media.get("original_info", {}).get("width", 0),
                            height=media.get("original_info", {}).get("height", 0),
                            thumb_url=f"{url}?format=jpg&name=small",
                        ))

                elif media_type == "video" or media_type == "animated_gif":
                    variants = media.get("video_info", {}).get("variants", [])
                    # 选择最高码率的 mp4
                    best = self._select_best_video(variants)
                    if best:
                        tweet.media.append(MediaItem(
                            url=best["url"],
                            type="gif" if media_type == "animated_gif" else "video",
                            bitrate=best.get("bitrate", 0),
                            duration_ms=media.get("video_info", {}).get("duration_millis", 0),
                            width=media.get("original_info", {}).get("width", 0),
                            height=media.get("original_info", {}).get("height", 0),
                            thumb_url=media.get("media_url_https", ""),
                        ))

            return tweet
        except Exception:
            return None

    def _parse_graphql_tweet(self, result: dict) -> Optional[TweetData]:
        """解析 GraphQL API 返回的推文数据"""
        try:
            # 处理可能的嵌套
            if result.get("__typename") == "TweetWithVisibilityResults":
                result = result.get("tweet", result)

            legacy = result.get("legacy", {})
            core = result.get("core", {}).get("user_results", {}).get("result", {})
            user_legacy = core.get("legacy", {})

            tweet = TweetData(
                tweet_id=legacy.get("id_str", result.get("rest_id", "")),
                text=legacy.get("full_text", ""),
                created_at=legacy.get("created_at", ""),
                user_name=user_legacy.get("name", ""),
                user_screen_name=user_legacy.get("screen_name", ""),
                reply_count=legacy.get("reply_count", 0),
                retweet_count=legacy.get("retweet_count", 0),
                like_count=legacy.get("favorite_count", 0),
            )

            # 解析媒体
            extended = legacy.get("extended_entities", {})
            media_list = extended.get("media", legacy.get("entities", {}).get("media", []))

            for media in media_list:
                media_type = media.get("type", "")

                if media_type == "photo":
                    url = media.get("media_url_https", "")
                    if url:
                        tweet.media.append(MediaItem(
                            url=f"{url}?format=jpg&name=4096x4096",
                            type="image",
                            width=media.get("original_info", {}).get("width", 0),
                            height=media.get("original_info", {}).get("height", 0),
                            thumb_url=f"{url}?format=jpg&name=small",
                        ))

                elif media_type in ("video", "animated_gif"):
                    variants = media.get("video_info", {}).get("variants", [])
                    best = self._select_best_video(variants)
                    if best:
                        tweet.media.append(MediaItem(
                            url=best["url"],
                            type="gif" if media_type == "animated_gif" else "video",
                            bitrate=best.get("bitrate", 0),
                            duration_ms=media.get("video_info", {}).get("duration_millis", 0),
                            width=media.get("original_info", {}).get("width", 0),
                            height=media.get("original_info", {}).get("height", 0),
                            thumb_url=media.get("media_url_https", ""),
                        ))

            return tweet
        except Exception:
            return None

    @staticmethod
    def _select_best_video(variants: list) -> Optional[dict]:
        """选择最高质量的视频变体"""
        mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
        if not mp4_variants:
            return variants[0] if variants else None
        return max(mp4_variants, key=lambda v: v.get("bitrate", 0))

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
