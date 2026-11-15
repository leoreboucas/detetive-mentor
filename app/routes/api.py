from flask import Blueprint, abort, jsonify, request

from app.extensions import get_mentor, run_async

api_bp = Blueprint("api", __name__)


def _public_progress(progress):
    # the browser only needs to know how far the learner went, never which contradictions exist
    return {
        "hint_level": progress["hint_level"],
        "discoveries": len(progress["discoveries"]),
        "accusations": len(progress["accusations"]),
        "solved": progress["solved"],
    }


def _session_from_request():
    data = request.get_json(silent=True) or {}
    session = get_mentor().get_session(data.get("session_id", ""))
    if not session:
        abort(404, description="session not found")

    return session, data


def _mentor_response(session, output):
    mentor = get_mentor()
    progress = run_async(mentor.get_progress(session))

    return jsonify({
        "answer": output["answer"],
        "source": output["source"],
        "solved": progress["solved"],
        "progress": _public_progress(progress),
    })


@api_bp.get("/cases")
def list_cases():
    return jsonify(run_async(get_mentor().mcp.call("list_cases"))["cases"])


@api_bp.get("/cases/<case_id>")
def get_case_file(case_id):
    mcp = get_mentor().mcp

    case = run_async(mcp.call("get_case", {"case_id": case_id}))
    if "error" in case:
        abort(404, description=case["error"])

    for tool in ("get_evidence", "get_testimonies", "get_timeline"):
        case.update(run_async(mcp.call(tool, {"case_id": case_id})))

    return jsonify(case)


@api_bp.post("/sessions")
def create_session():
    data = request.get_json(silent=True) or {}
    session = run_async(get_mentor().start_session(data.get("case_id", "")))
    if not session:
        abort(404, description="case not found")

    return jsonify({
        "session_id": session["id"],
        "greeting": session["greeting"],
        "hint_count": session["case"]["hint_count"],
    })


@api_bp.post("/sessions/end")
def end_session():
    # also called with navigator.sendBeacon when the tab closes, so the body may not be marked as JSON
    data = request.get_json(silent=True, force=True) or {}
    ended = run_async(get_mentor().end_session(data.get("session_id", "")))

    return jsonify({"ended": ended})


@api_bp.post("/chat")
def chat():
    session, data = _session_from_request()
    message = (data.get("message") or "").strip()
    if not message:
        abort(400, description="empty message")

    output = run_async(get_mentor().reply(session, message))
    return _mentor_response(session, output)


@api_bp.post("/hint")
def hint():
    session, _ = _session_from_request()
    output = run_async(get_mentor().request_hint(session))

    return _mentor_response(session, output)


@api_bp.post("/accuse")
def accuse():
    session, data = _session_from_request()
    if not data.get("suspect_id"):
        abort(400, description="suspect_id is required")

    output = run_async(get_mentor().accuse(
        session, data["suspect_id"], data.get("evidence_ids", []), data.get("motive", "")
    ))

    return _mentor_response(session, output)


@api_bp.errorhandler(400)
@api_bp.errorhandler(404)
def handle_error(error):
    return jsonify({"error": error.description}), error.code
