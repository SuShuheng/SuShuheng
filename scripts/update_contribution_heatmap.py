from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "contribution-heatmap.svg"
USER = "SuShuheng"
USER_AGENT = "SuShuheng-profile-metrics/1.0"
API_URL = f"https://github-contributions-api.jogruber.de/v4/{USER}?y=last"

CELL = 10
STEP = 13
GRID_X = 82
GRID_Y = 68
LEVEL_COLORS = {
    0: "#161b22",
    1: "#0e4429",
    2: "#006d32",
    3: "#26a641",
    4: "#39d353",
}


def fetch_json(url: str, attempts: int = 5) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as error:
            last_error = error
            if error.code == 429:
                retry_after = error.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 8.0
                time.sleep(delay * (attempt + 1))
            elif attempt + 1 < attempts:
                time.sleep(2.0 * (attempt + 1))
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2.0 * (attempt + 1))

    curl = shutil.which("curl")
    if curl:
        result = subprocess.run(
            [
                curl,
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--retry",
                "3",
                "--max-time",
                "45",
                url,
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        last_error = RuntimeError(result.stderr.strip())

    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def month_labels(dates: list[date]) -> list[tuple[int, str]]:
    labels: list[tuple[int, str]] = []
    previous_month: int | None = None
    for index, day in enumerate(dates):
        if index % 7 != 0:
            continue
        if day.month == previous_month:
            continue
        column = index // 7
        min_column = labels[-1][0] + 3 if labels else 0
        if column >= min_column:
            labels.append((column, day.strftime("%b")))
        previous_month = day.month
    return labels


def render(data: dict) -> str:
    contributions = data["contributions"]
    total = int(data["total"]["lastYear"])
    dates = [date.fromisoformat(item["date"]) for item in contributions]

    cells: list[str] = []
    for index, item in enumerate(contributions):
        column, row = divmod(index, 7)
        level = max(0, min(4, int(item["level"])))
        x = GRID_X + column * STEP
        y = GRID_Y + row * STEP
        cells.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" '
            f'rx="2" fill="{LEVEL_COLORS[level]}" />'
        )

    months = "".join(
        f'<text x="{GRID_X + column * STEP}" y="55" class="label">'
        f"{escape(label)}</text>"
        for column, label in month_labels(dates)
    )
    weekdays = "".join(
        f'<text x="58" y="{GRID_Y + row * STEP + 8}" text-anchor="end" class="label">'
        f"{escape(label)}</text>"
        for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )

    legend_x = 694
    legend = [
        f'<text x="{legend_x - 26}" y="199" text-anchor="end" class="muted">Less</text>'
    ]
    for level in range(5):
        x = legend_x + level * 15
        legend.append(
            f'<rect x="{x}" y="189" width="{CELL}" height="{CELL}" '
            f'rx="2" fill="{LEVEL_COLORS[level]}" />'
        )
    legend.append(
        f'<text x="{legend_x + 5 * 15 + 2}" y="199" class="muted">More</text>'
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="220" viewBox="0 0 900 220" role="img" aria-labelledby="title desc">
  <title id="title">{total:,} contributions in the last year</title>
  <desc id="desc">A GitHub dark-theme contribution calendar showing {total:,} contributions across the last year.</desc>
  <style>
    .heading {{ font: 600 14px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #e6edf3; }}
    .label {{ font: 500 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #8b949e; }}
    .muted {{ font: 500 10.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #8b949e; }}
  </style>
  <text x="0" y="21" class="heading">{total:,} contributions in the last year</text>
  <rect x="0.5" y="37.5" width="899" height="181" rx="6" fill="#0d1117" stroke="#30363d" />
  {months}
  {weekdays}
  {''.join(cells)}
  <text x="{GRID_X}" y="199" class="muted">Learn how we count contributions</text>
  {''.join(legend)}
</svg>
'''


def main() -> None:
    data = fetch_json(API_URL)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(data), encoding="utf-8")


if __name__ == "__main__":
    main()
