# sports-calendar-sync

Daily-generated `.ics` feed of upcoming games for 7 tracked teams, each scored 0-100 for "interestingness". Served at https://sports.houissa.com/calendar.ics for Google Calendar "From URL".

## Run / test
- `python3 -m venv .venv && .venv/bin/pip install requests`
- `.venv/bin/python generate.py` writes `calendar.ics`
- `cd scripts && python3 -m unittest` runs the ICS builder tests

## Layout
- `generate.py`: ESPN fetch, odds parsing, scoring, event formatting
- `scripts/ics.py`: stdlib RFC 5545 builder (folding, escaping, deterministic UIDs and DTSTAMP)
- `worker/`: Cloudflare Worker (`sports.houissa.com` custom domain) proxying the raw GitHub `calendar.ics` with `text/calendar` headers
- `.github/workflows/update_calendar.yml`: daily 11:00 UTC regenerate and commit `calendar.ics`

## Secrets
None in the repo or in GitHub. The Worker was deployed through the Cloudflare API with the local Cloudflare MCP session. Never commit tokens.

## Conventions
- Repo: `arianhgserv-source/sports-calendar-sync` (public; the Worker reads it via raw.githubusercontent.com).
- UIDs are `{league}-{espnGameId}@sports.houissa.com`; never change this format (Google would duplicate events).
- Team IDs are hardcoded in `TEAMS` (verified against ESPN): NBA 2/8, NHL 1/7, MLB 2, EPL 368, MLS 21300.

## Gotchas
- ESPN scoreboard rejects date ranges (HTTP 400); query one `dates=YYYYMMDD` per day.
- Soccer team schedule is results-only unless `?fixture=true`.
- Odds are only posted about 1-3 days before a game; further out the score uses record-based competitiveness, capped lower.
- Do not touch the existing `houissa.com` root, other subdomains, or other Workers.
- The apex `*.houissa.com` wildcard A record exists; the Worker custom domain adds a specific `sports` record.
