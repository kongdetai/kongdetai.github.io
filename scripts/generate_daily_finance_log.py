#!/usr/bin/env python3
"""Generate a daily finance log post for the GitHub Pages site.

The script uses the zhengxi-views skill as the research framework source and
public quote endpoints as market inputs. It is intentionally dependency-free so
GitHub Actions can run it on a stock Python runner.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".claude" / "skills" / "zhengxi-views"
POSTS_DIR = ROOT / "_posts"
TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass(frozen=True)
class Instrument:
    name: str
    code: str
    kind: str
    eastmoney_secid: str
    tencent_symbol: str
    sina_symbol: str
    xueqiu_symbol: str
    zhengxi_angle: str
    core_risk: str
    base_score: int


INSTRUMENTS = [
    Instrument(
        name="润泽科技",
        code="300442",
        kind="个股",
        eastmoney_secid="0.300442",
        tencent_symbol="sz300442",
        sina_symbol="sz300442",
        xueqiu_symbol="SZ300442",
        zhengxi_angle="AI 算力基础设施与数据中心需求，核心看全球 AI Capex 是否继续外溢到国内算力/机柜/电力配套。",
        core_risk="订单兑现、资本开支强度、应收与现金流、估值对成长兑现速度的敏感性。",
        base_score=76,
    ),
    Instrument(
        name="科创50ETF",
        code="588000",
        kind="ETF",
        eastmoney_secid="1.588000",
        tencent_symbol="sh588000",
        sina_symbol="sh588000",
        xueqiu_symbol="SH588000",
        zhengxi_angle="半导体、AI、硬科技的高弹性组合工具，适合观察技术周期和国产替代景气度。",
        core_risk="ETF 被动持有导致结构分化被摊薄，若硬科技景气不共振，指数弹性会弱于优质个股。",
        base_score=68,
    ),
    Instrument(
        name="创业板ETF",
        code="159915",
        kind="ETF",
        eastmoney_secid="0.159915",
        tencent_symbol="sz159915",
        sina_symbol="sz159915",
        xueqiu_symbol="SZ159915",
        zhengxi_angle="新能源、医药、成长制造的宽基成长 Beta，重点看产业周期能否从分化转为共振。",
        core_risk="权重行业较分散，部分成熟赛道 ROE 已不低，可能不如单一高景气方向契合郑希的低 ROE 弹性偏好。",
        base_score=61,
    ),
    Instrument(
        name="赛力斯",
        code="601127",
        kind="个股",
        eastmoney_secid="1.601127",
        tencent_symbol="sh601127",
        sina_symbol="sh601127",
        xueqiu_symbol="SH601127",
        zhengxi_angle="智能电动车和智能座舱/智驾产业链，核心看车型周期、品牌势能与供应链利润分配。",
        core_risk="汽车行业竞争激烈，价格战、销量结构、渠道库存和盈利质量会快速改变市场预期。",
        base_score=66,
    ),
    Instrument(
        name="比亚迪",
        code="002594",
        kind="个股",
        eastmoney_secid="0.002594",
        tencent_symbol="sz002594",
        sina_symbol="sz002594",
        xueqiu_symbol="SZ002594",
        zhengxi_angle="新能源车、电池、出海与制造优势的综合体，具备中国比较优势和全球竞争维度。",
        core_risk="体量较大后弹性下降，估值更依赖海外增长、单车利润和技术迭代能否继续超预期。",
        base_score=70,
    ),
]

INDEXES = [
    ("上证指数", "1.000001"),
    ("深证成指", "0.399001"),
    ("创业板指", "0.399006"),
    ("科创50", "1.000688"),
]


def request_text(url: str, headers: dict[str, str] | None = None, timeout: int = 12) -> str:
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)
    req = Request(url, headers=merged_headers)
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            return raw.decode(charset)
        except UnicodeDecodeError:
            return raw.decode("gbk", errors="ignore")


def safe_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(number):
        return number
    return None


def fmt_num(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}{suffix}"


def fmt_amount(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f} 亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.2f} 万"
    return f"{value:.0f}"


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    match = re.search(r"\((\{.*\})\)\s*;?$", text, re.S)
    if match:
        return json.loads(match.group(1))
    raise ValueError("response is not JSON/JSONP")


def fetch_eastmoney(secids: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
    fields = ",".join(
        [
            "f2",
            "f3",
            "f4",
            "f5",
            "f6",
            "f12",
            "f14",
            "f15",
            "f16",
            "f17",
            "f18",
            "f20",
            "f21",
            "f22",
            "f23",
            "f24",
            "f25",
            "f62",
            "f115",
        ]
    )
    url = (
        "https://push2.eastmoney.com/api/qt/ulist/get"
        f"?fltt=2&secids={','.join(secids)}&fields={fields}"
    )
    try:
        payload = extract_json(request_text(url, headers={"Referer": "https://quote.eastmoney.com/"}))
        items = payload.get("data", {}).get("diff") or []
        quotes: dict[str, dict[str, Any]] = {}
        for item in items:
            code = str(item.get("f12", ""))
            quotes[code] = {
                "source": "东方财富",
                "name": item.get("f14"),
                "code": code,
                "price": safe_float(item.get("f2")),
                "pct": safe_float(item.get("f3")),
                "change": safe_float(item.get("f4")),
                "volume": safe_float(item.get("f5")),
                "amount": safe_float(item.get("f6")),
                "high": safe_float(item.get("f15")),
                "low": safe_float(item.get("f16")),
                "open": safe_float(item.get("f17")),
                "prev_close": safe_float(item.get("f18")),
                "market_cap": safe_float(item.get("f20")),
                "float_market_cap": safe_float(item.get("f21")),
                "speed": safe_float(item.get("f22")),
                "pb": safe_float(item.get("f23")),
                "pct_60d": safe_float(item.get("f24")),
                "pct_ytd": safe_float(item.get("f25")),
                "main_net_inflow": safe_float(item.get("f62")),
                "pe": safe_float(item.get("f115")),
            }
        return quotes, "ok"
    except Exception as exc:  # noqa: BLE001 - keep scheduled job resilient
        return {}, f"failed: {exc}"


def fetch_tencent(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    try:
        text = request_text(
            url,
            headers={"Referer": "https://gu.qq.com/"},
        )
        quotes: dict[str, dict[str, Any]] = {}
        for line in text.splitlines():
            match = re.match(r'v_([a-z]{2})(\d+)="(.*)";', line.strip())
            if not match:
                continue
            code = match.group(2)
            parts = match.group(3).split("~")
            quotes[code] = {
                "source": "腾讯股票",
                "name": parts[1] if len(parts) > 1 else None,
                "code": code,
                "price": safe_float(parts[3] if len(parts) > 3 else None),
                "prev_close": safe_float(parts[4] if len(parts) > 4 else None),
                "open": safe_float(parts[5] if len(parts) > 5 else None),
                "volume": safe_float(parts[6] if len(parts) > 6 else None),
                "amount": safe_float(parts[37] if len(parts) > 37 else None),
                "pct": safe_float(parts[32] if len(parts) > 32 else None),
                "high": safe_float(parts[33] if len(parts) > 33 else None),
                "low": safe_float(parts[34] if len(parts) > 34 else None),
            }
        return quotes, "ok"
    except Exception as exc:  # noqa: BLE001
        return {}, f"failed: {exc}"


def fetch_sina(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    try:
        text = request_text(
            url,
            headers={
                "Referer": "https://finance.sina.com.cn/",
                "Accept": "*/*",
            },
        )
        quotes: dict[str, dict[str, Any]] = {}
        for line in text.splitlines():
            match = re.match(r'var hq_str_([a-z]{2})(\d+)="(.*)";', line.strip())
            if not match:
                continue
            code = match.group(2)
            parts = match.group(3).split(",")
            quotes[code] = {
                "source": "新浪财经",
                "name": parts[0] if len(parts) > 0 else None,
                "code": code,
                "open": safe_float(parts[1] if len(parts) > 1 else None),
                "prev_close": safe_float(parts[2] if len(parts) > 2 else None),
                "price": safe_float(parts[3] if len(parts) > 3 else None),
                "high": safe_float(parts[4] if len(parts) > 4 else None),
                "low": safe_float(parts[5] if len(parts) > 5 else None),
                "volume": safe_float(parts[8] if len(parts) > 8 else None),
                "amount": safe_float(parts[9] if len(parts) > 9 else None),
            }
            price = quotes[code]["price"]
            prev_close = quotes[code]["prev_close"]
            if price is not None and prev_close:
                quotes[code]["pct"] = (price - prev_close) / prev_close * 100
        return quotes, "ok"
    except Exception as exc:  # noqa: BLE001
        return {}, f"failed: {exc}"


def fetch_xueqiu(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
    # Xueqiu often requires a fresh cookie. Try a warm-up request first and keep
    # the result optional so the daily job does not fail when access is denied.
    try:
        warm_req = Request("https://xueqiu.com/", headers={"User-Agent": USER_AGENT})
        with urlopen(warm_req, timeout=10) as response:
            cookies = response.headers.get_all("Set-Cookie") or []
        cookie_header = "; ".join(cookie.split(";", 1)[0] for cookie in cookies)
        url = (
            "https://stock.xueqiu.com/v5/stock/batch/quote.json"
            f"?symbol={quote(','.join(symbols), safe=',')}"
        )
        payload = extract_json(
            request_text(
                url,
                headers={
                    "Referer": "https://xueqiu.com/",
                    "Cookie": cookie_header,
                },
            )
        )
        quotes: dict[str, dict[str, Any]] = {}
        for item in payload.get("data", {}).get("items", []):
            quote_data = item.get("quote") or {}
            symbol = str(quote_data.get("symbol", ""))
            code = symbol[-6:]
            quotes[code] = {
                "source": "雪球",
                "name": quote_data.get("name"),
                "code": code,
                "price": safe_float(quote_data.get("current")),
                "pct": safe_float(quote_data.get("percent")),
                "change": safe_float(quote_data.get("chg")),
                "volume": safe_float(quote_data.get("volume")),
                "amount": safe_float(quote_data.get("amount")),
                "high": safe_float(quote_data.get("high")),
                "low": safe_float(quote_data.get("low")),
                "market_cap": safe_float(quote_data.get("market_capital")),
            }
        return quotes, "ok"
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return {}, f"unavailable: {exc}"
    except Exception as exc:  # noqa: BLE001
        return {}, f"failed: {exc}"


def merge_quotes(
    instruments: list[Instrument],
    eastmoney: dict[str, dict[str, Any]],
    tencent: dict[str, dict[str, Any]],
    sina: dict[str, dict[str, Any]],
    xueqiu: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for instrument in instruments:
        code = instrument.code
        quote_data: dict[str, Any] = {"code": code, "name": instrument.name, "kind": instrument.kind}
        for source in (xueqiu, sina, tencent, eastmoney):
            for key, value in source.get(code, {}).items():
                if quote_data.get(key) is None and value is not None:
                    quote_data[key] = value
        quote_data["sources"] = [
            source_name
            for source_name, source in [
                ("东方财富", eastmoney),
                ("腾讯股票", tencent),
                ("新浪财经", sina),
                ("雪球", xueqiu),
            ]
            if code in source
        ]
        merged[code] = quote_data
    return merged


def price_band(quote_data: dict[str, Any], kind: str) -> tuple[str, str]:
    price = safe_float(quote_data.get("price"))
    if price is None:
        return "N/A", "行情缺失，暂不生成价格区间"
    pct = abs(safe_float(quote_data.get("pct")) or 0.0) / 100
    if kind == "ETF":
        band = min(0.04, max(0.012, pct * 1.2))
    else:
        band = min(0.08, max(0.025, pct * 1.5))
    lower = price * (1 - band)
    upper = price * (1 + band)
    label = f"{lower:.3f} - {upper:.3f}" if kind == "ETF" else f"{lower:.2f} - {upper:.2f}"
    note = "下一交易日观察区间，按当日波动率估算，不是目标价或收益承诺"
    return label, note


def market_state(pct: float | None) -> str:
    if pct is None:
        return "数据不足"
    if pct >= 2:
        return "强势"
    if pct <= -2:
        return "承压"
    return "震荡"


def suggestion(instrument: Instrument, quote_data: dict[str, Any]) -> str:
    pct = safe_float(quote_data.get("pct"))
    state = market_state(pct)
    if state == "强势":
        return "不宜只因单日上涨追高，重点验证量能、订单/景气线索与后续资金承接。"
    if state == "承压":
        return "先看下跌是否来自底层逻辑变化；若只是交易拥挤回落，可把价格区间下沿作为观察点。"
    if instrument.kind == "ETF":
        return "适合作为景气方向的观察仓位工具，等待指数与权重行业形成共振后再提高结论强度。"
    return "维持跟踪，优先等待基本面催化、成交活跃度和市场预期改善三者同向。"


def score_label(score: int) -> str:
    if score >= 75:
        return "较契合"
    if score >= 65:
        return "中等契合"
    if score >= 55:
        return "观察型契合"
    return "低契合"


def adjusted_score(instrument: Instrument, quote_data: dict[str, Any]) -> int:
    score = instrument.base_score
    pct = safe_float(quote_data.get("pct"))
    amount = safe_float(quote_data.get("amount"))
    if pct is not None:
        if pct > 3:
            score += 2
        elif pct < -3:
            score -= 3
    if amount is not None and amount > 1_000_000_000:
        score += 2
    return max(0, min(100, score))


def load_method_quote() -> str:
    method_file = SKILL_DIR / "references" / "method.md"
    if not method_file.exists():
        return "skill references missing"
    text = method_file.read_text(encoding="utf-8")
    matches = re.findall(r'> "([^"]+)"', text)
    selected = matches[:2]
    return "\n".join(f"> {line}" for line in selected)


def build_source_status(statuses: dict[str, str]) -> str:
    rows = ["| 数据源 | 状态 |", "|---|---|"]
    for source, status in statuses.items():
        rows.append(f"| {source} | {status} |")
    return "\n".join(rows)


def build_market_table(index_quotes: dict[str, dict[str, Any]]) -> str:
    rows = ["| 指数 | 最新 | 涨跌幅 | 成交额 | 状态 |", "|---|---:|---:|---:|---|"]
    for name, secid in INDEXES:
        code = secid.split(".")[-1]
        quote_data = index_quotes.get(code, {})
        pct = safe_float(quote_data.get("pct"))
        rows.append(
            "| {name} | {price} | {pct} | {amount} | {state} |".format(
                name=name,
                price=fmt_num(safe_float(quote_data.get("price"))),
                pct=fmt_num(pct, suffix="%"),
                amount=fmt_amount(safe_float(quote_data.get("amount"))),
                state=market_state(pct),
            )
        )
    return "\n".join(rows)


def build_instrument_table(instruments: list[Instrument], quotes: dict[str, dict[str, Any]]) -> str:
    rows = [
        "| 标的 | 类型 | 最新 | 涨跌幅 | 日内高低 | 市场预期价格 | 来源 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for instrument in instruments:
        quote_data = quotes.get(instrument.code, {})
        band, _ = price_band(quote_data, instrument.kind)
        rows.append(
            "| {name} | {kind} | {price} | {pct} | {low}/{high} | {band} | {sources} |".format(
                name=instrument.name,
                kind=instrument.kind,
                price=fmt_num(safe_float(quote_data.get("price")), 3 if instrument.kind == "ETF" else 2),
                pct=fmt_num(safe_float(quote_data.get("pct")), suffix="%"),
                low=fmt_num(safe_float(quote_data.get("low")), 3 if instrument.kind == "ETF" else 2),
                high=fmt_num(safe_float(quote_data.get("high")), 3 if instrument.kind == "ETF" else 2),
                band=band,
                sources="、".join(quote_data.get("sources") or ["N/A"]),
            )
        )
    return "\n".join(rows)


def build_instrument_sections(instruments: list[Instrument], quotes: dict[str, dict[str, Any]]) -> str:
    sections: list[str] = []
    for instrument in instruments:
        quote_data = quotes.get(instrument.code, {})
        band, band_note = price_band(quote_data, instrument.kind)
        score = adjusted_score(instrument, quote_data)
        pct = safe_float(quote_data.get("pct"))
        state = market_state(pct)
        sections.append(
            f"""### {instrument.name}（{instrument.code}）

**郑希视角推演（非其本人原话）：** {instrument.zhengxi_angle}

- 当日状态：{state}，最新价 {fmt_num(safe_float(quote_data.get("price")), 3 if instrument.kind == "ETF" else 2)}，涨跌幅 {fmt_num(pct, suffix="%")}，成交额 {fmt_amount(safe_float(quote_data.get("amount")))}。
- 框架契合度：{score}/100（{score_label(score)}）。主要依据是景气周期、全球比较优势、流动性与 ROE/利润弹性的组合判断。
- 关键原因：若产业景气来自新技术落地或供给端创造需求，并且价格/利润预期仍在上修，就更接近郑希偏好的"科技型通胀"；反之，若只是估值修复或交易拥挤，结论强度要下降。
- 主要风险：{instrument.core_risk}
- 建议：{suggestion(instrument, quote_data)}
- 市场预期价格：{band}（{band_note}）。
"""
        )
    return "\n".join(sections)


def build_post(
    today: datetime,
    statuses: dict[str, str],
    index_quotes: dict[str, dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
) -> str:
    date_str = today.strftime("%Y-%m-%d")
    method_quote = load_method_quote()
    generated_at = today.strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"""---
title: "{date_str} 每日财经日志：郑希视角观察"
date: {today.strftime("%Y-%m-%d %H:%M:%S %z")}
categories:
  - 财经日志
tags:
  - 郑希
  - 润泽科技
  - 科创50ETF
  - 创业板ETF
  - 赛力斯
  - 比亚迪
excerpt: "基于 zhengxi-views skill 方法框架与公开行情源生成的每日财经观察。"
---

> 自动生成时间：{generated_at}
>
> 说明：本文由 GitHub Actions 调用 `zhengxi-views` skill 的方法框架生成。除明确引用的郑希公开表述外，个股/ETF 判断均为"按郑希方法的推演"，不代表郑希本人观点，也不构成投资建议。

## 数据源状态

{build_source_status(statuses)}

## 今日市场概览

{build_market_table(index_quotes)}

## 跟踪标的一览

{build_instrument_table(INSTRUMENTS, quotes)}

## 使用的郑希方法框架

{method_quote}

本日志按这个框架观察五个标的：先看全球技术/需求变化，再看产业链中是否出现"通胀"或利润上修环节，随后用中国比较优势、流动性、ROE 修复弹性和退出纪律校验。

## 分标的观察

{build_instrument_sections(INSTRUMENTS, quotes)}

## 复盘清单

- 明天优先检查：价格是否落在今日给出的观察区间内，以及成交额是否放大或萎缩。
- 若行情源出现缺失，以东方财富和腾讯股票的可用数据为主，雪球/新浪作为交叉验证。
- 若后续出现财报、产业政策、公司公告或重大新闻，应覆盖单日技术区间，重新评估底层逻辑。
"""


def main() -> int:
    if not SKILL_DIR.exists():
        print(f"Missing skill directory: {SKILL_DIR}", file=sys.stderr)
        return 1

    now = datetime.now(TZ)
    all_secids = [item.eastmoney_secid for item in INSTRUMENTS] + [secid for _, secid in INDEXES]
    eastmoney_quotes, eastmoney_status = fetch_eastmoney(all_secids)
    tencent_quotes, tencent_status = fetch_tencent([item.tencent_symbol for item in INSTRUMENTS])
    sina_quotes, sina_status = fetch_sina([item.sina_symbol for item in INSTRUMENTS])
    xueqiu_quotes, xueqiu_status = fetch_xueqiu([item.xueqiu_symbol for item in INSTRUMENTS])

    instrument_quotes = merge_quotes(
        INSTRUMENTS,
        eastmoney=eastmoney_quotes,
        tencent=tencent_quotes,
        sina=sina_quotes,
        xueqiu=xueqiu_quotes,
    )
    index_quotes = {code: value for code, value in eastmoney_quotes.items() if code in {s.split(".")[-1] for _, s in INDEXES}}

    statuses = {
        "东方财富": eastmoney_status,
        "腾讯股票": tencent_status,
        "新浪财经": sina_status,
        "雪球": xueqiu_status,
    }

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = POSTS_DIR / f"{now.strftime('%Y-%m-%d')}-finance-log.md"
    filename.write_text(build_post(now, statuses, index_quotes, instrument_quotes), encoding="utf-8")
    print(f"Wrote {filename.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
