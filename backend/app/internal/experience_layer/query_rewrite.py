from __future__ import annotations


def build_retrieval_query(text: str) -> str:
    """Rewrite vague customer phrasing for retrieval only.

    This function must stay conservative: exact product or field questions are
    returned unchanged so product_detail and recommendation decisions remain hard.
    """
    value = str(text or "").strip()
    if not value:
        return ""

    exact_rewrites = {
        "简单说下": "产品核心信息总结",
        "简单说说": "产品核心信息总结",
        "简单讲下": "产品核心信息总结",
        "一句话说下": "产品核心信息总结",
        "适合吗": "使用场景推荐",
        "适不适合": "使用场景推荐",
        "能买吗": "购买建议",
        "能不能买": "购买建议",
        "怎么样": "评价与使用体验",
        "好不好": "评价与使用体验",
    }
    if value in exact_rewrites:
        return exact_rewrites[value]

    replacements = (
        ("简单说下", "产品核心信息总结"),
        ("简单说说", "产品核心信息总结"),
        ("能买吗", "购买建议"),
        ("怎么样", "评价与使用体验"),
    )
    rewritten = value
    for old, new in replacements:
        rewritten = rewritten.replace(old, new)
    return rewritten.strip() or value
