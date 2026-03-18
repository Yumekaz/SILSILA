from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
    username: str
    role: str
    authenticated: bool
    source: str



def _parse_api_tokens(raw: str) -> dict[str, UserContext]:
    tokens: dict[str, UserContext] = {}
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue
        if "|" in entry:
            token, username, role = [item.strip() for item in entry.split("|", 2)]
        elif ":" in entry:
            token, username, role = [item.strip() for item in entry.split(":", 2)]
        else:
            continue
        if token:
            tokens[token] = UserContext(username=username or "api-user", role=role or "viewer", authenticated=True, source="token")
    return tokens



def resolve_request_user(request, settings) -> UserContext:
    token_index = _parse_api_tokens(settings.api_tokens)
    api_key = (request.headers.get("X-API-Key") or "").strip()
    if api_key and api_key in token_index:
        return token_index[api_key]
    if settings.auth_required:
        raise PermissionError("API authentication required.")

    username = (request.headers.get("X-User") or "local-operator").strip() or "local-operator"
    role = (request.headers.get("X-Role") or "admin").strip() or "admin"
    return UserContext(username=username, role=role, authenticated=False, source="headers")



def require_role(user: UserContext, allowed_roles: set[str]) -> None:
    if user.role not in allowed_roles:
        raise PermissionError(f"Role '{user.role}' cannot access this operation.")
