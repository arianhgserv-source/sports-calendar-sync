"""Stdlib-only iCalendar (RFC 5545) builder for the sports calendar sync.

All output uses CRLF line endings and is deterministic: values that would
normally depend on wall-clock time (notably DTSTAMP) are derived from the
event's start time instead.
"""

from datetime import timedelta, timezone

FOLD_LIMIT = 75  # octets per physical line, excluding the CRLF itself
PRODID = "-//sports.houissa.com//Sports Calendar Sync//EN"


def fold_line(line):
    """Fold *line* at 75 UTF-8 octets using CRLF followed by a single space.

    Folding never splits a multibyte character. The first physical line may
    hold up to 75 octets; continuation lines reserve one octet for the
    leading space and therefore hold up to 74 octets of content.
    """
    if line is None:
        return ""
    if not isinstance(line, str):
        line = str(line)

    chunks = []
    current = []
    current_len = 0
    max_len = FOLD_LIMIT

    for char in line:
        char_len = len(char.encode("utf-8"))
        if current and current_len + char_len > max_len:
            chunks.append("".join(current))
            current = []
            current_len = 0
            max_len = FOLD_LIMIT - 1  # leave room for the leading space
        current.append(char)
        current_len += char_len

    chunks.append("".join(current))
    return "\r\n ".join(chunks)


def escape_text(s):
    """Escape *s* as an RFC 5545 TEXT value.

    Backslash is escaped first so that escapes added for other characters are
    not double-escaped. CR, LF and CRLF are all normalized to the literal
    two-character sequence ``\\n``.
    """
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)

    s = s.replace("\\", "\\\\")
    s = s.replace(";", "\\;")
    s = s.replace(",", "\\,")
    s = s.replace("\r\n", "\\n")
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\n")
    return s


def make_uid(league, game_id):
    """Return a stable, globally unique UID for a game."""
    return f"{league}-{game_id}@sports.houissa.com"


def _format_utc(dt):
    """Format an aware datetime as an iCalendar UTC timestamp."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_calendar(events, name="Sports"):
    """Build a complete VCALENDAR string from an iterable of event dicts.

    Each event must provide ``uid``, ``start`` (an aware datetime),
    ``duration_minutes``, ``summary`` and ``description``. ``location`` is
    optional. The returned string uses CRLF line endings and ends with CRLF.
    """
    lines = [
        "BEGIN:VCALENDAR",
        f"PRODID:{PRODID}",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(name)}",
        "X-WR-TIMEZONE:UTC",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]

    for event in events:
        start = event["start"]
        end = start + timedelta(minutes=event["duration_minutes"])
        stamp = _format_utc(start)  # deterministic: tied to start, not now

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event['uid']}",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{_format_utc(start)}",
                f"DTEND:{_format_utc(end)}",
                "SEQUENCE:0",
                f"SUMMARY:{escape_text(event['summary'])}",
                f"DESCRIPTION:{escape_text(event['description'])}",
            ]
        )

        if event.get("location") is not None:
            lines.append(f"LOCATION:{escape_text(event['location'])}")

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"
