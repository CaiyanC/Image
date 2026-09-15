"""Small customer-facing boundary shared by the active answer writers.

The model owns wording and semantic decisions.  This module only removes
internal audit markers that may have been carried in retrieved historical
text; it does not rewrite product claims, route questions, or insert a
customer-facing template.
"""

from __future__ import annotations

import re


_INTERNAL_AUDIT_MARKER = re.compile(
    r"(?i)(?:标签|tag|tags?|标记|审核标签|来源标签)?\s*[:：=]?\s*"
    r"(?:manual_history_review|human_identity_audit|rag_boundary|"
    r"full_history_audit(?:[_-]\d+)?|batch(?:[_-](?:remaining|\d+)(?:[_-]\d+)*)|"
    r"titleless_link_context_review)\s*[,，;；]?"
)


def _remove_internal_audit_markers(value: str) -> str:
    answer = _INTERNAL_AUDIT_MARKER.sub("", value)
    answer = re.sub(r"(?i)[（(]\s*[）)]", "", answer)
    answer = re.sub(
        r"(?i)(?:标签|tag|tags?|标记|审核标签|来源标签)\s*[:：=]?\s*(?=[。.!！?？\n]|$)",
        "",
        answer,
    )
    answer = re.sub(r"[，,;；]\s*(?=[。.!！?？\n]|$)", "", answer)
    answer = re.sub(r"[ \t]{2,}", " ", answer)
    return answer.strip()


def render_customer_answer(value: str) -> str:
    """Return the model's answer unchanged except for internal audit noise."""
    answer = str(value or "").strip()
    return _remove_internal_audit_markers(answer)


__all__ = ["render_customer_answer"]
