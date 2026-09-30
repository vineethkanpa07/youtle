"""
Pulls live subscriber count, video count, channel start year, and country
from the YouTube Data API v3 for every handle listed in data/handles.txt,
merges in your manually-curated gender/niche tags, and rewrites
data/creators.json.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional — falls back to already-exported env vars

ROOT = Path(__file__).parent.parent
HANDLES_PATH = ROOT / "data" / "handles.txt"
OVERRIDES_PATH = ROOT / "data" / "manual_overrides.json"
OUTPUT_PATH = ROOT / "data" / "creators.json"

API_KEY = os.environ.get("API_KEY")
API_URL = "https://www.googleapis.com/youtube/v3/channels"

# YouTube's API returns ISO 3166-1 alpha-2 codes (US, GB, DE...), but the
# game (and its continent-matching logic in app.py) uses friendly names.
# Add to this as your creator list grows into new countries.
COUNTRY_CODE_MAP = {
    "US": "USA",
    "CA": "Canada",
    "GB": "UK",
    "IE": "Ireland",
    "DE": "Germany",
    "SE": "Sweden",
    "NL": "Netherlands",
    "JP": "Japan"
}

# Only needed as a last resort, for creators whose channel doesn't set a
# country at all — snippet.country is genuinely blank for a lot of channels.
COUNTRY_FALLBACK = {"@lillysingh": "Canada"}


def fetch_channel(handle: str) -> dict | None:
    """One API call per handle (channels.list supports forHandle)."""
    params = {
        "part": "snippet,statistics",
        "forHandle": handle.lstrip("@"),
        "key": API_KEY,
    }
    resp = requests.get(API_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    items = data.get("items", [])
    if not items:
        print(f"  [!] No channel found for {handle} — skipping")
        return None

    item = items[0]
    snippet = item["snippet"]
    stats = item["statistics"]

    raw_country = snippet.get("country")
    if raw_country:
        country = COUNTRY_CODE_MAP.get(raw_country, raw_country)
    else:
        country = COUNTRY_FALLBACK.get(handle, "Unknown")

    return {
        "handle": handle,
        "name": snippet["title"],
        "subs": round(int(stats.get("subscriberCount", 0)) / 1_000_000, 1),
        "country": country,
        "started": int(snippet["publishedAt"][:4]),
        "videos": int(stats.get("videoCount", 0)),
    }


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    if not API_KEY:
        print("Set API_KEY as an environment variable first.")
        sys.exit(1)

    if not HANDLES_PATH.exists():
        print(f"Missing {HANDLES_PATH}. Create it with one @handle per line.")
        sys.exit(1)

    handles = [
        line.strip()
        for line in HANDLES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    overrides = load_json(OVERRIDES_PATH, {})

    creators = []
    for i, handle in enumerate(handles, start=1):
        print(f"[{i}/{len(handles)}] Fetching {handle}...")
        try:
            data = fetch_channel(handle)
        except requests.HTTPError as e:
            print(f"  [!] API error for {handle}: {e} — skipping")
            continue

        if data is None:
            continue

        override = overrides.get(handle, {})
        data["gender"] = override.get("gender", "Unknown")
        data["niche"] = override.get("niche", "Unknown")
        del data["handle"]
        creators.append(data)

        time.sleep(0.1)  # stay polite to the API, not strictly required
    
    if not creators:
        print("\nNo creators fetched — leaving existing creators.json untouched.")
        sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:

        json.dump(creators, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(creators)} creators to {OUTPUT_PATH}")
    missing_tags = [c["name"] for c in creators if c["gender"] == "Unknown" or c["niche"] == "Unknown"]
    if missing_tags:
        print(f"\n{len(missing_tags)} creators have no gender/niche override yet:")
        for name in missing_tags[:20]:
            print(f"  - {name}")
        if len(missing_tags) > 20:
            print(f"  ...and {len(missing_tags) - 20} more")
        print(f"Add them to {OVERRIDES_PATH}")


if __name__ == "__main__":
    main()