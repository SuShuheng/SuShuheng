from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "package-stats.json"
USER_AGENT = "SuShuheng-profile-metrics/1.0"

PACKAGES = [
    ("dsh-budget-view", "npm"),
    ("dsh-thinking-effort-slide-bar", "npm"),
    ("dsh-windows-acl-logon-dacl-fix", "npm"),
    ("se-cli", "pypi"),
    ("dglz", "pypi"),
    ("nrdp-cli", "pypi"),
    ("btvit-cli", "pypi"),
    ("jwztumor", "pypi"),
    ("btsp-cli", "pypi"),
    ("eip-cli", "pypi"),
    ("obshare-cli", "pypi"),
]


def fetch_json(url: str, attempts: int = 4) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
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


def display_number(value: int) -> str:
    return f"{value:,}"


def npm_total(package: str, created: date, today: date) -> int:
    total = 0
    cursor = created
    while cursor <= today:
        chunk_end = min(cursor + timedelta(days=364), today)
        url = (
            "https://api.npmjs.org/downloads/point/"
            f"{cursor.isoformat()}:{chunk_end.isoformat()}/{quote(package)}"
        )
        total += int(fetch_json(url)["downloads"])
        cursor = chunk_end + timedelta(days=1)
    return total


def npm_stats(package: str, today: date) -> dict:
    metadata = fetch_json(f"https://registry.npmjs.org/{quote(package)}")
    created = datetime.fromisoformat(
        metadata["time"]["created"].replace("Z", "+00:00")
    ).date()
    month_start = today - timedelta(days=29)
    monthly = fetch_json(
        "https://api.npmjs.org/downloads/point/"
        f"{month_start.isoformat()}:{today.isoformat()}/{quote(package)}"
    )["downloads"]
    return {
        "platform": "npm",
        "version": metadata["dist-tags"]["latest"],
        "monthly": int(monthly),
        "total": npm_total(package, created, today),
    }


def pypi_stats(package: str) -> dict:
    metadata = fetch_json(f"https://pypi.org/pypi/{quote(package)}/json")
    recent = fetch_json(
        f"https://pypistats.org/api/packages/{quote(package)}/recent"
    )
    overall = fetch_json(
        f"https://pypistats.org/api/packages/{quote(package)}/overall"
    )
    total = sum(
        int(row["downloads"])
        for row in overall["data"]
        if row["category"] == "without_mirrors"
    )
    return {
        "platform": "pypi",
        "version": metadata["info"]["version"],
        "monthly": int(recent["data"]["last_month"]),
        "total": total,
    }


def main() -> None:
    today = datetime.now(timezone.utc).date()
    packages = {}
    for package, platform in PACKAGES:
        packages[package] = (
            npm_stats(package, today)
            if platform == "npm"
            else pypi_stats(package)
        )
        packages[package]["monthly_display"] = display_number(
            packages[package]["monthly"]
        )
        packages[package]["total_display"] = display_number(
            packages[package]["total"]
        )

    npm_names = [name for name, platform in PACKAGES if platform == "npm"]
    pypi_names = [name for name, platform in PACKAGES if platform == "pypi"]

    def aggregate(names: list[str]) -> dict:
        monthly = sum(packages[name]["monthly"] for name in names)
        total = sum(packages[name]["total"] for name in names)
        return {
            "packages": len(names),
            "monthly": monthly,
            "total": total,
            "monthly_display": display_number(monthly),
            "total_display": display_number(total),
        }

    all_names = list(packages)
    result = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).date().isoformat(),
        "npm": aggregate(npm_names),
        "pypi": aggregate(pypi_names),
        "combined": aggregate(all_names),
        "packages": packages,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
