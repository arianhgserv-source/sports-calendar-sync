#!/usr/bin/env python3
"""Build calendar.ics: upcoming games for tracked teams with an interestingness score.

Data: ESPN public keyless JSON (site.api.espn.com). Only dependency: requests.
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from ics import build_calendar, make_uid  # noqa: E402

BASE = "https://site.api.espn.com/apis/site/v2/sports"
HORIZON_DAYS = 60
ODDS_WINDOW_DAYS = 10  # scoreboard odds only exist close to game time

# league key -> (path, tag, duration minutes, soccer?)
LEAGUES = {
    "nba": ("basketball/nba", "NBA", 150, False),
    "nhl": ("hockey/nhl", "NHL", 150, False),
    "mlb": ("baseball/mlb", "MLB", 180, False),
    "eng.1": ("soccer/eng.1", "EPL", 120, True),
    "usa.1": ("soccer/usa.1", "MLS", 120, True),
}

# Verified against ESPN /teams endpoints.
TEAMS = {
    "nba": {"2": "Boston Celtics", "8": "Detroit Pistons"},
    "nhl": {"1": "Boston Bruins", "7": "Carolina Hurricanes"},
    "mlb": {"2": "Boston Red Sox"},
    "eng.1": {"368": "Everton"},
    "usa.1": {"21300": "Charlotte FC"},
}

# Unordered rivalry pairs by team displayName.
RIVALRIES = [
    {"Boston Red Sox", "New York Yankees"},
    {"Everton", "Liverpool"},
    {"Boston Celtics", "New York Knicks"},
    {"Boston Celtics", "Los Angeles Lakers"},
    {"Boston Celtics", "Philadelphia 76ers"},
    {"Boston Celtics", "Miami Heat"},
    {"Boston Bruins", "Montreal Canadiens"},
    {"Boston Bruins", "Toronto Maple Leafs"},
    {"Carolina Hurricanes", "Washington Capitals"},
    {"Carolina Hurricanes", "New York Rangers"},
    {"Detroit Pistons", "Chicago Bulls"},
    {"Detroit Pistons", "Cleveland Cavaliers"},
    {"Charlotte FC", "Atlanta United FC"},
    {"Charlotte FC", "Inter Miami CF"},
    {"Charlotte FC", "Orlando City SC"},
]

S = requests.Session()
S.headers["User-Agent"] = "sports-calendar-sync/1.0"


def get(url, **params):
    try:
        r = S.get(url, params=params or None, timeout=30)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"warn: {url} failed: {e}", file=sys.stderr)
        return {}


def parse_dt(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def win_pct(summary):
    """'9-6', '9-6-2' (W-L-OTL) or soccer '5-3-2' (W-D-L handled by caller)."""
    nums = [int(x) for x in re.findall(r"\d+", summary or "")]
    if len(nums) < 2:
        return None
    return nums


def record_summary(comp_team):
    for r in comp_team.get("records") or comp_team.get("record") or []:
        if r.get("type") == "total" or r.get("name") == "overall":
            return r.get("summary")
    return None


def team_quality(nums, soccer):
    """0..1 quality from a record list."""
    if not nums:
        return 0.5
    if soccer and len(nums) >= 3:
        w, d, l = nums[:3]
        n = w + d + l
        return (w * 3 + d) / (3 * n) if n else 0.5
    if len(nums) >= 3:  # NHL W-L-OTL
        w, l, o = nums[:3]
        n = w + l + o
        return (w + o * 0.5) / n if n else 0.5
    w, l = nums[:2]
    return w / (w + l) if (w + l) else 0.5


def ml_prob(ml):
    try:
        ml = float(ml)
    except (TypeError, ValueError):
        return None
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def parse_odds(comp):
    """Return dict(spread, home_p, away_p, draw_p, details, ou) or None."""
    odds = comp.get("odds") or []
    if not odds:
        return None
    o = odds[0]
    home = ml_prob((o.get("homeTeamOdds") or {}).get("moneyLine"))
    away = ml_prob((o.get("awayTeamOdds") or {}).get("moneyLine"))
    draw = ml_prob((o.get("drawOdds") or {}).get("moneyLine"))
    spread = o.get("spread")
    try:
        spread = abs(float(spread)) if spread is not None else None
    except (TypeError, ValueError):
        spread = None
    if home is None and away is None and spread is None:
        return None
    return {"spread": spread, "home_p": home, "away_p": away, "draw_p": draw,
            "details": o.get("details"), "ou": o.get("overUnder")}


def score_game(g):
    """Return (score 0-100, label, reasons[])."""
    reasons = []
    q = (g["q_home"] + g["q_away"]) / 2
    quality = max(0.0, min(1.0, (q - 0.30) / 0.40)) * 35
    reasons.append(f"Team quality {quality:.0f}/35 (avg strength {q:.2f})")

    odds, comp_pts, toss = g["odds"], None, False
    if odds:
        if g["soccer"] and odds["home_p"] and odds["away_p"]:
            gap = abs(odds["home_p"] - odds["away_p"])
            comp_pts = max(0.0, 1 - gap / 0.5) * 35
            toss = gap < 0.12
            reasons.append(f"Competitiveness {comp_pts:.0f}/35 (3-way win-prob gap {gap:.2f})")
        elif g["league"] in ("nba",) and odds["spread"] is not None:
            comp_pts = max(0.0, 1 - max(0, odds["spread"] - 1) / 12) * 35
            toss = odds["spread"] <= 3.5
            reasons.append(f"Competitiveness {comp_pts:.0f}/35 (spread {odds['spread']:g})")
        elif odds["home_p"] and odds["away_p"]:
            gap = abs(odds["home_p"] - odds["away_p"])
            comp_pts = max(0.0, 1 - gap / 0.4) * 35
            toss = gap < 0.10
            reasons.append(f"Competitiveness {comp_pts:.0f}/35 (moneyline gap {gap:.2f})")
    if comp_pts is None:
        gap = abs(g["q_home"] - g["q_away"])
        comp_pts = max(0.0, 1 - gap / 0.4) * 20  # capped: estimate only
        reasons.append(f"Competitiveness {comp_pts:.0f}/20 (est. from records; odds not posted yet)")

    ctx = 0.0
    names = {g["home"], g["away"]}
    if g["tracked_vs_tracked"]:
        ctx += 15
        reasons.append("+15 tracked vs tracked")
    if any(names == r for r in RIVALRIES):
        ctx += 12
        reasons.append("+12 rivalry")
    if g["conference"]:
        ctx += 5
        reasons.append("+5 division/conference game")
    if g["postseason"]:
        ctx += 10
        reasons.append("+10 postseason")
    ctx = min(ctx, 30)

    score = int(round(min(100, quality + comp_pts + ctx)))
    label = None
    if score >= 80:
        label = "Must-Watch"
    elif g["tracked_vs_tracked"]:
        label = "Tracked vs Tracked"
    elif any(names == r for r in RIVALRIES):
        label = "Rivalry"
    elif toss:
        label = "Toss-up"
    return score, label, reasons


def team_records(path, tid):
    d = get(f"{BASE}/{path}/teams/{tid}").get("team", {})
    rec = None
    for it in (d.get("record") or {}).get("items", []):
        if it.get("type") == "total":
            rec = it.get("summary")
    return rec, d.get("standingSummary")


def main():
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=HORIZON_DAYS)
    events = []
    for league, (path, tag, dur, soccer) in LEAGUES.items():
        tracked = TEAMS[league]
        games = {}
        for tid in tracked:
            # soccer's default schedule is results-only; fixture=true returns upcoming matches
            extra = {"fixture": "true"} if soccer else {}
            for ev in get(f"{BASE}/{path}/teams/{tid}/schedule", **extra).get("events", []):
                try:
                    start = parse_dt(ev["date"])
                except (KeyError, ValueError):
                    continue
                comp = ev["competitions"][0]
                if not (now <= start <= end) or comp["status"]["type"].get("completed"):
                    continue
                games[ev["id"]] = (ev, comp, start)  # dict key dedups tracked-vs-tracked

        # scoreboard for odds / current records / broadcasts near-term
        sb = {}
        for off in range(ODDS_WINDOW_DAYS + 1):  # ESPN rejects date ranges; one call per day
            day = f"{now + timedelta(days=off):%Y%m%d}"
            for e in get(f"{BASE}/{path}/scoreboard", dates=day).get("events", []):
                sb[e["id"]] = e["competitions"][0]

        rec_cache = {}
        for gid, (ev, comp, start) in games.items():
            sbc = sb.get(gid, {})
            by = {c["homeAway"]: c for c in comp["competitors"]}
            sby = {c["homeAway"]: c for c in sbc.get("competitors", [])}
            side = {}
            for ha in ("home", "away"):
                team = by[ha]["team"]
                tid = team["id"]
                summ = record_summary(sby.get(ha, {})) or record_summary(by[ha])
                if not summ:
                    if tid not in rec_cache:
                        rec_cache[tid] = team_records(path, tid)
                    summ = rec_cache[tid][0]
                side[ha] = (team["displayName"], tid, summ)
            bc = sbc.get("broadcasts") or comp.get("broadcasts") or []
            nets = sorted({n for b in bc for n in (b.get("names") or [])})
            g = {
                "league": league, "soccer": soccer,
                "home": side["home"][0], "away": side["away"][0],
                "q_home": team_quality(win_pct(side["home"][2]), soccer),
                "q_away": team_quality(win_pct(side["away"][2]), soccer),
                "odds": parse_odds(sbc) or parse_odds(comp),
                "tracked_vs_tracked": side["home"][1] in tracked and side["away"][1] in tracked,
                "conference": bool(sbc.get("conferenceCompetition") or comp.get("conferenceCompetition")),
                "postseason": ev.get("seasonType", {}).get("type") in (3, 4) or
                              str(ev.get("seasonType", {}).get("id")) in ("3", "4"),
            }
            score, label, reasons = score_game(g)
            tail = f"{score}/100" + (f" - {label}" if label else "")
            if soccer:
                title = f"[{tag}] {g['away']} (A) @ {g['home']} (H) ({tail})"
            else:
                title = f"[{tag}] {g['away']} @ {g['home']} ({tail})"
            o = g["odds"]
            odds_line = "Odds: not posted yet"
            if o:
                bits = [o["details"] or (f"spread {o['spread']:g}" if o["spread"] is not None else None)]
                if o["ou"]:
                    bits.append(f"O/U {o['ou']}")
                odds_line = "Odds: " + ", ".join(b for b in bits if b)
            venue = (comp.get("venue") or {}).get("fullName", "")
            desc = "\n".join([
                f"{g['away']} ({side['away'][2] or 'n/a'}) at {g['home']} ({side['home'][2] or 'n/a'})",
                odds_line,
                "Broadcast: " + (", ".join(nets) if nets else "TBD"),
                "",
                f"Interest score {score}/100" + (f" ({label})" if label else ""),
                *[f"- {r}" for r in reasons],
            ])
            events.append({
                "uid": make_uid(league, gid), "start": start, "duration_minutes": dur,
                "summary": title, "description": desc, "location": venue,
            })

    events.sort(key=lambda e: (e["start"], e["uid"]))
    Path(__file__).with_name("calendar.ics").write_bytes(
        build_calendar(events, name="Sports").encode("utf-8")
    )
    print(f"wrote {len(events)} events")


if __name__ == "__main__":
    main()
