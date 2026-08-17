from __future__ import annotations


def shape_answer_tone(
    answer: str,
    *,
    intent: str | None = None,
    answer_type: str | None = None,
) -> str:
    """Keep the answer writer's wording intact.

    The old experience layer appended a generic product-name/SKU question to
    every clarification.  That was a second, lexical answer writer: it made
    unrelated questions sound identical and could ask for an identity that
    was already known.  Semantic answers and bounded safety contracts now
    own their wording, so this presentation layer only normalizes the outer
    string and never adds content.
    """
    del intent, answer_type
    return str(answer or "").strip()


def soften_clarify_answer(answer: str) -> str:
    """Backward-compatible API that does not alter customer wording."""
    return str(answer or "").strip()
