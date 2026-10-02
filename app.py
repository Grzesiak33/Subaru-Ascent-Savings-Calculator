from __future__ import annotations

from datetime import date, timedelta
import base64
import json
import math
import re
from urllib.parse import urljoin

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(
    page_title="Ashlee's Subaru Ascent Fund",
    page_icon="🚙",
    layout="wide",
)

# ---------- Helpers ----------
def money(value: float) -> str:
    return f"${value:,.0f}"


def monthly_payment(principal: float, annual_rate_pct: float, months: int) -> float:
    if principal <= 0 or months <= 0:
        return 0.0
    monthly_rate = annual_rate_pct / 100 / 12
    if monthly_rate == 0:
        return principal / months
    return principal * (monthly_rate * (1 + monthly_rate) ** months) / (((1 + monthly_rate) ** months) - 1)


def biweekly_dates(first_deposit: date, target_date: date) -> list[date]:
    if first_deposit > target_date:
        return []
    dates = []
    d = first_deposit
    while d <= target_date:
        dates.append(d)
        d += timedelta(days=14)
    return dates


def total_interest(payment: float, months: int, principal: float) -> float:
    return max(0.0, payment * months - principal)


def tiered_savings_balance(
    deposits: list[dict],
    as_of: date,
    promo_apy_pct: float,
    promo_cap: float,
    above_cap_apy_pct: float = 0.0,
) -> tuple[float, float]:
    eligible = [d for d in deposits if date.fromisoformat(d["date"]) <= as_of]
    if not eligible:
        return 0.0, 0.0

    by_date: dict[date, float] = {}
    for dep in eligible:
        dep_date = date.fromisoformat(dep["date"])
        by_date[dep_date] = by_date.get(dep_date, 0.0) + float(dep["amount"])

    cursor = min(by_date)
    balance = 0.0
    principal = sum(float(d["amount"]) for d in eligible)
    promo_daily = (1 + promo_apy_pct / 100) ** (1 / 365) - 1
    above_daily = (1 + above_cap_apy_pct / 100) ** (1 / 365) - 1

    while cursor <= as_of:
        balance += by_date.get(cursor, 0.0)

        # Interest accrues after a full day has elapsed, so a deposit made
        # today still displays as its exact deposited amount today.
        if cursor < as_of:
            promo_balance = min(balance, promo_cap)
            above_balance = max(0.0, balance - promo_cap)
            balance += promo_balance * promo_daily + above_balance * above_daily

        cursor += timedelta(days=1)

    return balance, max(0.0, balance - principal)


def build_projected_ledger(
    actual_deposits: list[dict],
    recurring_enabled: bool,
    recurring_amount: float,
    first_recurring: date,
    target: date,
) -> list[dict]:
    projected = [dict(d) for d in actual_deposits]
    if recurring_enabled and recurring_amount > 0 and first_recurring <= target:
        d = first_recurring
        while d <= target:
            projected.append(
                {
                    "date": d.isoformat(),
                    "amount": float(recurring_amount),
                    "note": "Projected recurring deposit",
                    "projected": True,
                }
            )
            d += timedelta(days=14)
    return projected


# ---------- Used Subaru Ascent market scanner ----------
FAMILY_FEATURES = {
    "2nd-row captain's chairs": ["captain's chairs", "captains chairs", "rear bucket seats", "2nd row captain"],
    "Rear climate / A/C": ["rear a/c", "rear ac", "rear climate", "rear-seat climate", "rear seat climate"],
    "Heated rear seats": ["heated rear seats", "rear heated seats", "heated second row"],
    "USBs for the kids": ["usb ports", "usb-a", "usb-c", "usb input"],
    "Power liftgate": ["power liftgate", "power lift gate", "power rear gate"],
    "EyeSight / adaptive cruise": ["eyesight", "adaptive cruise control"],
    "Blind-spot monitoring": ["blind spot", "blind-spot"],
    "Rear cross-traffic alert": ["rear cross traffic", "rear cross-traffic"],
    "Leather / easy-clean seating": ["leather seats", "leather upholstery", "spill-resistant", "startex"],
    "Panoramic roof": ["panoramic roof", "panoramic sunroof", "moonroof"],
}

CLEAN_HISTORY_TERMS = [
    "no accidents",
    "accident free",
    "clean carfax",
    "clean autocheck",
    "clean vehicle history",
]
ONE_OWNER_TERMS = ["one owner", "1 owner", "one-owner", "1-owner"]
SERVICE_TERMS = ["service records", "regular maintenance", "maintenance records", "dealer serviced"]
INSPECTION_TERMS = ["certified pre-owned", "cpo", "multi-point inspection", "multipoint inspection"]
ACCIDENT_TERMS = ["accident reported", "damage reported", "collision", "accident history"]
SEVERE_HISTORY_TERMS = [
    "salvage",
    "rebuilt title",
    "rebuilt salvage",
    "structural damage",
    "frame damage",
    "flood damage",
    "lemon law",
]


def _number_from_text(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", value)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _year_from_title(title: str) -> int | None:
    match = re.search(r"\b(20(?:1[9]|2[0-9]))\b", title or "")
    return int(match.group(1)) if match else None


def _text_has_any(text: str, terms: list[str]) -> bool:
    lower = (text or "").lower()
    return any(term in lower for term in terms)


def listing_signals(text: str) -> tuple[list[str], list[str], list[str]]:
    lower = (text or "").lower()
    family = [label for label, terms in FAMILY_FEATURES.items() if any(term in lower for term in terms)]
    positives: list[str] = []
    warnings: list[str] = []

    if _text_has_any(lower, CLEAN_HISTORY_TERMS):
        positives.append("Listing claims clean / accident-free history")
    if _text_has_any(lower, ONE_OWNER_TERMS):
        positives.append("One-owner signal")
    if _text_has_any(lower, SERVICE_TERMS):
        positives.append("Maintenance / service-record signal")
    if _text_has_any(lower, INSPECTION_TERMS):
        positives.append("Inspection / CPO signal")

    if _text_has_any(lower, ACCIDENT_TERMS):
        warnings.append("Accident or damage language found")
    severe = [term for term in SEVERE_HISTORY_TERMS if term in lower]
    if severe:
        warnings.append("Severe history flag: " + ", ".join(severe[:2]))

    return family, positives, warnings


def value_score(
    listing: dict,
    preferred_price: float,
    preferred_miles: float,
    ideal_miles: float,
) -> tuple[float, dict]:
    price = float(listing.get("price") or 999999)
    miles = float(listing.get("mileage") or 999999)
    year = listing.get("year") or 2019
    family = listing.get("family_features") or []
    positives = listing.get("condition_positives") or []
    warnings = listing.get("condition_warnings") or []

    # Price: 30 points. Full credit at <=85% of the preferred ceiling,
    # then gradually falls through the preferred price and beyond.
    if price <= preferred_price * 0.85:
        price_score = 30.0
    elif price <= preferred_price:
        frac = (price - preferred_price * 0.85) / max(preferred_price * 0.15, 1)
        price_score = 30.0 - 8.0 * frac
    else:
        price_score = max(0.0, 22.0 * (1 - (price - preferred_price) / 6000.0))

    # Mileage: 25 points. <= ideal is excellent, <= preferred is still strong.
    if miles <= ideal_miles:
        mileage_score = 25.0
    elif miles <= preferred_miles:
        span = max(preferred_miles - ideal_miles, 1)
        mileage_score = 25.0 - 7.0 * ((miles - ideal_miles) / span)
    elif miles <= 100000:
        span = max(100000 - preferred_miles, 1)
        mileage_score = 18.0 - 13.0 * ((miles - preferred_miles) / span)
    else:
        mileage_score = max(0.0, 5.0 - ((miles - 100000) / 15000.0))

    # Condition/history: 25 points. Unknown is deliberately not treated as "clean."
    condition_score = 12.0
    condition_score += min(13.0, len(positives) * 3.5)
    if any("Accident" in w for w in warnings):
        condition_score -= 10.0
    severe = any("Severe history" in w for w in warnings)
    if severe:
        condition_score = 0.0
    condition_score = max(0.0, min(25.0, condition_score))

    # Family-road-trip equipment: 15 points.
    family_score = min(15.0, len(family) * 1.8)

    # Year: only 5 points so a clean, well-priced older Ascent can still win.
    if year >= 2022:
        year_score = 5.0
    elif year == 2021:
        year_score = 4.0
    elif year == 2020:
        year_score = 3.0
    else:
        year_score = 2.0

    total = round(price_score + mileage_score + condition_score + family_score + year_score, 1)
    if severe:
        total = min(total, 35.0)

    detail = {
        "price": round(price_score, 1),
        "mileage": round(mileage_score, 1),
        "condition": round(condition_score, 1),
        "family": round(family_score, 1),
        "year": round(year_score, 1),
    }
    return total, detail


def generic_listing_from_url(url: str, timeout: int = 12) -> dict | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AscentValueFinder/1.0; +personal-use)",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = " ".join(soup.stripped_strings)
    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else "Subaru Ascent listing"

    price_match = re.search(r"\$\s*([0-9]{2,3}(?:,[0-9]{3})+)", text)
    mileage_match = re.search(r"([0-9]{1,3}(?:,[0-9]{3})+)\s*(?:mi\.?|miles)", text, re.I)
    price = _number_from_text(price_match.group(1)) if price_match else None
    mileage = _number_from_text(mileage_match.group(1)) if mileage_match else None
    if price is None or mileage is None or "ascent" not in text.lower():
        return None

    family, positives, warnings = listing_signals(text)
    vin_match = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", text)

    return {
        "title": title[:140],
        "year": _year_from_title(title),
        "price": price,
        "mileage": mileage,
        "dealer": "Listing page",
        "distance": None,
        "url": url,
        "vin": vin_match.group(1) if vin_match else "",
        "family_features": family,
        "condition_positives": positives,
        "condition_warnings": warnings,
        "source": "Pasted listing",
        "raw_text": text[:15000],
    }


@st.cache_data(ttl=900, show_spinner=False)
def scrape_ascent_market(zip_code: str, radius_miles: int, max_detail_pages: int = 14) -> tuple[list[dict], str]:
    url = "https://www.cars.com/shopping/results/"
    params = [
        ("stock_type", "used"),
        ("makes[]", "subaru"),
        ("models[]", "subaru-ascent"),
        ("maximum_distance", str(radius_miles)),
        ("zip", zip_code),
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as exc:
        return [], "Live search request failed: " + str(exc)

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select("div.vehicle-card")
    listings: list[dict] = []
    seen: set[str] = set()

    for card in cards:
        title_el = card.select_one(".title") or card.select_one("h2")
        price_el = card.select_one(".primary-price")
        mileage_el = card.select_one(".mileage")
        dealer_el = card.select_one(".dealer-name")
        link_el = card.select_one("a.vehicle-card-link") or card.select_one('a[href*="/vehicledetail/"]')

        title = title_el.get_text(" ", strip=True) if title_el else ""
        price = _number_from_text(price_el.get_text(" ", strip=True) if price_el else "")
        mileage = _number_from_text(mileage_el.get_text(" ", strip=True) if mileage_el else "")
        href = link_el.get("href") if link_el else None
        listing_url = urljoin("https://www.cars.com", href) if href else ""

        if not title or "ascent" not in title.lower() or price is None or mileage is None:
            continue
        dedupe_key = listing_url or f"{title}-{price}-{mileage}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        card_text = " ".join(card.stripped_strings)
        dist_match = re.search(r"(\d+(?:\.\d+)?)\s*mi(?:\.|les)?\s*away", card_text, re.I)
        distance = float(dist_match.group(1)) if dist_match else None
        dealer = dealer_el.get_text(" ", strip=True) if dealer_el else "Dealer listing"
        family, positives, warnings = listing_signals(card_text)

        listings.append(
            {
                "title": title,
                "year": _year_from_title(title),
                "price": price,
                "mileage": mileage,
                "dealer": dealer,
                "distance": distance,
                "url": listing_url,
                "vin": "",
                "family_features": family,
                "condition_positives": positives,
                "condition_warnings": warnings,
                "source": "Cars.com 20-mile dealer search",
                "raw_text": card_text,
            }
        )

    # Enrich a limited number of results with detail-page feature/history language.
    for listing in listings[:max_detail_pages]:
        if not listing["url"]:
            continue
        try:
            detail_response = requests.get(listing["url"], headers=headers, timeout=10)
            if detail_response.status_code != 200:
                continue
            detail_soup = BeautifulSoup(detail_response.text, "html.parser")
            detail_text = " ".join(detail_soup.stripped_strings)
            family, positives, warnings = listing_signals(detail_text)
            listing["family_features"] = sorted(set(listing["family_features"] + family))
            listing["condition_positives"] = sorted(set(listing["condition_positives"] + positives))
            listing["condition_warnings"] = sorted(set(listing["condition_warnings"] + warnings))
            listing["raw_text"] = detail_text[:15000]
            vin_match = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", detail_text)
            if vin_match:
                listing["vin"] = vin_match.group(1)
        except Exception:
            pass

    if not listings:
        return [], "The listing site returned a page, but no readable vehicle cards were found. It may be blocking automated requests."

    return listings, ""


def rank_ascent_listings(
    listings: list[dict],
    preferred_price: float,
    preferred_miles: float,
    ideal_miles: float,
    exclude_severe_history: bool,
) -> list[dict]:
    ranked: list[dict] = []
    for source_listing in listings:
        listing = dict(source_listing)
        severe = any("Severe history" in warning for warning in listing.get("condition_warnings", []))
        if exclude_severe_history and severe:
            continue
        score, score_detail = value_score(listing, preferred_price, preferred_miles, ideal_miles)
        listing["value_score"] = score
        listing["score_detail"] = score_detail
        if score >= 82:
            listing["value_label"] = "Excellent target"
        elif score >= 70:
            listing["value_label"] = "Strong value"
        elif score >= 58:
            listing["value_label"] = "Worth a look"
        else:
            listing["value_label"] = "Below target"
        ranked.append(listing)
    return sorted(ranked, key=lambda x: x["value_score"], reverse=True)


def ai_market_summary(ranked: list[dict], token: str) -> str:
    if not token.strip():
        raise ValueError("Enter a free Hugging Face token first.")

    from huggingface_hub import InferenceClient

    payload = []
    for i, item in enumerate(ranked[:5], start=1):
        payload.append(
            {
                "rank": i,
                "title": item.get("title"),
                "price": item.get("price"),
                "mileage": item.get("mileage"),
                "dealer": item.get("dealer"),
                "score": item.get("value_score"),
                "family_features": item.get("family_features"),
                "history_signals": item.get("condition_positives"),
                "warnings": item.get("condition_warnings"),
            }
        )

    prompt = (
        "You are helping a family evaluate used Subaru Ascent listings. "
        "The deterministic score is already calculated and must not be reordered. "
        "Explain the tradeoffs in the top listings using only the supplied facts. "
        "Do not assume a clean title or accident-free history when it is not stated. "
        "Emphasize price, mileage, family road-trip features, and condition/history uncertainty. "
        "Keep the answer concise and practical.\n\n"
        + json.dumps(payload, indent=2)
    )

    client = InferenceClient(token=token.strip())
    response = client.chat_completion(
        model="Qwen/Qwen2.5-7B-Instruct",
        messages=[
            {"role": "system", "content": "Be factual, concise, and careful about unknown vehicle history."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=650,
        temperature=0.2,
    )
    return response.choices[0].message.content


# ---------- Persistent deposit ledger ----------
STORAGE_PARAM = "ledger"
SEED_LEDGER = [
    {
        "date": "2026-09-30",
        "amount": 60.0,
        "note": "First deposit to high-yield savings",
        "projected": False,
    }
]


def encode_ledger(ledger: list[dict]) -> str:
    raw = json.dumps(ledger, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_ledger(token: str) -> list[dict]:
    padding = "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("Invalid ledger")
    return parsed


if "deposit_ledger" not in st.session_state:
    try:
        token = st.query_params.get(STORAGE_PARAM)
        st.session_state.deposit_ledger = decode_ledger(token) if token else list(SEED_LEDGER)
    except Exception:
        st.session_state.deposit_ledger = list(SEED_LEDGER)

deposit_ledger = st.session_state.deposit_ledger


def save_deposit_ledger() -> None:
    st.query_params[STORAGE_PARAM] = encode_ledger(st.session_state.deposit_ledger)


# ---------- Styling ----------
st.markdown(
    """
    <style>
        :root {
            --pink-dark: #5A163A;
            --pink-deep: #7A1F4E;
            --pink: #E74C9B;
            --pink-bright: #FF78B9;
            --pink-soft: #FFD4E8;
            --blush: #FFF1F8;
            --blue: #67C8FF;
            --blue-deep: #277EAE;
            --blue-soft: #DDF4FF;
            --cream: #FFFDFB;
            --plum: #3E2434;
            --teal: #1E6F74;
        }
        .stApp {
            background:
                radial-gradient(circle at 7% 4%, rgba(255,120,185,.22), transparent 24%),
                radial-gradient(circle at 94% 8%, rgba(103,200,255,.24), transparent 26%),
                linear-gradient(180deg, #FFF5FA 0%, #F6FBFF 52%, #FFF0F8 100%);
            color: #332831;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #6B1B49 0%, #C23D82 48%, #277EAE 100%);
        }
        [data-testid="stSidebar"] * { color: white; }
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] [data-baseweb="select"] > div {
            background: rgba(255,255,255,.11) !important;
            border-color: rgba(255,255,255,.24) !important;
        }
        .hero {
            padding: 2rem 1.8rem;
            border-radius: 26px;
            background: linear-gradient(135deg, #6B1B49 0%, #E74C9B 56%, #67C8FF 145%);
            color: white;
            margin-bottom: 1rem;
            box-shadow: 0 16px 38px rgba(90,22,58,.22);
        }
        .hero-kicker {
            display: inline-block;
            padding: .35rem .7rem;
            border-radius: 999px;
            background: rgba(255,255,255,.16);
            border: 1px solid rgba(255,255,255,.24);
            font-weight: 800;
            font-size: .78rem;
            letter-spacing: .08em;
            text-transform: uppercase;
            margin-bottom: .75rem;
        }
        .hero h1 { margin: 0; font-size: 2.65rem; line-height: 1.03; color: white; }
        .hero p { margin: .65rem 0 0 0; opacity: .94; font-size: 1.02rem; }
        .hero-love { margin-top: .95rem; color: #FFE4F0; font-weight: 800; }
        .metric-card {
            background: rgba(255,255,255,.95);
            border: 1px solid #F0C0D5;
            border-radius: 20px;
            padding: 1rem 1.1rem;
            min-height: 130px;
            box-shadow: 0 8px 22px rgba(90,22,58,.08);
        }
        .metric-label { color: #86566D; font-size: .8rem; font-weight: 800; text-transform: uppercase; letter-spacing: .07em; }
        .metric-value { color: #5A163A; font-size: 2rem; font-weight: 900; margin-top: .25rem; }
        .metric-note { color: #725D68; font-size: .86rem; margin-top: .25rem; }
        h1, h2, h3, h4 { color: #5A163A; }
        [data-testid="stMetricValue"] { color: #5A163A; }
        [data-testid="stMetricDelta"] { color: #1E6F74 !important; }
        div[data-testid="stProgress"] > div > div > div > div { background-color: #D9468B; }
        .good { color: #1E6F74; font-weight: 800; }
        .small-note { color: #725D68; font-size: .85rem; }

        .whiteboard-title {
            text-align: center;
            font-size: 1.55rem;
            font-weight: 900;
            color: #5A163A;
            margin: .15rem 0 .1rem 0;
        }
        .whiteboard-subtitle {
            text-align: center;
            color: #277EAE;
            font-weight: 750;
            margin-bottom: .45rem;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #FFFFFF;
            border: 9px solid #D6DCE4 !important;
            border-radius: 22px !important;
            box-shadow: 0 12px 28px rgba(49,74,94,.14), inset 0 0 0 2px #F1F4F7;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:after {
            content: "";
            display: block;
            width: 42%;
            height: 8px;
            border-radius: 999px;
            margin: .45rem auto -.2rem auto;
            background: linear-gradient(90deg, #E74C9B 0 47%, #67C8FF 47% 100%);
            box-shadow: 0 3px 8px rgba(0,0,0,.12);
        }
        .board-note {
            text-align: center;
            color: #6F6170;
            font-size: .85rem;
            margin: .2rem 0 .8rem 0;
        }
        .balance-panel {
            background: linear-gradient(145deg, #FFF8FC 0%, #F1FAFF 100%);
            border: 2px solid #F1B8D6;
            border-radius: 24px;
            padding: 1.1rem;
            box-shadow: 0 10px 25px rgba(83,58,78,.08);
        }
        .balance-ring {
            width: 220px;
            height: 220px;
            margin: .25rem auto .65rem auto;
            border-radius: 50%;
            display: grid;
            place-items: center;
            position: relative;
            box-shadow: 0 10px 25px rgba(103,200,255,.15);
        }
        .balance-ring:before {
            content: "";
            width: 164px;
            height: 164px;
            border-radius: 50%;
            background: white;
            position: absolute;
            box-shadow: inset 0 0 0 1px #F4D7E6;
        }
        .balance-center {
            position: relative;
            z-index: 2;
            text-align: center;
        }
        .balance-number {
            color: #5A163A;
            font-weight: 950;
            font-size: 2.2rem;
            line-height: 1;
        }
        .balance-label {
            color: #786573;
            text-transform: uppercase;
            letter-spacing: .08em;
            font-weight: 800;
            font-size: .72rem;
            margin-top: .45rem;
        }
        .goal-line {
            color: #277EAE;
            text-align: center;
            font-weight: 850;
            margin-top: .35rem;
        }
        .projection-card {
            background: linear-gradient(135deg, #FFE4F1 0%, #E6F6FF 100%);
            border: 1px solid #E5B7D1;
            border-radius: 20px;
            padding: 1rem 1.1rem;
            min-height: 145px;
            box-shadow: 0 8px 22px rgba(86,81,105,.07);
        }
        .projection-big {
            color: #5A163A;
            font-weight: 950;
            font-size: 2rem;
            margin-top: .2rem;
        }
        @media (max-width: 640px) {
            .block-container {
                padding-top: .55rem !important;
                padding-left: .65rem !important;
                padding-right: .65rem !important;
            }
            [data-testid="stNumberInput"] input,
            [data-testid="stDateInput"] input {
                min-height: 48px !important;
                font-size: 16px !important;
            }
            [data-baseweb="select"] > div {
                min-height: 48px !important;
                font-size: 16px !important;
            }
            [data-testid="stExpander"] {
                border-radius: 18px !important;
            }
            .whiteboard-title {
                font-size: 1.15rem;
                margin-top: 0;
            }
            .whiteboard-subtitle {
                font-size: .85rem;
                margin-bottom: .2rem;
            }
            .board-note {
                margin-bottom: .15rem;
            }
            .hero {
                padding: 1.15rem 1rem;
                margin-top: .45rem;
            }
            .hero h1 {
                font-size: 1.75rem;
            }
        }

        .deposit-card {
            background: linear-gradient(135deg, #FFF0F8 0%, #EAF8FF 100%);
            border: 2px solid #F1B8D6;
            border-radius: 22px;
            padding: 1rem 1.1rem;
            box-shadow: 0 8px 24px rgba(70,75,110,.08);
            margin-bottom: .9rem;
        }
        .deposit-total {
            font-size: 2rem;
            font-weight: 950;
            color: #5A163A;
            line-height: 1;
        }
        .deposit-sub {
            color: #277EAE;
            font-weight: 750;
            margin-top: .35rem;
        }
        .tank-wrap {
            background: linear-gradient(180deg, #FAFDFF 0%, #FFF5FA 100%);
            border: 2px solid #D9B7CE;
            border-radius: 28px;
            padding: 1rem;
            box-shadow: 0 12px 28px rgba(59,73,103,.10);
            text-align: center;
        }
        .savings-tank {
            width: 150px;
            height: 300px;
            margin: .4rem auto .7rem auto;
            border: 7px solid #4D6780;
            border-radius: 34px 34px 26px 26px;
            position: relative;
            overflow: hidden;
            background:
                repeating-linear-gradient(to top, transparent 0 58px, rgba(39,126,174,.13) 58px 60px),
                #FFFFFF;
            box-shadow: inset 0 0 0 4px #E9F6FD, 0 10px 22px rgba(103,200,255,.16);
        }
        .tank-fill {
            position: absolute;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(180deg, #67C8FF 0%, #B7E9FF 35%, #FF9AC8 68%, #E74C9B 100%);
            transition: height .8s ease;
        }
        .tank-bubbles {
            position: absolute;
            inset: 0;
            background-image:
                radial-gradient(circle at 25% 75%, rgba(255,255,255,.55) 0 5px, transparent 6px),
                radial-gradient(circle at 70% 55%, rgba(255,255,255,.48) 0 7px, transparent 8px),
                radial-gradient(circle at 45% 35%, rgba(255,255,255,.42) 0 4px, transparent 5px);
        }
        .tank-car {
            position: absolute;
            left: 50%;
            transform: translateX(-50%);
            font-size: 1.9rem;
            z-index: 3;
            transition: bottom .8s ease;
            filter: drop-shadow(0 3px 3px rgba(0,0,0,.18));
        }
        .tank-cap-line {
            position: absolute;
            left: 0;
            right: 0;
            border-top: 2px dashed #277EAE;
            z-index: 4;
        }
        .tank-cap-label {
            color: #277EAE;
            font-size: .78rem;
            font-weight: 850;
        }
        .interest-pill {
            display: inline-block;
            padding: .35rem .7rem;
            border-radius: 999px;
            background: #E3F6FF;
            color: #277EAE;
            border: 1px solid #A8DEFA;
            font-size: .8rem;
            font-weight: 850;
            margin-top: .35rem;
        }

        .blue-chip {
            display: inline-block;
            background: #DDF4FF;
            color: #277EAE;
            border: 1px solid #AEDFFF;
            border-radius: 999px;
            padding: .3rem .65rem;
            font-weight: 800;
            font-size: .8rem;
            margin-top: .45rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Hero ----------
# Mobile-first: put the visualization first so Ashlee + the Ascent are visible immediately.
with st.container(border=True):
    st.markdown('<div class="whiteboard-title">🖊️ Visualization Board</div>', unsafe_allow_html=True)
    st.markdown('<div class="whiteboard-subtitle">Ashlee + her future Subaru Ascent 💗🚙</div>', unsafe_allow_html=True)
    st.image(
        "assets/ChatGPT Image Sep 27, 2026, 04_18_11 PM.png",
        use_container_width=True,
    )
    st.markdown('<div class="board-note">See it. Fund it. Drive it. 💗💙</div>', unsafe_allow_html=True)

st.markdown(
    """
    <div class="hero">
        <div class="hero-kicker">December car goal</div>
        <h1>💗 Ashlee's Subaru Ascent Fund</h1>
        <p>Every deposit moves the goal from “someday” to a real down payment, a lower amount financed, and a payment you can see before dealership day.</p>
        <div class="hero-love">Cotton-candy colors. Real numbers. Her future Ascent. ✨</div>
    </div>
    """,
    unsafe_allow_html=True,
)
# ---------- Deposit tracker ----------
st.markdown("## 💵 Add money to the car fund")
actual_principal = sum(float(d["amount"]) for d in deposit_ledger)

tracker_left, tracker_right = st.columns([1.05, 1.35], gap="large")
with tracker_left:
    plural = "s" if len(deposit_ledger) != 1 else ""
    st.markdown(
        f"""
        <div class="deposit-card">
            <div class="metric-label">SAVED DEPOSITS</div>
            <div class="deposit-total">{money(actual_principal)}</div>
            <div class="deposit-sub">{len(deposit_ledger)} saved deposit{plural} • saved in this page link</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with tracker_right:
    with st.form("add_deposit_form", clear_on_submit=True):
        d1, d2 = st.columns([0.8, 1.2])
        with d1:
            new_deposit_amount = st.number_input(
                "Deposit amount",
                min_value=0.01,
                value=60.0,
                step=10.0,
                format="%.2f",
            )
        with d2:
            new_deposit_date = st.date_input("Deposit date", value=date.today())
        new_deposit_note = st.text_input(
            "Optional note",
            placeholder="Example: payday transfer",
        )
        add_deposit = st.form_submit_button("💗 Save this deposit", use_container_width=True)

    if add_deposit:
        st.session_state.deposit_ledger.append(
            {
                "date": new_deposit_date.isoformat(),
                "amount": float(new_deposit_amount),
                "note": new_deposit_note.strip() or "Car fund deposit",
                "projected": False,
            }
        )
        save_deposit_ledger()
        st.success(f"Saved {money(new_deposit_amount)} to Ashlee's car fund.")
        st.rerun()

st.caption("Your saved deposits are stored in the page URL, so refreshing this exact page keeps them. After adding deposits, bookmark this page on your phone.")

with st.expander("📒 Deposit history"):
    history_df = pd.DataFrame(deposit_ledger)
    if not history_df.empty:
        history_df = history_df.sort_values("date", ascending=False)
        st.dataframe(
            history_df[["date", "amount", "note"]].style.format({"amount": "$" + "{:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )
        if st.button("↩️ Undo most recent deposit", type="secondary"):
            st.session_state.deposit_ledger.pop()
            save_deposit_ledger()
            st.rerun()

# ---------- Mobile-friendly inputs ----------
st.markdown("## 💗 Build the plan")
st.caption("Tap any number below to change it. Everything on the page recalculates instantly.")

with st.expander("✏️ Change savings, car price, and financing", expanded=True):
    save_col, car_col, finance_col = st.columns(3, gap="large")

    with save_col:
        st.markdown("### 💰 Savings")
        down_payment_goal = st.number_input(
            "Down payment goal",
            min_value=500.0,
            value=4000.0,
            step=250.0,
            format="%.0f",
            key="down_payment_goal",
        )
        recurring_enabled = st.toggle(
            "Recurring deposit is set up",
            value=False,
            help="Leave this off until the automatic transfer is actually active.",
            key="recurring_enabled",
        )
        biweekly_amount = st.number_input(
            "Recurring deposit every 2 weeks",
            min_value=0.0,
            value=300.0,
            step=25.0,
            format="%.0f",
            disabled=not recurring_enabled,
            key="biweekly_amount",
        )
        first_deposit = st.date_input(
            "Next / first recurring deposit",
            value=date(2026, 10, 2),
            disabled=not recurring_enabled,
            key="first_deposit",
        )
        target_date = st.date_input(
            "Target purchase date",
            value=date(2026, 12, 19),
            key="target_date",
        )
        st.markdown("#### 💙 HYSA growth")
        promo_apy_pct = st.number_input(
            "APY on first $1,000",
            min_value=0.0,
            max_value=100.0,
            value=10.0,
            step=0.25,
            key="promo_apy_pct",
        )
        above_cap_apy_pct = st.number_input(
            "APY above $1,000",
            min_value=0.0,
            max_value=25.0,
            value=0.0,
            step=0.25,
            help="Leave at 0 until you enter the account's rate above the first $1,000.",
            key="above_cap_apy_pct",
        )

    with car_col:
        st.markdown("### 🚙 Subaru target")
        car_price = st.number_input(
            "Negotiated vehicle price",
            min_value=5000.0,
            value=21000.0,
            step=250.0,
            format="%.0f",
            key="car_price",
        )
        sales_tax_pct = st.number_input(
            "Sales tax %",
            min_value=0.0,
            max_value=15.0,
            value=6.0,
            step=0.1,
            key="sales_tax_pct",
        )
        fees = st.number_input(
            "Title / registration / dealer fees",
            min_value=0.0,
            value=500.0,
            step=50.0,
            format="%.0f",
            key="fees",
        )
        trade_credit = st.number_input(
            "Trade-in / other credit",
            min_value=0.0,
            value=0.0,
            step=250.0,
            format="%.0f",
            key="trade_credit",
        )

    with finance_col:
        st.markdown("### 💳 Financing")
        apr = st.number_input(
            "APR %",
            min_value=0.0,
            max_value=35.0,
            value=19.10,
            step=0.25,
            help="Replace this planning placeholder with your actual prequalification APR.",
            key="apr",
        )
        term_months = st.selectbox(
            "Loan term",
            options=[36, 48, 60, 66, 72, 75, 84],
            index=4,
            key="term_months",
        )

# ---------- Calculations ----------
today = date.today()
promo_cap = 1000.0

current_saved, interest_earned_to_date = tiered_savings_balance(
    deposit_ledger,
    today,
    promo_apy_pct,
    promo_cap,
    above_cap_apy_pct,
)

deposit_dates = biweekly_dates(first_deposit, target_date) if recurring_enabled else []
num_deposits = len(deposit_dates)
future_deposits = num_deposits * biweekly_amount if recurring_enabled else 0.0

projected_ledger = build_projected_ledger(
    deposit_ledger,
    recurring_enabled,
    biweekly_amount,
    first_deposit,
    target_date,
)
saved_by_target, projected_interest_total = tiered_savings_balance(
    projected_ledger,
    target_date,
    promo_apy_pct,
    promo_cap,
    above_cap_apy_pct,
)

sales_tax = car_price * sales_tax_pct / 100
out_the_door = car_price + sales_tax + fees

cash_down = min(saved_by_target, max(0.0, out_the_door - trade_credit))
principal_zero_down = max(0.0, out_the_door - trade_credit)
principal_with_savings = max(0.0, out_the_door - trade_credit - cash_down)

payment_zero = monthly_payment(principal_zero_down, apr, term_months)
payment_saved = monthly_payment(principal_with_savings, apr, term_months)
monthly_savings = payment_zero - payment_saved
interest_zero = total_interest(payment_zero, term_months, principal_zero_down)
interest_saved = total_interest(payment_saved, term_months, principal_with_savings)
interest_reduction = interest_zero - interest_saved

current_progress_pct = 0.0 if down_payment_goal <= 0 else min(100.0, (current_saved / down_payment_goal) * 100)
projected_progress_pct = 0.0 if down_payment_goal <= 0 else min(100.0, (saved_by_target / down_payment_goal) * 100)
remaining_to_goal = max(0.0, down_payment_goal - current_saved)
projected_over_under = saved_by_target - down_payment_goal

# ---------- Cotton-candy savings tank ----------
tank_pct = 0.0 if down_payment_goal <= 0 else min(100.0, (current_saved / down_payment_goal) * 100)
promo_cap_pct = 0.0 if down_payment_goal <= 0 else min(100.0, (promo_cap / down_payment_goal) * 100)
car_bottom = max(2.0, min(92.0, tank_pct - 4.0))

st.markdown("## 🍦 Watch the car fund fill up")
tank_col, growth_col = st.columns([0.8, 1.4], gap="large", vertical_alignment="center")

with tank_col:
    st.markdown(
        f"""
        <div class="tank-wrap">
            <div class="metric-label">ASHLEE'S CAR FUND</div>
            <div class="savings-tank">
                <div class="tank-fill" style="height:{tank_pct:.1f}%;">
                    <div class="tank-bubbles"></div>
                </div>
                <div class="tank-cap-line" style="bottom:{promo_cap_pct:.1f}%;"></div>
                <div class="tank-car" style="bottom:{car_bottom:.1f}%;">🚙</div>
            </div>
            <div class="deposit-total">{money(current_saved)}</div>
            <div class="deposit-sub">{tank_pct:.1f}% of the {money(down_payment_goal)} goal</div>
            <div class="tank-cap-label">💙 10% APY bonus zone: first $1,000</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with growth_col:
    g1, g2, g3 = st.columns(3)
    g1.metric("Deposits made", money(actual_principal))
    g2.metric("Est. interest earned", money(interest_earned_to_date))
    g3.metric("Est. HYSA balance", money(current_saved))

    recurring_text = (
        f"{money(biweekly_amount)} every 2 weeks is ON"
        if recurring_enabled
        else "Not active yet — projection excludes recurring deposits"
    )
    st.markdown(
        f"""
        <div class="projection-card">
            <div class="metric-label">INTEREST + DEPOSIT ENGINE</div>
            <div class="projection-big">{money(saved_by_target)}</div>
            <div class="metric-note">estimated by {target_date.strftime('%B %d, %Y')} including HYSA growth</div>
            <div class="interest-pill">{promo_apy_pct:.2f}% APY on the first {money(promo_cap)}</div>
            <div class="blue-chip">{recurring_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------- Live savings status ----------
st.markdown("## 💗💙 Live car-fund balance")
balance_col, projection_col = st.columns([0.95, 1.35], gap="large", vertical_alignment="center")

with balance_col:
    st.markdown(
        f"""
        <div class="balance-panel">
            <div class="metric-label" style="text-align:center;">CURRENT ACTUAL BALANCE</div>
            <div class="balance-ring" style="background: conic-gradient(#E74C9B 0 {current_progress_pct:.1f}%, #67C8FF {current_progress_pct:.1f}% 100%);">
                <div class="balance-center">
                    <div class="balance-number">{money(current_saved)}</div>
                    <div class="balance-label">{current_progress_pct:.0f}% of goal</div>
                </div>
            </div>
            <div class="goal-line">Goal: {money(down_payment_goal)} • {money(remaining_to_goal)} to go</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with projection_col:
    p1, p2 = st.columns(2)
    with p1:
        st.markdown(
            f"""
            <div class="projection-card">
                <div class="metric-label">RECURRING PLAN</div>
                <div class="projection-big">{money(biweekly_amount)}</div>
                <div class="metric-note">every 2 weeks • {num_deposits} scheduled deposits</div>
                <div class="blue-chip">Next: {first_deposit.strftime('%b %d')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with p2:
        projected_note = (
            f"{money(abs(projected_over_under))} over goal"
            if projected_over_under >= 0
            else f"{money(abs(projected_over_under))} short of goal"
        )
        st.markdown(
            f"""
            <div class="projection-card">
                <div class="metric-label">PROJECTED BY {target_date.strftime('%b %d').upper()}</div>
                <div class="projection-big">{money(saved_by_target)}</div>
                <div class="metric-note">{projected_progress_pct:.0f}% of the {money(down_payment_goal)} goal</div>
                <div class="blue-chip">{projected_note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.caption("The big ring is the estimated HYSA balance today, including accrued interest. The projection only adds recurring deposits after you switch them on.")

# ---------- Main dashboard ----------
st.subheader("💗 Your December snapshot")
cols = st.columns(4)
metrics = [
    ("Scheduled deposits", f"{num_deposits}", f"{money(biweekly_amount)} every 14 days"),
    ("Projected by target", money(saved_by_target), target_date.strftime("By %b %d, %Y")),
    ("Projected cash down", money(cash_down), f"{(cash_down / out_the_door * 100) if out_the_door else 0:.1f}% of estimated OTD price"),
    ("Payment reduction", money(monthly_savings), "per month vs. $0 cash down"),
]
for col, (label, value, note) in zip(cols, metrics):
    with col:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',
            unsafe_allow_html=True,
        )

st.markdown("### 💖 $0 down vs. using the savings fund")
a, b = st.columns(2)
with a:
    st.markdown("#### If you walked in with $0 down")
    st.metric("Amount financed", money(principal_zero_down))
    st.metric("Estimated monthly payment", f"${payment_zero:,.0f}/mo")
    st.metric("Estimated total interest", money(interest_zero))

with b:
    st.markdown("#### If you use the saved down payment")
    st.metric("Amount financed", money(principal_with_savings), delta=f"-{money(cash_down)} borrowed")
    st.metric("Estimated monthly payment", f"${payment_saved:,.0f}/mo", delta=f"-{money(monthly_savings)}/mo")
    st.metric("Estimated total interest", money(interest_saved), delta=f"-{money(interest_reduction)} interest")

if recurring_enabled:
    st.success(
        f"With the recurring transfer on, the fund is projected to reach about {money(saved_by_target)} by {target_date.strftime('%B %d')}, including estimated HYSA interest. "
        f"That lowers the estimated payment from about {money(payment_zero)}/month to {money(payment_saved)}/month — roughly {money(monthly_savings)} less each month."
    )
else:
    st.info(
        f"You have {money(actual_principal)} in saved deposits right now. Recurring deposits are OFF, so the December projection only includes those deposits plus estimated HYSA growth."
    )

# ---------- Savings schedule ----------
st.markdown("### 🌸 Biweekly savings path")
if recurring_enabled and deposit_dates:
    rows = []
    for i, d in enumerate(deposit_dates, start=1):
        partial_projected = build_projected_ledger(
            deposit_ledger,
            True,
            biweekly_amount,
            first_deposit,
            d,
        )
        running, _ = tiered_savings_balance(
            partial_projected,
            d,
            promo_apy_pct,
            promo_cap,
            above_cap_apy_pct,
        )
        rows.append({"Deposit #": i, "Date": d, "Deposit": biweekly_amount, "Running savings": running})
    schedule = pd.DataFrame(rows)
    chart_df = schedule.set_index("Date")[["Running savings"]]
    st.line_chart(chart_df)
    with st.expander("See every scheduled deposit"):
        st.dataframe(
            schedule.style.format({"Deposit": "${:,.0f}", "Running savings": "${:,.0f}"}),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.info("Recurring deposits are not active yet. Turn them on in Build the plan after you actually set up the automatic transfer.")

# ---------- Scenario table ----------
st.markdown("### 💕 What different biweekly deposits would do")
scenario_amounts = sorted(set([100, 150, 200, 250, 300, 400, 500, 600, int(biweekly_amount)]))
scenario_rows = []
for amount in scenario_amounts:
    scenario_ledger = build_projected_ledger(
        deposit_ledger,
        True,
        amount,
        first_deposit,
        target_date,
    )
    scenario_saved, _ = tiered_savings_balance(
        scenario_ledger,
        target_date,
        promo_apy_pct,
        promo_cap,
        above_cap_apy_pct,
    )
    scenario_down = min(scenario_saved, max(0.0, out_the_door - trade_credit))
    scenario_principal = max(0.0, out_the_door - trade_credit - scenario_down)
    scenario_payment = monthly_payment(scenario_principal, apr, term_months)
    scenario_rows.append(
        {
            "Every 2 weeks": amount,
            "Saved by target": scenario_saved,
            "Amount financed": scenario_principal,
            "Est. payment": scenario_payment,
            "Monthly improvement": payment_zero - scenario_payment,
        }
    )
scenario_df = pd.DataFrame(scenario_rows)
st.dataframe(
    scenario_df.style.format(
        {
            "Every 2 weeks": "${:,.0f}",
            "Saved by target": "${:,.0f}",
            "Amount financed": "${:,.0f}",
            "Est. payment": "${:,.0f}",
            "Monthly improvement": "${:,.0f}",
        }
    ),
    use_container_width=True,
    hide_index=True,
)

# ---------- Live Ascent market scanner ----------
st.markdown("---")
st.markdown("## 🚙 Live Subaru Ascent Value Finder")
st.caption(
    "Scans used Subaru Ascent dealer listings around 48152, then ranks them with transparent math. "
    "Condition scores use listing/history language only — always verify the VIN, title, Carfax/AutoCheck, recalls, and a pre-purchase inspection before buying."
)

with st.expander("🎯 What counts as a great value?", expanded=True):
    v1, v2, v3, v4 = st.columns(4)
    with v1:
        market_radius = st.number_input(
            "Search radius (miles)",
            min_value=5,
            max_value=50,
            value=20,
            step=5,
            key="market_radius",
        )
    with v2:
        preferred_market_price = st.number_input(
            "Preferred max price",
            min_value=10000.0,
            max_value=40000.0,
            value=20000.0,
            step=500.0,
            format="%.0f",
            key="preferred_market_price",
        )
    with v3:
        preferred_market_miles = st.number_input(
            "Preferred max mileage",
            min_value=30000.0,
            max_value=150000.0,
            value=75000.0,
            step=5000.0,
            format="%.0f",
            key="preferred_market_miles",
        )
    with v4:
        ideal_market_miles = st.number_input(
            "Ideal mileage",
            min_value=20000.0,
            max_value=100000.0,
            value=50000.0,
            step=5000.0,
            format="%.0f",
            key="ideal_market_miles",
        )

    exclude_severe_history = st.toggle(
        "Hide salvage / rebuilt / structural-damage listings",
        value=True,
        key="exclude_severe_history",
    )

    st.markdown(
        """
        **Value score = 100 points:** price **30** • mileage **25** • condition/history signals **25** •
        family/road-trip features **15** • model year **5**.

        **Condition is intentionally strict:** if the listing does not actually say clean history, one-owner,
        service records, CPO/inspection, etc., the app treats history as **unknown**, not clean.
        Salvage/rebuilt/structural/frame-damage language is heavily penalized and hidden by default.

        **Family features** include captain's chairs, rear climate, heated rear seats, plentiful USBs,
        power liftgate, EyeSight/adaptive cruise, blind-spot monitoring, rear cross-traffic alert,
        easy-clean/leather seating, and panoramic roof. AWD is not given extra points because it does not
        meaningfully separate one Ascent listing from another.
        """
    )

scan_col, manual_col = st.columns([0.8, 1.2], gap="large")
with scan_col:
    run_market_scan = st.button(
        "🔎 Scan 20-mile market",
        type="primary",
        use_container_width=True,
    )
with manual_col:
    st.caption("The automatic scan uses a dealer-listing marketplace as the discovery layer, then opens listing detail pages for features/history signals.")

if run_market_scan:
    with st.spinner("Scanning nearby Subaru Ascent listings and scoring the best values…"):
        live_listings, market_error = scrape_ascent_market("48152", int(market_radius))
        if live_listings:
            st.session_state.market_results = rank_ascent_listings(
                live_listings,
                preferred_market_price,
                preferred_market_miles,
                ideal_market_miles,
                exclude_severe_history,
            )
            st.session_state.market_error = ""
        else:
            st.session_state.market_results = []
            st.session_state.market_error = market_error

with st.expander("➕ Add a listing the scanner missed"):
    pasted_urls = st.text_area(
        "Paste one or more listing URLs, one per line",
        placeholder="https://dealer-or-marketplace.com/listing/...",
        key="pasted_listing_urls",
    )
    analyze_urls = st.button("Analyze pasted listings", use_container_width=True)
    if analyze_urls:
        manual_listings: list[dict] = []
        errors: list[str] = []
        for line in pasted_urls.splitlines():
            url = line.strip()
            if not url:
                continue
            try:
                parsed_listing = generic_listing_from_url(url)
                if parsed_listing:
                    manual_listings.append(parsed_listing)
                else:
                    errors.append(url)
            except Exception:
                errors.append(url)

        if manual_listings:
            existing = st.session_state.get("market_results", [])
            combined = existing + manual_listings
            st.session_state.market_results = rank_ascent_listings(
                combined,
                preferred_market_price,
                preferred_market_miles,
                ideal_market_miles,
                exclude_severe_history,
            )
        if errors:
            st.warning("Could not read " + str(len(errors)) + " pasted listing(s). Some dealer sites block automated page access.")

market_results = st.session_state.get("market_results", [])
market_error = st.session_state.get("market_error", "")

if market_error:
    st.warning(
        market_error
        + " You can still paste individual listing URLs above and the app will score them."
    )

if market_results:
    visible_results = market_results[:12]
    great_count = sum(1 for item in market_results if item["value_score"] >= 70)
    under_price = sum(1 for item in market_results if item.get("price", 999999) <= preferred_market_price)
    under_miles = sum(1 for item in market_results if item.get("mileage", 999999) <= preferred_market_miles)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Listings ranked", len(market_results))
    m2.metric("Strong / excellent", great_count)
    m3.metric("At or under price goal", under_price)
    m4.metric("At or under mileage goal", under_miles)

    st.markdown("### 🏆 Best current values")
    for rank, item in enumerate(visible_results, start=1):
        price = float(item.get("price") or 0)
        mileage = float(item.get("mileage") or 0)
        score = float(item.get("value_score") or 0)
        dealer = item.get("dealer") or "Dealer"
        distance = item.get("distance")
        distance_text = f"{distance:.0f} mi away" if distance is not None else "distance not shown"
        family_features = item.get("family_features") or []
        positives = item.get("condition_positives") or []
        warnings = item.get("condition_warnings") or []
        score_detail = item.get("score_detail") or {}

        listing_otd = price * (1 + sales_tax_pct / 100) + fees
        listing_down = min(saved_by_target, max(0.0, listing_otd - trade_credit))
        listing_principal = max(0.0, listing_otd - trade_credit - listing_down)
        listing_payment = monthly_payment(listing_principal, apr, term_months)

        with st.container(border=True):
            top_line, score_line = st.columns([1.7, 0.55], vertical_alignment="center")
            with top_line:
                st.markdown(f"#### #{rank} • {item.get('title', 'Subaru Ascent')}")
                st.markdown(
                    f"**{money(price)}** • **{mileage:,.0f} miles** • {dealer} • {distance_text}"
                )
            with score_line:
                st.metric("Value score", f"{score:.0f}/100")
                st.caption(item.get("value_label", ""))

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Price points", f"{score_detail.get('price', 0):.0f}/30")
            c2.metric("Mileage points", f"{score_detail.get('mileage', 0):.0f}/25")
            c3.metric("Condition points", f"{score_detail.get('condition', 0):.0f}/25")
            c4.metric("Family points", f"{score_detail.get('family', 0):.0f}/15")

            if family_features:
                st.markdown("**Road-trip / family features found:** " + " • ".join(family_features[:8]))
            else:
                st.caption("Family-feature detail was not available in the scraped listing text.")

            if positives:
                st.success("History/condition signals: " + " • ".join(positives))
            elif not warnings:
                st.info("Vehicle-history status is unknown from the listing text. Verify it before treating this as a clean-condition vehicle.")

            if warnings:
                st.warning("History warning: " + " • ".join(warnings))

            st.markdown(
                f"With the current savings projection and financing settings, this listing would finance about "
                f"**{money(listing_principal)}** and estimate around **{money(listing_payment)}/month**."
            )

            if item.get("url"):
                st.link_button("Open listing ↗", item["url"], use_container_width=True)

    with st.expander("📊 Compare every ranked listing"):
        comparison_rows = []
        for item in market_results:
            comparison_rows.append(
                {
                    "Score": item.get("value_score"),
                    "Year": item.get("year"),
                    "Vehicle": item.get("title"),
                    "Price": item.get("price"),
                    "Mileage": item.get("mileage"),
                    "Dealer": item.get("dealer"),
                    "Distance": item.get("distance"),
                    "Family features": len(item.get("family_features") or []),
                    "History warnings": "; ".join(item.get("condition_warnings") or []),
                }
            )
        comparison_df = pd.DataFrame(comparison_rows)
        st.dataframe(
            comparison_df.style.format(
                {
                    "Score": "{:.1f}",
                    "Price": "$" + "{:,.0f}",
                    "Mileage": "{:,.0f}",
                    "Distance": lambda x: "" if pd.isna(x) else f"{x:.0f} mi",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("🤖 Free LLM analysis of the top listings"):
        st.caption(
            "The score above is always calculated by the transparent algorithm. "
            "The LLM only explains tradeoffs so it cannot secretly change the ranking."
        )
        try:
            default_hf_token = st.secrets.get("HF_TOKEN", "")
        except Exception:
            default_hf_token = ""

        hf_token = st.text_input(
            "Free Hugging Face token",
            value=default_hf_token,
            type="password",
            help="Optional. A free Hugging Face account/token lets the app ask an open model to summarize the top listings.",
            key="hf_token",
        )
        st.link_button("Get a free Hugging Face token ↗", "https://huggingface.co/settings/tokens")
        if st.button("Ask AI to compare the top 5", use_container_width=True):
            try:
                with st.spinner("AI is reviewing the ranked listings…"):
                    st.session_state.market_ai_summary = ai_market_summary(market_results, hf_token)
            except Exception as exc:
                st.error("AI analysis could not run: " + str(exc))

        if st.session_state.get("market_ai_summary"):
            st.markdown(st.session_state.market_ai_summary)

else:
    st.info(
        "Tap **Scan 20-mile market** to pull current Subaru Ascent listings near 48152. "
        "The scanner only runs when you ask, so it does not slow down the savings dashboard every time you open it."
    )

# ---------- Rate sensitivity ----------
st.markdown("### 💳 When you get your real APR, plug it in")
rate_floor = max(0.0, apr - 6)
rate_ceiling = min(35.0, apr + 6)
rate_points = [round(rate_floor + i * (rate_ceiling - rate_floor) / 6, 2) for i in range(7)]
rate_rows = []
for rate in rate_points:
    pmt = monthly_payment(principal_with_savings, rate, term_months)
    rate_rows.append({"APR": rate, "Monthly payment": pmt, "Total interest": total_interest(pmt, term_months, principal_with_savings)})
rate_df = pd.DataFrame(rate_rows)
st.dataframe(
    rate_df.style.format({"APR": "{:.2f}%", "Monthly payment": "${:,.0f}", "Total interest": "${:,.0f}"}),
    use_container_width=True,
    hide_index=True,
)

# ---------- Deal math ----------
st.markdown("### ✨ Deal math")
d1, d2, d3, d4 = st.columns(4)
d1.metric("Vehicle price", money(car_price))
d2.metric("Estimated sales tax", money(sales_tax))
d3.metric("Fees", money(fees))
d4.metric("Estimated out-the-door", money(out_the_door))

st.caption(
    "Planning tool only. Actual APR, taxes, dealer fees, lender requirements, trade-in tax treatment, warranties/add-ons, and final payment can differ. "
    "The 19.10% default APR is only a benchmark for the 501–600 VantageScore tier from Experian Q2 2026; replace it with your actual prequalified rate."
)
