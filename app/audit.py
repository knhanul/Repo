from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditLog


def add_audit(db: Session, user_id: int | None, action: str, target: str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, target=target, detail=detail))
