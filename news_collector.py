import os
import sys
import requests
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

class NewsCollector:
    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or os.environ.get("NAVER_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("NAVER_CLIENT_SECRET")
        self.api_url = "https://openapi.naver.com/v1/search/news.json"

    def fetch_yesterday_news(self, query="병무청", max_results=50):
        """
        네이버 뉴스 API를 통해 특정 키워드로 뉴스를 검색한 뒤,
        어제 하루 동안 작성된 기사만 필터링하여 반환합니다.
        """
        if not self.client_id or not self.client_secret:
            print("[오류] NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET 환경 변수가 설정되지 않았습니다.", file=sys.stderr)
            return []

        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret
        }
        
        params = {
            "query": query,
            "display": max_results,
            "start": 1,
            "sort": "date"  # 최신순 정렬
        }

        try:
            response = requests.get(self.api_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"[오류] 네이버 뉴스 API 호출 실패: {e}", file=sys.stderr)
            return []

        items = data.get("items", [])
        
        # 한국 표준시(KST, UTC+9) 기준으로 어제 날짜 계산
        timezone_kst = timezone(timedelta(hours=9))
        now_kst = datetime.now(timezone_kst)
        yesterday_kst = now_kst - timedelta(days=1)
        yesterday_str = yesterday_kst.strftime("%Y-%m-%d")
        
        print(f"[정보] 현재 시각(KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[정보] 필터링 대상 어제 날짜: {yesterday_str}")

        yesterday_news = []
        for item in items:
            pub_date_str = item.get("pubDate")
            if not pub_date_str:
                continue

            try:
                # 네이버 pubDate 포맷: 'Thu, 21 May 2026 00:01:00 +0900'
                pub_date_dt = parsedate_to_datetime(pub_date_str)
                # KST 시간대로 통일
                pub_date_kst = pub_date_dt.astimezone(timezone_kst)
                pub_date_date_str = pub_date_kst.strftime("%Y-%m-%d")
                
                # 어제 작성된 뉴스만 필터링
                if pub_date_date_str == yesterday_str:
                    yesterday_news.append({
                        "title": item.get("title").replace("<b>", "").replace("</b>", "").replace("&quot;", '"'),
                        "originallink": item.get("originallink"),
                        "link": item.get("link"),
                        "description": item.get("description").replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&apos;", "'"),
                        "pubDate": pub_date_kst.strftime("%Y-%m-%d %H:%M:%S")
                    })
            except Exception as ex:
                print(f"[경고] pubDate 파싱 실패 ({pub_date_str}): {ex}", file=sys.stderr)
                continue

        print(f"[정보] 수집된 전체 뉴스 {len(items)}개 중 어제 날짜 뉴스는 총 {len(yesterday_news)}개입니다.")
        return yesterday_news

if __name__ == "__main__":
    # 로컬 개발 및 테스트를 위한 코드
    collector = NewsCollector()
    news = collector.fetch_yesterday_news(query="병무청")
    for idx, item in enumerate(news, 1):
        print(f"\n[{idx}] {item['title']}")
        print(f"일시: {item['pubDate']}")
        print(f"설명: {item['description']}")
        print(f"링크: {item['link']}")
