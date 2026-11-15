"""Data access for cases (read-only JSON files) and learner progress (JSON files)."""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = BASE_DIR / "cases"
PROGRESS_DIR = BASE_DIR / "data" / "progress"


def load_case(case_id):
    path = CASES_DIR / f"{case_id}.json"
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def list_case_summaries():
    summaries = []
    for path in CASES_DIR.glob("*.json"):
        if path.name.startswith("_"):  # templates such as _template.json
            continue

        case = load_case(path.stem)
        summaries.append({
            "id": case["id"],
            "order": case.get("order", 99),
            "title": case["title"],
            "difficulty": case["difficulty"],
        })

    return sorted(summaries, key=lambda s: s["order"])


def _progress_path(session_id, case_id):
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in f"{session_id}_{case_id}" if c.isalnum() or c in "-_")

    return PROGRESS_DIR / f"{safe_name}.json"


def load_progress(session_id, case_id):
    path = _progress_path(session_id, case_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    return {
        "session_id": session_id,
        "case_id": case_id,
        "hint_level": 0,
        "discoveries": [],
        "accusations": [],
        "solved": False,
    }


def delete_progress(session_id, case_id):
    path = _progress_path(session_id, case_id)
    existed = path.exists()
    path.unlink(missing_ok=True)

    return existed


def save_progress(progress):
    path = _progress_path(progress["session_id"], progress["case_id"])
    with open(path, "w", encoding="utf-8") as file:
        json.dump(progress, file, ensure_ascii=False, indent=2)
