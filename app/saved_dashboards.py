"""Persistent, local-only storage for Morrow dashboard configurations."""

import json
import re
from datetime import date
from pathlib import Path

SAVE_DIR = Path(__file__).resolve().parent.parent / "data" / "saved_dashboards"
NAME_RE = re.compile(r"^[\w .()-]{1,80}$", re.UNICODE)


def _path_for(name):
    name = str(name).strip()
    if not NAME_RE.fullmatch(name):
        raise ValueError(
            "Name must be 1–80 characters and use letters, numbers, spaces, "
            "dots, parentheses, underscores, or hyphens."
        )
    # Store using a stable digest-like filename rather than a user-supplied path.
    import hashlib
    key = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()
    return SAVE_DIR / f"{key}.json"


def list_dashboards():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in SAVE_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("name"), str):
                items.append({
                    "name": payload["name"],
                    "updated_at": payload.get("updated_at", ""),
                })
        except (OSError, ValueError):
            continue
    return sorted(items, key=lambda item: item["name"].casefold())


def save_dashboard(name, config):
    name = str(name).strip()
    path = _path_for(name)
    if not isinstance(config, dict):
        raise ValueError("Dashboard configuration must be an object.")

    start = str(config.get("start_date", ""))
    end = str(config.get("end_date", ""))
    # Validate dates before persisting the configuration.
    if start:
        date.fromisoformat(start)
    if end:
        date.fromisoformat(end)
    if start and end and start > end:
        raise ValueError("Start date must not be after end date.")

    status = str(config.get("status", "All statuses"))
    category = str(config.get("category", "All categories"))
    completed_only = config.get("completed_only", False)
    if not isinstance(completed_only, bool):
        raise ValueError("completed_only must be true or false.")

    payload = {
        "version": 1,
        "name": name,
        "start_date": start,
        "end_date": end,
        "status": status[:100],
        "category": category[:100],
        "completed_only": completed_only,
        "updated_at": date.today().isoformat(),
    }

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(path)
    return payload


def load_dashboard(name):
    path = _path_for(name)
    if not path.is_file():
        raise FileNotFoundError(f"No saved dashboard named {name!r}.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("name", "").casefold() != str(name).strip().casefold():
        raise ValueError("Saved dashboard name does not match its file.")
    return payload


def delete_dashboard(name):
    path = _path_for(name)
    if not path.is_file():
        raise FileNotFoundError(f"No saved dashboard named {name!r}.")
    path.unlink()
