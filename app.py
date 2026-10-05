import json
import os
import random
from datetime import date, datetime
from pathlib import Path
from flask import Flask, redirect, render_template, request, session, url_for
from zoneinfo import ZoneInfo
import threading
import time
from scripts.fetch_youtube_stats import fetch_channel, load_json, HANDLES_PATH, OVERRIDES_PATH
import redis

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-to-a-random-secret-in-production")

DATA_PATH = Path(__file__).parent / "data" / "creators.json"
with open(DATA_PATH, encoding="utf-8") as f:
    CREATORS = json.load(f)


# --- Redis setup ---------------------------------------------------------
# If REDIS_URL isn't set (e.g. running locally without Redis), r is None and
# every Redis call is skipped. If Redis goes down, the game keeps working.
REDIS_URL = os.environ.get("REDIS_URL")
r = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


def redis_call(fn):
    """Run a Redis command; skip quietly if Redis isn't set up or is down."""
    if r is None:
        return None
    try:
        return fn()
    except redis.RedisError as e:
        print(f"[redis] {e}")
        return None


# On startup, use the last refreshed stats if Redis has them. The length check
# matters: daily_index() depends on len(CREATORS), so a different-sized list
# would reshuffle the answers.
cached = redis_call(lambda: r.get("creators:latest"))
if cached:
    cached = json.loads(cached)
    if len(cached) == len(CREATORS):
        CREATORS = cached
        print(f"[redis] loaded cached stats for {len(CREATORS)} creators")


REFRESH_SECONDS = 6 * 60 * 60  # every 6 hours


def refresh_creators():
    global CREATORS
    handles = [
        line.strip()
        for line in HANDLES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    overrides = load_json(OVERRIDES_PATH, {})

    fresh = []
    for handle in handles:
        try:
            data = fetch_channel(handle)
        except Exception as e:
            print(f"[refresh] {handle} failed: {e} — keeping old stats")
            return
        if data is None:
            return
        override = overrides.get(handle, {})
        data["gender"] = override.get("gender", "Unknown")
        data["niche"] = override.get("niche", "Unknown")
        del data["handle"]
        fresh.append(data)

    if len(fresh) == len(CREATORS):
        CREATORS = fresh
        redis_call(lambda: r.set("creators:latest", json.dumps(fresh)))
        print(f"[refresh] updated stats for {len(fresh)} creators")


def refresh_loop():
    while True:
        refresh_creators()
        time.sleep(REFRESH_SECONDS)


if os.environ.get("API_KEY"):
    threading.Thread(target=refresh_loop, daemon=True).start()

EPOCH = date(2024, 1, 1)
MAX_GUESSES = 6

PUZZLE_START = date(2026, 9, 27)  # Sept 27 = #1, so today (Sept 30) = #4

MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June",
          "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]

def puzzle_number() -> int:
    # Uses Eastern time (today()) so the number rolls over with the answer
    return (today() - PUZZLE_START).days + 1

def pretty_date(d: date) -> str:
    return f"{d.strftime('%A')}, {MONTHS[d.month - 1]} {d.day}, {d.year}"

def today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()

# Salt for the shuffle seed. Changing this reshuffles every cycle's order —
# only do that intentionally (e.g. if you ever want to "reset" the sequence).
SHUFFLE_SALT = "tubedle-v1"


def daily_index() -> int:
    """
    Same creator for everyone, changes once per day, and the order isn't
    just the raw list order. Each block of len(CREATORS) days is one
    "cycle" — every creator appears exactly once per cycle (no repeats
    within a cycle), but each cycle gets its own random-looking shuffle
    that's deterministic (same for every player, reproducible from the
    date) rather than truly random per request.
    """
    n = len(CREATORS)
    days_since_epoch = (today() - EPOCH).days
    cycle_number = days_since_epoch // n
    day_in_cycle = days_since_epoch % n

    order = list(range(n))
    random.Random(f"{SHUFFLE_SALT}-{cycle_number}").shuffle(order)
    return order[day_in_cycle]


def find_creator(name: str):
    return next((c for c in CREATORS if c["name"].lower() == name.lower()), None)


def current_answer():
    return CREATORS[daily_index()]


CONTINENTS = {
    "USA": "North America",
    "Canada": "North America",
    "UK": "Europe",
    "Ireland": "Europe",
    "Germany": "Europe",
    "Sweden": "Europe",
    "Netherlands": "Europe",
    "Japan": "Asia"
}


def compare(guess: dict, answer: dict) -> dict:
    def numeric_field(key, pct_threshold=None, abs_threshold=None):
        diff = guess[key] - answer[key]
        if diff == 0:
            return {"value": guess[key], "status": "hit", "arrow": ""}

        arrow = "↑" if diff < 0 else "↓"  # still shown for direction, just not color-coded

        is_close = False
        if abs_threshold is not None:
            is_close = abs(diff) <= abs_threshold
        elif pct_threshold is not None and answer[key]:
            is_close = abs(diff) / answer[key] <= pct_threshold

        status = "close" if is_close else "neutral"
        return {"value": guess[key], "status": status, "arrow": arrow}

    def country_field():
        exact = guess["country"] == answer["country"]
        if exact:
            status = "hit"
        else:
            same_continent = CONTINENTS.get(guess["country"]) == CONTINENTS.get(answer["country"])
            status = "close" if same_continent else "neutral"
        return {"value": guess["country"], "status": status}

    def exact_field(key):
        exact = guess[key] == answer[key]
        return {"value": guess[key], "status": "hit" if exact else "neutral"}

    return {
        "name": guess["name"],
        "subs": numeric_field("subs", pct_threshold=0.10),
        "started": numeric_field("started", abs_threshold=2),
        "videos": numeric_field("videos", pct_threshold=0.10),
        "country": country_field(),
        "gender": exact_field("gender"),
        "niche": exact_field("niche"),
        "won": guess["name"] == answer["name"],
    }


def reset_daily_round():
    session["game_date"] = today().isoformat()
    session["guesses"] = []
    session["game_over"] = False
    session["won"] = False
    session["view"] = "daily"
    session.pop("bonus_answer", None)
    session.pop("bonus_guesses", None)
    session.pop("bonus_game_over", None)
    session.pop("bonus_won", None)


def ensure_current_round():
    """Start a fresh daily round automatically whenever the date has rolled
    over, and drop any in-progress bonus round from a previous day."""
    if session.get("game_date") != today().isoformat():
        reset_daily_round()


def record_play():
    """Count each browser once per day when it opens the daily puzzle."""
    d = today().isoformat()
    if session.get("counted_date") != d:
        session["counted_date"] = d
        redis_call(lambda: r.incr(f"plays:{d}"))


def record_result():
    """Record how a finished daily game ended: number of guesses, or X for a loss."""
    d = today().isoformat()
    result_key = str(len(session["guesses"])) if session["won"] else "X"
    redis_call(lambda: r.hincrby(f"results:{d}", result_key, 1))


def start_bonus_round():
    """Pick a genuinely random creator, different from today's actual daily
    answer, independent of the deterministic daily-order logic."""
    today_answer_name = current_answer()["name"]
    choices = [c["name"] for c in CREATORS if c["name"] != today_answer_name]
    session["bonus_answer"] = random.choice(choices)
    session["bonus_guesses"] = []
    session["bonus_game_over"] = False
    session["bonus_won"] = False
    session["view"] = "bonus"

def render_game(view):
    if view == "bonus":
        guesses = session["bonus_guesses"]
        game_over = session["bonus_game_over"]
        won = session["bonus_won"]
        answer_name = session["bonus_answer"]
    else:
        guesses = session["guesses"]
        game_over = session["game_over"]
        won = session["won"]
        answer_name = current_answer()["name"]

    guessed_names = {g["name"] for g in guesses}
    remaining_names = sorted(c["name"] for c in CREATORS if c["name"] not in guessed_names)
    revealed_answer = answer_name if (game_over and not won) else None

    return render_template(
        "index.html",
        view=view,
        guesses=guesses,
        guess_count=len(guesses),
        max_guesses=MAX_GUESSES,
        game_over=game_over,
        won=won,
        names=remaining_names,
        revealed_answer=revealed_answer,
        daily_won=session.get("won", False),
        daily_game_over=session.get("game_over", False),
        today_label=pretty_date(today()),
        puzzle_number=puzzle_number(),
    )

@app.route("/")
def index():
    ensure_current_round()
    record_play()
    return render_game("daily")


@app.route("/bonus")
def bonus():
    ensure_current_round()
    if "bonus_answer" not in session:
        return redirect(url_for("index"))
    return render_game("bonus")

@app.route("/guess", methods=["POST"])
def guess():
    ensure_current_round()

    if not session["game_over"]:
        name = request.form.get("creator_name", "")
        creator = find_creator(name)
        if creator and creator["name"] not in {g["name"] for g in session["guesses"]}:
            answer = current_answer()
            result = compare(creator, answer)
            session["guesses"] = session["guesses"] + [result]
            if result["won"]:
                session["game_over"] = True
                session["won"] = True
            elif len(session["guesses"]) >= MAX_GUESSES:
                session["game_over"] = True
                session["won"] = False

            # Runs once per player: only on the guess that ends the game
            if session["game_over"]:
                record_result()

    return redirect(url_for("index"))


@app.route("/bonus/start", methods=["POST"])
def bonus_start():
    ensure_current_round()
    start_bonus_round()
    return redirect(url_for("bonus"))

@app.route("/bonus/guess", methods=["POST"])
def bonus_guess():
    ensure_current_round()

    if "bonus_answer" in session and not session["bonus_game_over"]:
        name = request.form.get("creator_name", "")
        creator = find_creator(name)
        if creator and creator["name"] not in {g["name"] for g in session["bonus_guesses"]}:
            answer = find_creator(session["bonus_answer"])
            result = compare(creator, answer)
            session["bonus_guesses"] = session["bonus_guesses"] + [result]
            if result["won"]:
                session["bonus_game_over"] = True
                session["bonus_won"] = True
            elif len(session["bonus_guesses"]) >= MAX_GUESSES:
                session["bonus_game_over"] = True
                session["bonus_won"] = False

    return redirect(url_for("bonus"))

@app.route("/view-daily", methods=["POST"])
def view_daily():
    ensure_current_round()
    session["view"] = "daily"
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001)