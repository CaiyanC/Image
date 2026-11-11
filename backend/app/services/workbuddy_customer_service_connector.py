import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models.workbuddy_customer_service_token import WorkBuddyCustomerServiceToken


TOKEN_PREFIX = "cscwb_"
QA_TOKEN_PREFIX = "cscwbqa_"
MAX_ACTIVE_TOKENS_PER_USER = 5


def hash_connector_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def issue_connector_token(
    db: Session,
    *,
    user_id: str,
    name: str,
    expires_in_days: int,
    allow_qa_write: bool = False,
) -> tuple[WorkBuddyCustomerServiceToken, str]:
    now = datetime.now(timezone.utc)
    token = (QA_TOKEN_PREFIX if allow_qa_write else TOKEN_PREFIX) + secrets.token_urlsafe(36)
    row = WorkBuddyCustomerServiceToken(
        user_id=str(user_id),
        name=str(name or "WorkBuddy 客服连接").strip()[:100] or "WorkBuddy 客服连接",
        token_hash=hash_connector_token(token),
        token_prefix=token[:18],
        created_at=now,
        expires_at=now + timedelta(days=int(expires_in_days)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, token


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
