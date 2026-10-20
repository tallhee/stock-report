# 📈 데일리 증권 리포트 (자동)

GitHub Actions가 평일마다 자동 실행해 GitHub 페이지를 만듭니다. 노트북이나 Claude 구독이 없어도 돌아갑니다.

- **08:45 KST** — 네이버페이증권 리서치(종목·산업·시황·투자·경제) 목록 + 목표가/투자의견 + 상승여력, 보유 ETF 등락, 전일 급락 시 🚨 오전 9시대 매수 체크
- **14:00 KST** — 장중 급락 체크. 급락 조건이면 🚨 페이지 생성 + GitHub 이슈로 알림

페이지: https://tallhee.github.io/stock-report/

## 설정 바꾸기
`scripts/config.py`에서 보유 ETF 종목코드, 급락 기준(%)을 수정하세요.

## 수동 실행
Actions 탭 → "데일리 증권 리포트" → Run workflow → mode에 `morning` 또는 `dip`

> 공개 자료 자동 수집이며 투자 권유가 아닙니다.
