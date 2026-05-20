import html
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests


DEFAULT_KEYWORDS = ["대체역심사위원회", "양심적병역거부", "여호와의증인", "대체복무", "병무청"]


class NewsCollector:
    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or os.environ.get("NAVER_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("NAVER_CLIENT_SECRET")
        self.api_url = "https://openapi.naver.com/v1/search/news.json"

    def fetch_yesterday_news(self, query=None, max_results=50):
        """
        네이버 뉴스 API를 통해 지정 키워드로 뉴스를 검색한 뒤,
        어제 하루 동안 작성된 기사만 중복 제거하여 반환합니다.
        query는 문자열 하나 또는 문자열 리스트를 받을 수 있습니다.
        """
        if not self.client_id or not self.client_secret:
            print("[오류] NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET 환경 변수가 설정되지 않았습니다.", file=sys.stderr)
            return []

        keywords = self._normalize_keywords(query or DEFAULT_KEYWORDS)
        timezone_kst = timezone(timedelta(hours=9))
        now_kst = datetime.now(timezone_kst)
        yesterday_kst = now_kst - timedelta(days=1)
        yesterday_str = yesterday_kst.strftime("%Y-%m-%d")

        print(f"[정보] 현재 시각(KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[정보] 필터링 대상 날짜: {yesterday_str}")
        print(f"[정보] 검색 키워드: {', '.join(keywords)}")

        deduped_news = {}
        for keyword in keywords:
            items = self._request_news(keyword, max_results)
            for item in items:
                normalized = self._normalize_item(item, timezone_kst, yesterday_str, keyword)
                if not normalized:
                    continue
                dedupe_key = normalized.get("originallink") or normalized.get("link") or normalized["title"]
                deduped_news.setdefault(dedupe_key, normalized)

        yesterday_news = sorted(deduped_news.values(), key=lambda item: item["pubDate"], reverse=True)
        if max_results:
            yesterday_news = yesterday_news[:max_results]

        print(f"[정보] 어제 날짜 뉴스는 중복 제거 후 총 {len(yesterday_news)}개입니다.")
        return yesterday_news

    def _request_news(self, keyword, max_results):
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }
        params = {
            "query": keyword,
            "display": min(max_results or 50, 100),
            "start": 1,
            "sort": "date",
        }

        try:
            response = requests.get(self.api_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"[오류] 네이버 뉴스 API 호출 실패 ({keyword}): {e}", file=sys.stderr)
            return []

        items = data.get("items", [])
        print(f"[정보] '{keyword}' 검색 결과 {len(items)}개 수신")
        return items

    def _normalize_item(self, item, timezone_kst, yesterday_str, keyword):
        pub_date_str = item.get("pubDate")
        if not pub_date_str:
            return None

        try:
            pub_date_dt = parsedate_to_datetime(pub_date_str)
            pub_date_kst = pub_date_dt.astimezone(timezone_kst)
        except Exception as ex:
            print(f"[경고] pubDate 파싱 실패 ({pub_date_str}): {ex}", file=sys.stderr)
            return None

        if pub_date_kst.strftime("%Y-%m-%d") != yesterday_str:
            return None

        title = self._clean_text(item.get("title", ""))
        description = self._clean_text(item.get("description", ""))
        if self._keyword_key(keyword) not in self._keyword_key(f"{title} {description}"):
            return None

        return {
            "title": title,
            "originallink": item.get("originallink"),
            "link": item.get("link"),
            "description": description,
            "pubDate": pub_date_kst.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _normalize_keywords(self, query):
        if isinstance(query, str):
            return [query]
        return [keyword for keyword in query if isinstance(keyword, str) and keyword.strip()]

    def _clean_text(self, value):
        text = html.unescape(value or "")
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    def _keyword_key(self, value):
        return re.sub(r"\s+", "", value or "").lower()


if __name__ == "__main__":
    collector = NewsCollector()
    news = collector.fetch_yesterday_news(query=DEFAULT_KEYWORDS)
    for idx, item in enumerate(news, 1):
        print(f"\n[{idx}] {item['title']}")
        print(f"일시: {item['pubDate']}")
        print(f"설명: {item['description']}")
        print(f"링크: {item['link']}")
