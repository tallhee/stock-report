# 보유/관심 ETF 설정 — 종목코드는 네이버증권에서 확인 후 필요하면 수정하세요.
HOLDINGS = [
    {"name": "KODEX 보험", "code": "140700", "sector": "보험"},
    {"name": "KODEX 증권", "code": "102970", "sector": "증권"},
    {"name": "TIGER 증권", "code": "157500", "sector": "증권"},
]

INDEXES = [
    {"name": "KOSPI", "code": "KOSPI"},
    {"name": "KOSDAQ", "code": "KOSDAQ"},
]

# 급락 기준 (%)
KOSPI_DROP = -2.0          # KOSPI 하루 하락률
HOLDING_DROP = -3.0        # 보유 ETF 하루 하락률
CONSECUTIVE_PREV = -2.0    # 전일 하락 후
CONSECUTIVE_TODAY = -1.0   # 오늘 추가 하락

# 리포트 목록에서 가져올 최대 개수
MAX_COMPANY = 40
MAX_OTHER = 12

# 업종 리포트에서 보유 업종 관련으로 표시할 키워드
SECTOR_KEYWORDS = ["보험", "증권", "금융", "은행", "금리"]

NAVER_LINKS = {
    "시황정보": "https://m.stock.naver.com/investment/research/daily",
    "투자정보": "https://m.stock.naver.com/investment/research/invest",
    "경제분석": "https://m.stock.naver.com/investment/research/economy",
    "종목분석": "https://m.stock.naver.com/investment/research/company",
    "산업분석": "https://m.stock.naver.com/investment/research/industry",
    "인포스탁데일리 리포트": "https://www.infostockdaily.co.kr/news/articleList.html?sc_section_code=S1N17",
}
