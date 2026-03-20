"""Audit logging service -- fire-and-forget, never breaks main flow."""

from datetime import datetime
from typing import Optional

from loguru import logger

from app.database import async_session
from app.models.audit import AuditLog


async def audit_log(
    action: str,
    category: str,
    *,
    user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    details: Optional[dict] = None,
    request=None,
    severity: str = "INFO",
) -> None:
    """Record an audit log entry.

    This is fire-and-forget: failures are logged but never propagated
    to the caller, so audit logging cannot break the main application flow.

    Args:
        action:        Short verb-noun key, e.g. 'order:create', 'auth:login'.
        category:      High-level bucket: 'auth', 'trading', 'risk', 'admin'.
        user_id:       ID of the acting user (None for system actions).
        resource_type: Type of affected entity, e.g. 'order', 'position'.
        resource_id:   Primary key of affected entity.
        details:       Arbitrary JSON-serialisable context dict.
        request:       Optional FastAPI/Starlette Request for IP & UA extraction.
        severity:      'INFO' (default), 'WARNING', or 'CRITICAL'.
    """
    try:
        ip_address: Optional[str] = None
        user_agent: Optional[str] = None

        if request is not None:
            # Starlette / FastAPI Request object
            ip_address = getattr(request.client, "host", None) if request.client else None
            user_agent = request.headers.get("user-agent")

        entry = AuditLog(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            action=action,
            category=category,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            severity=severity,
        )

        async with async_session() as session:
            session.add(entry)
            await session.commit()

    except Exception:
        # Audit must never break the caller -- swallow and log.
        logger.opt(exception=True).warning("Audit log write failed for action={}", action)
