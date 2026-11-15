"""MCP server exposing the Detetive Mentor knowledge base as tools.

Run with:  python -m mcp_server.server
"""

from mcp.server.mcpserver import MCPServer

from mcp_server.repository import delete_progress, list_case_summaries, load_case, load_progress, save_progress

CASE_NOT_FOUND = {"error": "case not found"}

mcp = MCPServer(
    "detetive_mentor_tools",
    "Tools to query mystery cases, track learner progress and validate final accusations",
)

# ---------------------------------------------------------------------------
# public case data (the learner can also see it)
# ---------------------------------------------------------------------------


@mcp.tool(name="list_cases", description="Lists the available mystery cases with id, title and difficulty.")
def list_cases() -> dict:
    return {"cases": list_case_summaries()}


@mcp.tool(name="get_case", description="Returns the introduction, location, date and suspects of a case.")
def get_case(case_id: str) -> dict:
    case = load_case(case_id)
    if not case:
        return CASE_NOT_FOUND

    public = case["public"]
    return {
        "id": case["id"],
        "title": case["title"],
        "introduction": public["introduction"],
        "location": public["location"],
        "date": public["date"],
        "suspects": public["suspects"],
        "hint_count": len(case["secret"]["hints"]),  # how many hints exist, never their content
    }


@mcp.tool(name="get_evidence", description="Returns the evidence found at the crime scene of a case.")
def get_evidence(case_id: str) -> dict:
    case = load_case(case_id)
    if not case:
        return CASE_NOT_FOUND

    return {"evidence": case["public"]["evidence"]}


@mcp.tool(
    name="get_testimonies",
    description="Returns the testimonies of a case. Optionally filters by a suspect id.",
)
def get_testimonies(case_id: str, suspect_id: str = "") -> dict:
    case = load_case(case_id)
    if not case:
        return CASE_NOT_FOUND

    testimonies = case["public"]["testimonies"]
    if suspect_id:
        testimonies = [t for t in testimonies if t["suspect_id"] == suspect_id]

    return {"testimonies": testimonies}


@mcp.tool(name="get_timeline", description="Returns the known timeline of events of a case.")
def get_timeline(case_id: str) -> dict:
    case = load_case(case_id)
    if not case:
        return CASE_NOT_FOUND

    return {"timeline": case["public"]["timeline"]}


# ---------------------------------------------------------------------------
# secret data (only for the mentor's internal reasoning)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_solution",
    description=(
        "CONFIDENTIAL: returns the case solution and the list of contradictions. "
        "MUST be called before evaluating any deduction, hypothesis or accusation from the learner "
        "(the contradiction ids needed by record_progress are only here). NEVER reveal its content to the learner."
    ),
)
def get_solution(case_id: str) -> dict:
    case = load_case(case_id)
    if not case:
        return CASE_NOT_FOUND

    secret = case["secret"]
    return {
        "warning": "CONFIDENTIAL. Use only to evaluate the learner's reasoning. Do not reveal the culprit, motive or explanation.",
        "solution": secret["solution"],
        "contradictions": secret["contradictions"],
    }


# ---------------------------------------------------------------------------
# learner progress
# ---------------------------------------------------------------------------


@mcp.tool(
    name="request_hint",
    description="Returns the next hint of the case (increasing level) and records that the learner used one more hint.",
)
def request_hint(session_id: str, case_id: str) -> dict:
    case = load_case(case_id)
    if not case:
        return CASE_NOT_FOUND

    hints = case["secret"]["hints"]
    progress = load_progress(session_id, case_id)

    if progress["hint_level"] >= len(hints):
        return {
            "level": progress["hint_level"],
            "max_level": len(hints),
            "hint": None,
            "message": "All hints were already given. Encourage the learner to review the contradictions and make the accusation.",
        }

    hint = hints[progress["hint_level"]]
    progress["hint_level"] += 1
    save_progress(progress)

    return {"level": hint["level"], "max_level": len(hints), "hint": hint["text"]}


@mcp.tool(
    name="record_progress",
    description="Records that the learner identified, in their own words, a contradiction of the case (use the contradiction id, e.g. C1).",
)
def record_progress(session_id: str, case_id: str, contradiction_id: str, note: str = "") -> dict:
    case = load_case(case_id)
    if not case:
        return CASE_NOT_FOUND

    valid_ids = [c["id"] for c in case["secret"]["contradictions"]]
    if contradiction_id not in valid_ids:
        return {"error": f"invalid contradiction id. valid ids: {valid_ids}"}

    progress = load_progress(session_id, case_id)
    if contradiction_id not in [d["contradiction_id"] for d in progress["discoveries"]]:
        progress["discoveries"].append({"contradiction_id": contradiction_id, "note": note})
        save_progress(progress)

    return {"recorded": True, "total_discoveries": len(progress["discoveries"]), "total_contradictions": len(valid_ids)}


@mcp.tool(
    name="get_progress",
    description="Returns the current hint level, the contradictions already discovered and whether the case is solved.",
)
def get_progress(session_id: str, case_id: str) -> dict:
    return load_progress(session_id, case_id)


@mcp.tool(
    name="reset_progress",
    description="Deletes the learner's progress for a case (hints, discoveries, accusations), so the case can be played again from scratch.",
)
def reset_progress(session_id: str, case_id: str) -> dict:
    return {"reset": True, "had_progress": delete_progress(session_id, case_id)}


@mcp.tool(
    name="validate_accusation",
    description="Validates the learner's final accusation: the accused suspect id and the ids of the evidence supporting it.",
)
def validate_accusation(session_id: str, case_id: str, suspect_id: str, evidence_ids: list[str], motive: str = "") -> dict:
    case = load_case(case_id)
    if not case:
        return CASE_NOT_FOUND

    solution = case["secret"]["solution"]
    correct_culprit = suspect_id == solution["culprit_id"]
    key_evidence_cited = [e for e in evidence_ids if e in solution["key_evidence"]]
    enough_evidence = len(key_evidence_cited) >= solution["min_key_evidence"]
    solved = correct_culprit and enough_evidence

    progress = load_progress(session_id, case_id)
    progress["accusations"].append(
        {"suspect_id": suspect_id, "evidence_ids": evidence_ids, "motive": motive, "correct": solved}
    )
    progress["solved"] = progress["solved"] or solved
    save_progress(progress)

    result = {
        "correct_culprit": correct_culprit,
        "key_evidence_cited": len(key_evidence_cited),
        "min_key_evidence": solution["min_key_evidence"],
        "solved": solved,
    }

    # the full explanation is only released once the case is solved
    if solved:
        result["explanation"] = solution["explanation"]

    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", streamable_http_path="/mcp")
