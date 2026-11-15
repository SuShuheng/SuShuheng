from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = ROOT / "data" / "star-events.csv"
SNAPSHOTS_PATH = ROOT / "data" / "star-history-snapshots.csv"
DARK_OUTPUT = ROOT / "data" / "star-history-dark.svg"
LIGHT_OUTPUT = ROOT / "data" / "star-history-light.svg"
USER = "SuShuheng"
USER_AGENT = "SuShuheng-profile-metrics/1.0"
API_BASE = "https://api.github.com"

THEMES = {
    "dark": {
        "bg_start": "#07131a",
        "bg_mid": "#0b1020",
        "bg_end": "#151027",
        "line_start": "#5eead4",
        "line_mid": "#7dd3fc",
        "line_end": "#a78bfa",
        "grid": "#334155",
        "axis": "#7c8ba1",
        "eyebrow": "#5eead4",
        "total": "#f8fafc",
        "caption": "#94a3b8",
        "halo_teal": "#5eead4",
        "halo_purple": "#a78bfa",
        "end_dot": "#f8fafc",
        "end_glow": "#a78bfa",
    },
    "light": {
        "bg_start": "#f8fafc",
        "bg_mid": "#eef8f6",
        "bg_end": "#f7f2ff",
        "line_start": "#0d9488",
        "line_mid": "#0ea5e9",
        "line_end": "#7c3aed",
        "grid": "#d0d7de",
        "axis": "#59636e",
        "eyebrow": "#0f766e",
        "total": "#1f2328",
        "caption": "#57606a",
        "halo_teal": "#99f6e4",
        "halo_purple": "#ddd6fe",
        "end_dot": "#0f172a",
        "end_glow": "#7c3aed",
    },
}


def fetch_json(
    url: str,
    token: str | None = None,
    accept: str = "application/vnd.github+json",
    attempts: int = 5,
) -> dict | list:
    last_error: Exception | None = None
    headers = {
        "Accept": accept,
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(attempts):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as error:
            last_error = error
            if error.code in (429, 403):
                retry_after = error.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 8.0
                time.sleep(delay * (attempt + 1))
            elif attempt + 1 < attempts:
                time.sleep(2.0 * (attempt + 1))
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def fetch_with_curl(
    url: str,
    token: str | None,
    accept: str,
) -> list[dict]:
    curl = shutil.which("curl")
    if not curl:
        return []
    command = [
        curl,
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--retry",
        "3",
        "--max-time",
        "45",
        "-H",
        f"Accept: {accept}",
        "-H",
        f"User-Agent: {USER_AGENT}",
    ]
    if token:
        command.extend(["-H", f"Authorization: Bearer {token}"])
    command.append(url)
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Invalid JSON response from {url}: {result.stdout[:300]}"
        ) from error
    return value if isinstance(value, list) else []


def github_json(
    url: str,
    token: str,
    accept: str = "application/vnd.github+json",
) -> list[dict]:
    try:
        value = fetch_json(url, token, accept)
        if isinstance(value, list):
            return value
        raise RuntimeError(f"Expected a list from {url}")
    except RuntimeError:
        return fetch_with_curl(url, token, accept)


def fetch_public_star_total(token: str | None) -> int:
    repos: list[dict] = []
    page = 1
    while True:
        batch = github_json(
            f"{API_BASE}/users/{USER}/repos?per_page=100&type=owner&page={page}",
            token,
        )
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    return sum(
        int(repo.get("stargazers_count", 0))
        for repo in repos
        if not repo.get("private")
    )


def read_events() -> list[dict[str, str]]:
    with EVENTS_PATH.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def seed_snapshots(events: list[dict[str, str]]) -> list[tuple[date, int]]:
    counts = Counter(
        date.fromisoformat(row["StarredAt"][:10]) for row in events
    )
    points: list[tuple[date, int]] = []
    total = 0
    for event_date in sorted(counts):
        total += counts[event_date]
        points.append((event_date, total))
    return points


def read_snapshots() -> list[tuple[date, int]]:
    if not SNAPSHOTS_PATH.exists():
        return seed_snapshots(read_events())
    with SNAPSHOTS_PATH.open(encoding="utf-8", newline="") as handle:
        return sorted(
            (
                date.fromisoformat(row["Date"]),
                int(row["TotalStars"]),
            )
            for row in csv.DictReader(handle)
        )


def write_snapshots(points: list[tuple[date, int]]) -> None:
    SNAPSHOTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOTS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Date", "TotalStars"])
        writer.writeheader()
        writer.writerows(
            {"Date": day.isoformat(), "TotalStars": total}
            for day, total in points
        )


def month_labels(first_day: date, last_day: date) -> list[tuple[date, str]]:
    months: list[date] = []
    cursor = first_day.replace(day=1)
    final_month = last_day.replace(day=1)
    while cursor <= final_month:
        months.append(cursor)
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    if len(months) <= 7:
        selected = months
    else:
        step = (len(months) - 1) / 6
        selected = [months[round(index * step)] for index in range(7)]
    return [(day, day.strftime("%b")) for day in selected]


def render(points: list[tuple[date, int]], theme_name: str) -> str:
    theme = THEMES[theme_name]
    total = points[-1][1]
    today = datetime.now(timezone.utc).date()
    first_day = points[0][0]
    last_day = max(today, points[-1][0])
    width, height = 1200, 420
    left, right, top, bottom = 80, 48, 112, 64
    plot_width = width - left - right
    plot_height = height - top - bottom
    span = max((last_day - first_day).days, 1)
    y_max = max(24, ((total + 5) // 5) * 5)

    def x_for(day: date) -> float:
        return left + (day - first_day).days / span * plot_width

    def y_for(value: int) -> float:
        return top + plot_height - value / y_max * plot_height

    step_parts = [f"M {left:.2f} {y_for(0):.2f}"]
    previous_y = y_for(0)
    for day, value in points:
        x = x_for(day)
        y = y_for(value)
        step_parts.append(f"L {x:.2f} {previous_y:.2f}")
        step_parts.append(f"L {x:.2f} {y:.2f}")
        previous_y = y
    step_parts.append(f"L {left + plot_width:.2f} {previous_y:.2f}")
    line_path = " ".join(step_parts)
    area_path = (
        f"{line_path} L {left + plot_width:.2f} {top + plot_height:.2f} "
        f"L {left:.2f} {top + plot_height:.2f} Z"
    )

    grid = []
    for value in range(0, y_max + 1, 5):
        y = y_for(value)
        grid.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" '
            f'y2="{y:.2f}" class="grid" />'
        )
        grid.append(
            f'<text x="{left - 14}" y="{y + 4:.2f}" text-anchor="end" '
            f'class="axis">{value}</text>'
        )

    labels = []
    for day, label in month_labels(first_day, last_day):
        clamped = min(max(day, first_day), last_day)
        labels.append(
            f'<text x="{x_for(clamped):.2f}" y="{top + plot_height + 30}" '
            f'text-anchor="middle" class="axis">{escape(label)}</text>'
        )

    final_x = x_for(points[-1][0])
    final_y = y_for(total)
    range_label = f"{first_day.strftime('%b %Y')} — {last_day.strftime('%b %Y')}"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Star history across public repositories</title>
  <desc id="desc">A {theme_name}-theme chart showing {total} GitHub stars accumulated across public repositories.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{theme["bg_start"]}" />
      <stop offset="0.55" stop-color="{theme["bg_mid"]}" />
      <stop offset="1" stop-color="{theme["bg_end"]}" />
    </linearGradient>
    <linearGradient id="line" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{theme["line_start"]}" />
      <stop offset="0.62" stop-color="{theme["line_mid"]}" />
      <stop offset="1" stop-color="{theme["line_end"]}" />
    </linearGradient>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{theme["line_start"]}" stop-opacity="0.28" />
      <stop offset="1" stop-color="{theme["line_start"]}" stop-opacity="0" />
    </linearGradient>
    <filter id="glow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="5" result="blur" />
      <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
    </filter>
    <style>
      .eyebrow {{ font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; letter-spacing: 2.4px; fill: {theme["eyebrow"]}; }}
      .total {{ font: 700 44px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: {theme["total"]}; }}
      .caption {{ font: 500 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: {theme["caption"]}; }}
      .grid {{ stroke: {theme["grid"]}; stroke-width: 1; stroke-dasharray: 3 7; opacity: .65; }}
      .axis {{ font: 500 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: {theme["axis"]}; }}
    </style>
  </defs>
  <rect width="{width}" height="{height}" rx="24" fill="url(#bg)" />
  <circle cx="1080" cy="40" r="190" fill="{theme["halo_teal"]}" opacity=".06" />
  <circle cx="150" cy="390" r="180" fill="{theme["halo_purple"]}" opacity=".06" />
  <text x="{left}" y="43" class="eyebrow">STARS OVER TIME</text>
  <text x="{left}" y="91" class="total">{total}</text>
  <text x="{left + 58}" y="88" class="caption">public stars</text>
  <text x="{left + plot_width}" y="43" text-anchor="end" class="caption">{range_label}</text>
  {''.join(grid)}
  <path d="{area_path}" fill="url(#area)" />
  <path d="{line_path}" fill="none" stroke="url(#line)" stroke-width="3.2" stroke-linejoin="round" filter="url(#glow)" />
  <circle cx="{final_x:.2f}" cy="{final_y:.2f}" r="7" fill="{theme["end_glow"]}" opacity=".22" />
  <circle cx="{final_x:.2f}" cy="{final_y:.2f}" r="4" fill="{theme["end_dot"]}" />
  {''.join(labels)}
</svg>
'''


def main() -> None:
    today = datetime.now(timezone.utc).date()
    points = read_snapshots()
    token = os.environ.get("GITHUB_TOKEN", "").strip() or None
    try:
        current_total = fetch_public_star_total(token)
    except RuntimeError as error:
        print(f"Warning: keeping the latest saved star count: {error}")
    else:
        points = [
            (day, total)
            for day, total in points
            if day != today
        ]
        points.append((today, current_total))
        points.sort()
    write_snapshots(points)

    DARK_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DARK_OUTPUT.write_text(render(points, "dark"), encoding="utf-8")
    LIGHT_OUTPUT.write_text(render(points, "light"), encoding="utf-8")


if __name__ == "__main__":
    main()
