from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from bot_trading_news.config import BotConfig


@dataclass(slots=True)
class SmartMoneySignal:
    symbol: str
    conviction_score: float
    manager_count: int
    crowding_risk: float
    top_managers: list[str]
    source: str


SEC_MANAGERS = [
    {"name": "Berkshire Hathaway", "cik": "0001067983"},
    {"name": "Pershing Square", "cik": "0001336528"},
    {"name": "Tiger Global", "cik": "0001167483"},
    {"name": "Coatue Management", "cik": "0001456801"},
    {"name": "Scion Asset Management", "cik": "0001649339"},
]

ISSUER_ALIASES = {
    "AAPL": ["apple"],
    "MSFT": ["microsoft"],
    "NVDA": ["nvidia"],
    "TSLA": ["tesla"],
    "SPY": ["spdr s&p 500", "spdr s p 500", "s&p 500 etf"],
    "BTC": ["bitcoin", "ishares bitcoin", "grayscale bitcoin", "blackrock bitcoin"],
    "AMZN": ["amazon"],
    "GOOGL": ["alphabet", "google"],
    "META": ["meta", "facebook"],
    "AMD": ["advanced micro devices", "amd"],
    "NFLX": ["netflix"],
    "QQQ": ["invesco qqq", "qqq trust", "nasdaq 100 trust"],
    "IWM": ["russell 2000", "ishares russell 2000"],
    "COIN": ["coinbase"],
    "MSTR": ["microstrategy", "strategy inc"],
    "XOM": ["exxon", "exxon mobil"],
    "GLD": ["spdr gold", "gold trust"],
    "TLT": ["20+ year treasury", "20 year treasury", "ishares 20+ year treasury"],
    "JPM": ["jpmorgan", "jp morgan"],
    "BA": ["boeing"],
}


def load_smart_money_signals(
    config: BotConfig,
    file_path: str = "sample_smart_money.json",
) -> dict[str, SmartMoneySignal]:
    mode = config.smart_money_mode
    if mode == "sec":
        try:
            return fetch_sec_smart_money(config, config.watchlist)
        except Exception:
            pass
    if mode == "fmp" and config.fmp_api_key:
        try:
            return fetch_fmp_smart_money(config, config.watchlist)
        except Exception:
            pass

    return load_smart_money_from_file(file_path)


def load_smart_money_from_file(file_path: str) -> dict[str, SmartMoneySignal]:
    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    signals: dict[str, SmartMoneySignal] = {}
    for item in payload:
        symbol = str(item["symbol"]).upper()
        signals[symbol] = SmartMoneySignal(
            symbol=symbol,
            conviction_score=float(item.get("conviction_score", 0.0)),
            manager_count=int(item.get("manager_count", 0)),
            crowding_risk=float(item.get("crowding_risk", 0.0)),
            top_managers=[str(value) for value in item.get("top_managers", [])],
            source=str(item.get("source", "sample")),
        )
    return signals


def fetch_fmp_smart_money(
    config: BotConfig, symbols: list[str]
) -> dict[str, SmartMoneySignal]:
    if not config.fmp_api_key:
        raise ValueError("Falta FMP_API_KEY para smart money via FMP.")

    base_url = "https://financialmodelingprep.com/api/v4/institutional-ownership/symbol-positions-summary"
    signals: dict[str, SmartMoneySignal] = {}

    for symbol in symbols:
        response = requests.get(
            base_url,
            params={"symbol": symbol, "apikey": config.fmp_api_key},
            timeout=20,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            continue

        row = rows[0]
        holders = int(row.get("holders", 0) or 0)
        changes = float(row.get("changeInSharesNumberPercentage", 0.0) or 0.0)
        put_call_ratio = float(row.get("putCallShareRatio", 0.0) or 0.0)
        conviction = max(min((changes / 10), 3.0), -3.0)
        crowding_risk = min(max((put_call_ratio - 1.0), -2.0), 2.0)

        signals[symbol] = SmartMoneySignal(
            symbol=symbol,
            conviction_score=round(conviction, 2),
            manager_count=holders,
            crowding_risk=round(crowding_risk, 2),
            top_managers=[],
            source="fmp_13f",
        )

    return signals


def fetch_sec_smart_money(
    config: BotConfig, symbols: list[str]
) -> dict[str, SmartMoneySignal]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": config.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        }
    )

    aggregated: dict[str, dict] = {
        symbol: {"conviction": 0.0, "manager_count": 0, "managers": []}
        for symbol in symbols
    }

    for manager in SEC_MANAGERS:
        holdings = _fetch_manager_holdings(session, manager["cik"])
        matched_symbols = set()
        for issuer_name, position_value in holdings:
            symbol = _match_symbol(issuer_name, symbols)
            if not symbol:
                continue
            normalized_value = min(position_value / 5000000, 1.8)
            aggregated[symbol]["conviction"] += normalized_value
            matched_symbols.add(symbol)

        for symbol in matched_symbols:
            aggregated[symbol]["manager_count"] += 1
            aggregated[symbol]["managers"].append(manager["name"])

    signals: dict[str, SmartMoneySignal] = {}
    for symbol, item in aggregated.items():
        if item["manager_count"] == 0:
            continue
        crowding = min(max((item["manager_count"] - 2) * 0.35, 0.0), 1.5)
        signals[symbol] = SmartMoneySignal(
            symbol=symbol,
            conviction_score=round(item["conviction"], 2),
            manager_count=item["manager_count"],
            crowding_risk=round(crowding, 2),
            top_managers=item["managers"][:5],
            source="sec_13f",
        )
    return signals


def _fetch_manager_holdings(session: requests.Session, cik: str) -> list[tuple[str, float]]:
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
    submissions = session.get(submissions_url, timeout=20)
    submissions.raise_for_status()
    data = submissions.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])

    accession = None
    for form, accession_number in zip(forms, accessions):
        if str(form).startswith("13F-HR"):
            accession = str(accession_number)
            break
    if not accession:
        return []

    accession_clean = accession.replace("-", "")
    cik_no_padding = str(int(cik))
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_padding}/{accession_clean}/index.json"
    index_response = session.get(index_url, timeout=20)
    index_response.raise_for_status()
    index_data = index_response.json()
    items = index_data.get("directory", {}).get("item", [])

    xml_name = ""
    for item in items:
        name = str(item.get("name", ""))
        lowered = name.lower()
        if lowered.endswith(".xml") and "infotable" in lowered:
            xml_name = name
            break
    if not xml_name:
        return []

    xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_padding}/{accession_clean}/{xml_name}"
    xml_response = session.get(xml_url, timeout=20)
    xml_response.raise_for_status()
    return _parse_info_table(xml_response.text)


def _parse_info_table(xml_text: str) -> list[tuple[str, float]]:
    root = ET.fromstring(xml_text)
    holdings: list[tuple[str, float]] = []
    for info_table in root.iter():
        if not info_table.tag.lower().endswith("infotable"):
            continue

        issuer_name = ""
        position_value = 0.0
        for child in info_table:
            tag = child.tag.lower()
            text = (child.text or "").strip()
            if tag.endswith("nameofissuer"):
                issuer_name = text
            elif tag.endswith("value"):
                try:
                    position_value = float(text)
                except ValueError:
                    position_value = 0.0

        if issuer_name:
            holdings.append((issuer_name, position_value))
    return holdings


def _match_symbol(issuer_name: str, symbols: list[str]) -> str | None:
    lowered = issuer_name.lower()
    for symbol in symbols:
        aliases = ISSUER_ALIASES.get(symbol, [symbol.lower()])
        if any(alias in lowered for alias in aliases):
            return symbol
    return None
