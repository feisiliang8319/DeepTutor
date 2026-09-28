"""Teaching-product entry policy. Menus are not an authorization boundary."""
from fastapi import HTTPException
from .teaching_identity import active

RETIRED = ("/api/v1/imports", "/api/v1/space", "/api/v1/partners", "/api/v1/plugins",
           "/api/v1/subagents", "/api/v1/book", "/api/v1/co_writer", "/api/v1/notebook",
           "/api/v1/question", "/api/v1/question-notebook", "/api/v1/learning")


def under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def authorize(path: str, method: str, role: str) -> None:
    if not active():
        return
    if any(under(path, prefix) for prefix in RETIRED):
        raise HTTPException(410, "This feature is retired from the teaching product")
    if role == "admin":
        return
    if role not in {"parent", "student"}:
        raise HTTPException(403, "Teaching account migration is required")
    if path in {"/api/v1/auth/logout", "/api/v1/auth/status"} or under(path, "/api/v1/auth/profile") or under(path, "/api/v1/auth/avatar"):
        return
    if role == "parent" and (path == "/api/v1/auth/users" and method == "POST" or path.startswith("/api/v1/auth/users/") and path.endswith("/teaching") and method == "PUT"):
        return  # Account router enforces the parent/child relationship.
    if under(path, "/api/v1/teaching"):
        return  # Endpoint-specific ownership checks are mandatory.
    if role == "parent" and under(path, "/api/v1/knowledge"):
        import re
        rest = path.removeprefix("/api/v1/knowledge")
        if (method == "GET" and (rest in {"", "/list", "/upload-policy"} or re.fullmatch(r"/[^/]+/(?:files(?:/.*)?|progress)", rest))) or (method == "POST" and (rest == "/create" or re.fullmatch(r"/[^/]+/upload", rest))):
            return  # Existing write guards resolve to the parent's own workspace.
    if role == "student":
        if (path, method) in {("/api/v1/voice/status", "GET"), ("/api/v1/voice/stt", "POST")}:
            return  # Voice router rechecks current Chat access.
        if path == "/api/v1/ws" or under(path, "/api/attachments"):
            return
        if under(path, "/api/v1/sessions"):
            # Old quiz-results trusts caller-supplied grading. Teaching tests
            # use the education service's server-issued sets exclusively.
            if "quiz-results" not in path and method in {"GET", "PATCH"}:
                return
        if method == "GET" and path in {"/api/v1/capabilities", "/api/v1/settings/ui"}:
            return
    raise HTTPException(403, "This endpoint is not available for your teaching role")
