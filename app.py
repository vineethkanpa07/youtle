import json
import os
import random
from datetime import date
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-to-a-random-secret-in-production")

DATA_PATH = Path(__file__).parent / "data" / "creators.json"
with open(DATA_PATH, encoding="utf-8") as f:
    CREATORS = json.load(f)

EPOCH = date(2024, 1, 1)
MAX_GUESSES = 6


def daily_index() -> int:
    """Same creator for everyone, changes once per day."""
    days_since_epoch = (date.today() - EPOCH).days
    return days_since_epoch % len(CREATORS)


def find_creator(name: str):
    return next((c for c in CREATORS if c["name"].lower() == name.lower()), None)


def current_answer():
    if session.get("mode") == "practice":
        name = session.get("practice_answer")
        return find_creator(name) if name else CREATORS[daily_index()]
    return CREATORS[daily_index()]


CONTINENTS = {
    "USA": "North America",
    "Canada": "North America",
    "UK": "Europe",
    "Ireland": "Europe",
    "Germany": "Europe",
    "Sweden": "Europe",
    "Netherlands": "Europe",
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


def reset_round(mode="daily"):
    session["mode"] = mode
    session["guesses"] = []
    session["game_over"] = False
    session["won"] = False
    if mode == "practice":
        current = session.get("practice_answer")
        choices = [c["name"] for c in CREATORS if c["name"] != current] or [c["name"] for c in CREATORS]
        session["practice_answer"] = random.choice(choices)


@app.route("/")
def index():
    if "guesses" not in session:
        reset_round("daily")

    guessed_names = {g["name"] for g in session["guesses"]}
    remaining_names = sorted(c["name"] for c in CREATORS if c["name"] not in guessed_names)

    revealed_answer = None
    if session.get("game_over") and not session.get("won"):
        revealed_answer = current_answer()["name"]

    return render_template(
        "index.html",
        guesses=session["guesses"],
        guess_count=len(session["guesses"]),
        max_guesses=MAX_GUESSES,
        game_over=session.get("game_over", False),
        won=session.get("won", False),
        names=remaining_names,
        revealed_answer=revealed_answer,
    )


@app.route("/guess", methods=["POST"])
def guess():
    if "guesses" not in session:
        reset_round("daily")

    if not session.get("game_over"):
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

    return redirect(url_for("index"))


@app.route("/new-game", methods=["POST"])
def new_game():
    reset_round("practice")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")