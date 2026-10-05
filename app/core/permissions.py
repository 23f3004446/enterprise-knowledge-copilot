from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.db.models import DocumentRecord

ROLE_LEVELS = {
    "EMPLOYEE": {"PUBLIC", "EMPLOYEE"},
    "MANAGER": {"PUBLIC", "EMPLOYEE", "MANAGER"},
    "ADMIN": {"PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"},
}


def allowed_access_levels(role: str) -> set[str]:
    return ROLE_LEVELS.get(role.upper(), set())


def can_access(role: str, access_level: str) -> bool:
    return access_level.upper() in allowed_access_levels(role)


def restricted_document_requested(db: Session, query: str, role: str) -> bool:
    """Reject explicit requests for restricted document titles before content retrieval."""
    allowed = allowed_access_levels(role)
    if not allowed:
        return True
    raw_query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    query_terms = set(raw_query_terms)
    generic = {"policy", "procedure", "document", "information", "about", "show", "tell", "reveal"}
    query_terms -= generic
    lowered = query.lower()
    request_language = any(
        phrase in lowered
        for phrase in (
            "show",
            "reveal",
            "give me",
            "provide",
            "print",
            "read",
            "manager-only",
            "manager only",
            "admin-only",
            "admin only",
            "administrator-only",
            "administrator only",
        )
    )
    document_language = bool(raw_query_terms.intersection({"policy", "procedure", "document", "file"}))
    restricted = db.query(DocumentRecord).filter(~DocumentRecord.access_role.in_(allowed)).all()
    for document in restricted:
        title_terms = set(re.findall(r"[a-z0-9]+", document.filename.lower()))
        title_terms.discard("policy")
        title_terms.discard("procedure")
        title_terms.discard("md")
        distinctive = query_terms.intersection(title_terms)
        if distinctive and (request_language or document_language):
            return True
    return False
