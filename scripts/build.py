"""평일 증권 리포트 페이지 생성기.

사용법:
  python scripts/build.py morning   # 오전 8:50 — 리포트 요약 + 전일 급락 체크
  python scripts/build.py dip       # 오후 2:05 — 장중 급락 체크 (급락일에만 페이지 생성)
"""
import ast
import datetime as dt
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REPORTS = DOCS / "reports"
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST)
TODAY = NOW.date()
WEEKDAY = "월화수목금토일"[TODAY.weekday()]

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://finance.naver.com/",
})
STATUS = []  # 출처 접근 상태


def get(url, encoding=None):
    for attempt in range(3):
        try:
            r = S.get(url, timeout=20)
            r.raise_for_status()
            if encoding:
                r.encoding = encoding
            return r.text
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2)
    raise err


# ---------------- 시세 ----------------
def daily_prices(code, days=120):
    end = TODAY + dt.timedelta(days=1)
    start = TODAY - dt.timedelta(days=days)
    url = ("https://api.finance.naver.com/siseJson.naver?symbol={}&requestType=1"
           "&startTime={}&endTime={}&timeframe=day").format(
        code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    txt = get(url).strip()
    rows = ast.literal_eval(txt.replace("null", "None"))
    out = []
    for r in rows[1:]:
        if not r or r[4] in (None, 0):
            continue
        out.append({"date": str(r[0]).strip(), "close": float(r[4])})
    return out


def pct(a, b):
    return (a / b - 1) * 100 if b else None


def analyze(code):
    p = daily_prices(code)
    if len(p) < 2:
        return None
    closes = [x["close"] for x in p]
    last = p[-1]
    is_today = last["date"] == TODAY.strftime("%Y%m%d")
    res = {
        "last_date": last["date"], "is_today": is_today, "close": closes[-1],
        "chg": pct(closes[-1], closes[-2]),
        "prev_chg": pct(closes[-2], closes[-3]) if len(closes) > 2 else None,
        "chg_1w": pct(closes[-1], closes[-6]) if len(closes) > 5 else None,
        "ma20": sum(closes[-20:]) / min(20, len(closes)),
        "ma60": sum(closes[-60:]) / min(60, len(closes)),
        "low20": min(closes[-20:]),
        "high20": max(closes[-20:]),
    }
    res["from_high20"] = pct(res["close"], res["high20"])
    return res


def market_snapshot():
    data = {}
    for item in config.INDEXES + config.HOLDINGS:
        try:
            data[item["name"]] = analyze(item["code"])
        except Exception as e:  # noqa: BLE001
            data[item["name"]] = None
            print("시세 실패", item["name"], e)
    ok = sum(1 for v in data.values() if v)
    STATUS.append(f"시세 {ok}/{len(data)}개 확인")
    return data


def dip_reasons(snap, use_prev=False):
    """급락 조건 판정. use_prev=True면 '전 영업일' 기준."""
    key = "prev_chg" if use_prev else "chg"
    reasons = []
    k = snap.get("KOSPI")
    if k and k.get(key) is not None and k[key] <= config.KOSPI_DROP:
        reasons.append(f"KOSPI {k[key]:+.2f}%")
    for h in config.HOLDINGS:
        v = snap.get(h["name"])
        if v and v.get(key) is not None and v[key] <= config.HOLDING_DROP:
            reasons.append(f"{h['name']} {v[key]:+.2f}%")
    if not use_prev:
        for name in ["KOSPI"] + [h["name"] for h in config.HOLDINGS]:
            v = snap.get(name)
            if v and v.get("prev_chg") is not None and v.get("chg") is not None \
                    and v["prev_chg"] <= config.CONSECUTIVE_PREV and v["chg"] <= config.CONSECUTIVE_TODAY:
                reasons.append(f"{name} 연속 하락 ({v['prev_chg']:+.2f}% → {v['chg']:+.2f}%)")
    return reasons


# ---------------- 네이버 리서치 (m.stock.naver.com JSON) ----------------
API = "https://m.stock.naver.com/api/research/"


def api_json(path):
    return json.loads(get(API + path))


def strip_html(t, n=220):
    t = re.sub(r"<br\s*/?>|</p>", " ", t or "")
    t = html.unescape(html.unescape(re.sub(r"<[^>]+>", "", t))).strip('" ')
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n] + ("…" if len(t) > n else "")


def to_int(v):
    try:
        return int(str(v).replace(",", "")) if v not in (None, "", "0") else None
    except ValueError:
        return None


def fetch_kind(kind, limit, detail=True):
    rows = api_json(f"{kind}?page=1&pageSize={limit}")
    recent = {(TODAY - dt.timedelta(days=d)).isoformat() for d in range(0, 5)}
    out = []
    for r in rows:
        if r.get("writeDate") not in recent:
            continue
        item = {
            "id": r.get("researchId"), "title": r.get("title", ""), "broker": r.get("brokerName", ""),
            "date": r.get("writeDate", ""), "category": r.get("category", ""),
            "stock": r.get("itemName", ""), "code": r.get("itemCode", ""),
            "url": r.get("endUrl", ""), "pdf": "", "summary": "",
        }
        if detail:
            try:
                d = api_json(f"{kind}/{item['id']}").get("researchContent", {})
                item["pdf"] = d.get("attachUrl", "")
                item["summary"] = strip_html(d.get("content"))
                item["opinion"] = d.get("opinion") or ""
                item["target"] = to_int(d.get("goalPrice"))
                item["prev_target"] = None  # prevGoalPrice는 실제로 작성일 주가라 사용 안 함
            except Exception as e:  # noqa: BLE001
                print("상세 실패", kind, item["id"], e)
            time.sleep(0.2)
        out.append(item)
    return out


def classify(op):
    op = (op or "").lower()
    if any(k in op for k in ["buy", "매수", "outperform", "overweight", "비중확대"]):
        return "buy"
    if any(k in op for k in ["sell", "매도", "underperform", "underweight", "비중축소", "reduce"]):
        return "sell"
    if op in ("", "-", "없음", "nr", "not rated", "투자의견없음"):
        return "none"
    return "hold"


def research():
    out = {}
    try:
        comp = fetch_kind("company", config.MAX_COMPANY)
        for r in comp:
            r["close"] = None
            if r.get("code"):
                try:
                    a = analyze(r["code"])
                    r["close"] = a["close"] if a else None
                except Exception:  # noqa: BLE001
                    pass
        out["company"] = comp
        STATUS.append(f"네이버 종목분석 {len(comp)}건")
    except Exception as e:  # noqa: BLE001
        out["company"] = []
        STATUS.append(f"네이버 종목분석 실패({type(e).__name__})")
    for kind, label in [("industry", "산업분석"), ("market", "시황정보"),
                        ("invest", "투자정보"), ("economy", "경제분석")]:
        try:
            out[kind] = fetch_kind(kind, config.MAX_OTHER)
            STATUS.append(f"{label} {len(out[kind])}건")
        except Exception as e:  # noqa: BLE001
            out[kind] = []
            STATUS.append(f"{label} 실패({type(e).__name__})")
    return out


# ---------------- HTML ----------------
def e(x):
    return html.escape(str(x)) if x is not None else ""


def fmt_num(v, d=0):
    if v is None:
        return "–"
    return f"{v:,.{d}f}"


def fmt_pct(v):
    if v is None:
        return "–"
    cls = "up" if v > 0 else "down" if v < 0 else ""
    return f'<span class="{cls}">{v:+.2f}%</span>'


CSS = """
:root{--bg:#f7f6f3;--card:#fff;--ink:#1f2328;--mute:#6b7280;--line:#e5e2dc;--up:#d6336c;--down:#1c64f2;--warn:#fff4e5;--warnline:#f59f00;--accent:#0f766e}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e22;--ink:#e6e6e6;--mute:#9aa1ab;--line:#2c3036;--up:#ff6b9a;--down:#6ea8ff;--warn:#2b2214;--warnline:#f59f00;--accent:#2dd4bf}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR",sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:4px 0 2px}h2{font-size:17px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.sub{color:var(--mute);font-size:13px}.note{color:var(--mute);font-size:12.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.alert{background:var(--warn);border:1px solid var(--warnline);border-radius:10px;padding:12px 14px;margin:14px 0}
.tbl{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13.5px;white-space:nowrap}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}th{font-weight:600;color:var(--mute);font-size:12.5px;background:var(--bg)}
td.n{text-align:right;font-variant-numeric:tabular-nums}tr:last-child td{border-bottom:0}
td.t{white-space:normal;min-width:220px}
.up{color:var(--up)}.down{color:var(--down)}a{color:var(--accent)}
ul{padding-left:20px}li{margin:3px 0}
.pill{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mute)}
"""


def page(title, body):
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>{CSS}</style></head><body><main>
<p class="sub"><a href="../index.html">← 전체 목록</a></p>
{body}
<p class="note" style="margin-top:40px">본 페이지는 공개된 증권사 리포트와 시세를 자동으로 모은 것으로 투자 권유가 아니며, 투자 판단과 책임은 본인에게 있습니다.</p>
</main></body></html>"""


def table(headers, rows, num_cols=()):
    h = "".join(f"<th>{x}</th>" for x in headers)
    body = ""
    for r in rows:
        tds = ""
        for i, c in enumerate(r):
            cls = ' class="n"' if i in num_cols else (' class="t"' if headers[i] in ("제목", "근거") else "")
            tds += f"<td{cls}>{c}</td>"
        body += f"<tr>{tds}</tr>"
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="note">해당 없음</td></tr>'
    return f'<div class="tbl"><table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def link(text, url):
    return f'<a href="{e(url)}" target="_blank" rel="noopener">{e(text)}</a>' if url else e(text)


def market_table(snap):
    rows = []
    for item in config.INDEXES + config.HOLDINGS:
        v = snap.get(item["name"])
        if not v:
            rows.append([e(item["name"]), "–", "–", "–", "–", "–", "–"])
            continue
        ma_note = []
        if v["close"] < v["ma20"]:
            ma_note.append("20일선 아래")
        if v["close"] < v["ma60"]:
            ma_note.append("60일선 아래")
        rows.append([
            e(item["name"]), fmt_num(v["close"], 2 if item in config.INDEXES else 0),
            fmt_pct(v["chg"]), fmt_pct(v["chg_1w"]),
            fmt_num(v["ma20"]) + " / " + fmt_num(v["ma60"]),
            fmt_num(v["low20"]), fmt_pct(v["from_high20"]) + (" · " + ", ".join(ma_note) if ma_note else ""),
        ])
    return table(["구분", "종가(최근)", "등락", "1주", "20일선 / 60일선", "20일 최저", "20일 고점 대비"],
                 rows, num_cols=(1, 2, 3, 4, 5))


def zone_rows(snap):
    rows = []
    for h in config.HOLDINGS:
        v = snap.get(h["name"])
        if not v:
            continue
        support = sorted([v["ma20"], v["ma60"], v["low20"]])
        lo, hi = support[0], support[1]
        rows.append([e(h["name"]), fmt_num(v["close"]), fmt_num(v["ma20"]), fmt_num(v["ma60"]),
                     fmt_num(v["low20"]), f"{fmt_num(lo)} ~ {fmt_num(hi)}"])
    return table(["ETF", "현재가", "20일선", "60일선", "20일 최저", "분할매수 참고 구간(지지선 기반 참고치)"],
                 rows, num_cols=(1, 2, 3, 4, 5))


CHECK_AM = """<ul>
<li>하락 원인이 업종 자체의 악재(실적·규제)인가, 일시적 수급(외국인 매도·해외 증시)인가?</li>
<li>9:00~9:30 시초가를 보고 판단 — 갭 반등이면 서두르지 않기, 추가 급락이면 지지선 근처까지 기다리기</li>
<li>한 번에 다 사지 말고 계획 금액의 1/3 이하로 나눠서</li>
<li>연금 월 납입 한도와 보험·증권 비중 계획 안인가?</li></ul>"""
CHECK_PM = """<ul>
<li>하락 원인이 업종 자체의 악재인가, 일시적 수급인가?</li>
<li>현재가가 20일·60일선, 20일 최저 같은 지지선 근처인가?</li>
<li>오늘 사도 월 납입 한도·비중 계획 안인가? 계획 금액의 1/3 이하로 나눠서</li>
<li>15:20~15:30 동시호가는 가격이 크게 움직일 수 있으니 그 전에 결정</li>
<li>내일 아침 페이지에서 밤사이 미국 증시·환율을 다시 확인</li></ul>"""


def morning():
    snap = market_snapshot()
    res = research()
    # 장 시작 전이므로 최신 봉 = 전 영업일
    prev = dip_reasons(snap, use_prev=False)
    title = f"{TODAY:%Y-%m-%d} ({WEEKDAY}) 증권 리포트 요약"
    if prev:
        title = "🚨 " + title
    parts = [f"<h1>{e(title)}</h1><p class='sub'>생성 {NOW:%Y-%m-%d %H:%M} KST · 출처 상태: {e(' · '.join(STATUS))}</p>"]

    if prev:
        parts.append(f"<div class='alert'><b>🚨 전일 급락 — 오전 9시대 매수 체크</b><br>조건: {e(', '.join(prev))}"
                     f"{zone_rows(snap)}{CHECK_AM}</div>")

    parts.append("<h2>시장 · 내 보유 ETF</h2>" + market_table(snap))

    comp = res.get("company", [])
    buckets = {"buy": [], "hold": [], "sell": [], "none": []}
    for r in comp:
        c = classify(r.get("opinion"))
        if c != "sell" and r.get("target") and r.get("prev_target") and r["target"] < r["prev_target"]:
            buckets["sell"].append(r)   # 목표가 하향은 C에도 표시
            if c == "buy":
                continue
        buckets[c].append(r)

    def comp_rows(rs):
        out = []
        for r in rs:
            up = pct(r["target"], r["close"]) if r.get("target") and r.get("close") else None
            chg = ""
            if r.get("target") and r.get("prev_target") and r["target"] != r["prev_target"]:
                chg = ("▲ " if r["target"] > r["prev_target"] else "▼ ") + fmt_num(r["prev_target"]) + "→"
            out.append([e(r.get("stock")), e(r.get("broker")), e(r.get("opinion") or "–"),
                        e(chg) + fmt_num(r.get("target")), fmt_num(r.get("close")), fmt_pct(up),
                        link(r["title"], r["url"]) + f"<br><span class='note'>{e(r.get('summary'))}</span>",
                        link("PDF", r.get("pdf")), e(r.get("date"))])
        return out
    hdr = ["종목", "증권사", "투자의견", "목표가", "최근 종가", "상승여력", "제목", "원문", "날짜"]
    buy = sorted(buckets["buy"], key=lambda r: -(pct(r["target"], r["close"]) or -999)
                 if r.get("target") and r.get("close") else 999)
    parts.append("<h2>A. 매수 의견 종목</h2><p class='note'>상승여력 = 목표가 ÷ 최근 종가. 목표가는 보통 6~12개월 기준입니다.</p>"
                 + table(hdr, comp_rows(buy), num_cols=(3, 4, 5)))
    parts.append("<h2>B. 보유(중립) 의견 종목</h2>" + table(hdr, comp_rows(buckets["hold"]), num_cols=(3, 4, 5)))
    parts.append("<h2>C. 매도·비중축소 의견 종목</h2>" + table(hdr, comp_rows(buckets["sell"]), num_cols=(3, 4, 5)))
    if buckets["none"]:
        parts.append("<h2>기타 (의견 없음/확인 불가)</h2>" + table(hdr, comp_rows(buckets["none"]), num_cols=(3, 4, 5)))

    ind = res.get("industry", [])
    mine = [r for r in ind if any(k in r["title"] + r.get("category", "") for k in config.SECTOR_KEYWORDS)]
    parts.append("<h2>D. 산업분석 (국내 업종 ETF 참고)</h2>"
                 "<p class='note'>⭐ = 보유 업종(보험·증권·금융·금리) 관련</p>"
                 + table(["", "업종", "제목", "증권사", "원문", "날짜"],
                         [["⭐" if r in mine else "", e(r.get("category")), link(r["title"], r["url"]) + f"<br><span class='note'>{e(r.get('summary'))}</span>",
                           e(r["broker"]), link("PDF", r.get("pdf")), e(r["date"])] for r in ind]))
    for kind, label in [("market", "시황정보"), ("invest", "투자정보"), ("economy", "경제분석 (금리·환율)")]:
        rs = res.get(kind, [])
        parts.append(f"<h2>{label}</h2>" + table(["제목", "증권사", "원문", "날짜"],
                     [[link(r["title"], r["url"]) + f"<br><span class='note'>{e(r.get('summary'))}</span>", e(r["broker"]), link("PDF", r.get("pdf")), e(r["date"])] for r in rs]))

    parts.append("<h2>원문 보기</h2><ul>" + "".join(
        f"<li>{link(k, v)}</li>" for k, v in config.NAVER_LINKS.items()) + "</ul>")

    write(f"{TODAY:%Y-%m-%d}", title, "".join(parts))
    summary = {"type": "morning", "title": title, "dip": prev,
               "top_buy": [f"{r.get('stock')}({r.get('broker')})" for r in buy[:3]],
               "status": STATUS}
    return summary


def dip():
    snap = market_snapshot()
    k = snap.get("KOSPI")
    if not k or not k["is_today"]:
        print("오늘 시세 없음(휴장 또는 조회 실패) — 종료")
        return {"type": "dip", "dip": [], "status": STATUS}
    reasons = dip_reasons(snap)
    line = ", ".join(f"{n} {fmt_plain(snap.get(n))}" for n in ["KOSPI"] + [h["name"] for h in config.HOLDINGS])
    if not reasons:
        print("급락 조건 해당 없음:", line)
        return {"type": "dip", "dip": [], "line": line, "status": STATUS}
    title = f"🚨 {TODAY:%Y-%m-%d} ({WEEKDAY}) 급락 매수 체크 — 오후 2시"
    body = (f"<h1>{e(title)}</h1><p class='sub'>확인 {NOW:%H:%M} KST · 조건: {e(', '.join(reasons))}</p>"
            "<h2>오늘 하락 현황 (장중)</h2>" + market_table(snap)
            + "<h2>보유 ETF 지지선 · 분할매수 참고 구간</h2>" + zone_rows(snap)
            + "<h2>장 마감 전 체크리스트 (14:00~15:20)</h2>" + CHECK_PM
            + "<h2>원문 보기</h2><ul>" + "".join(f"<li>{link(a, b)}</li>" for a, b in config.NAVER_LINKS.items()) + "</ul>")
    write(f"{TODAY:%Y-%m-%d}-dip", title, body)
    return {"type": "dip", "title": title, "dip": reasons, "line": line, "status": STATUS}


def fmt_plain(v):
    return f"{v['chg']:+.2f}%" if v and v.get("chg") is not None else "–"


# ---------------- 저장 / 목록 ----------------
def write(slug, title, body):
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{slug}.html").write_text(page(title, body), encoding="utf-8")
    idx_path = DOCS / "index.json"
    items = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else []
    items = [i for i in items if i["slug"] != slug]
    items.append({"slug": slug, "title": title})
    items.sort(key=lambda i: i["slug"], reverse=True)
    idx_path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    lis = "".join(f'<li><a href="reports/{e(i["slug"])}.html">{e(i["title"])}</a></li>' for i in items)
    index = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>데일리 증권 리포트</title>
<style>{CSS}</style></head><body><main><h1>📈 데일리 증권 리포트</h1>
<p class="sub">평일 08:50 리포트 요약 · 급락일 14:05 매수 체크 (GitHub Actions 자동 생성)</p>
<ul>{lis}</ul><p class="note">투자 권유가 아니며, 투자 판단과 책임은 본인에게 있습니다.</p></main></body></html>"""
    (DOCS / "index.html").write_text(index, encoding="utf-8")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    result = morning() if mode == "morning" else dip()
    print(json.dumps(result, ensure_ascii=False))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"dip={'yes' if result.get('dip') else 'no'}\n")
            f.write(f"title={result.get('title', '')}\n")
            f.write(f"reasons={', '.join(result.get('dip') or [])}\n")
            f.write(f"slug={TODAY:%Y-%m-%d}{'-dip' if mode == 'dip' else ''}\n")
