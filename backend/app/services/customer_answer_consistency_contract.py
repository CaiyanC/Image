"""Narrow, source-backed contradiction checks; not a question or SKU router."""
import json
import re
from typing import Any


_SPECIFIC_HEAT_SOURCE_ALIASES = {
    "酒精炉": ("酒精炉", "液体酒精", "固体酒精", "alcohol stove"),
    "燃气炉": ("燃气炉", "燃气灶", "gas stove"),
    "卡式炉": ("卡式炉", "卡式气罐", "butane stove"),
    "分体炉": ("分体炉",),
    "一体炉": ("一体炉",),
    "电磁炉": ("电磁炉", "induction"),
    "电陶炉": ("电陶炉", "ceramic stove"),
    "木柴": ("木柴", "柴火", "wood"),
    "木炭": ("木炭", "炭火", "charcoal"),
}
_HEAT_POSITIVE_PATTERN = re.compile(
    r"(?<!不)(?<!未)(?<!没)(?:可以(?:使用|用)?|可用|支持|适合|兼容|适用|"
    r"能(?:够)?(?:使用|用)|能用)"
)
_HEAT_REVERSE_POSITIVE_PATTERN = re.compile(
    r"(?:可以(?:使用|用)?|可用|支持|适合|兼容|适用|能(?:够)?(?:使用|用)|能用)"
)
_HEAT_NEGATIVE_CONTEXT_PATTERN = re.compile(
    r"(?:不|未|没|没有|无法|不能|暂时不能|暂时无法|未确认|未标注|没有明确标注|"
    r"不代表|不等于|不建议).{0,12}$",
    flags=re.I,
)
_IDENTITY_REASK_PATTERN = re.compile(
    r"(?:请|需要|还请).{0,24}(?:提供|补充).{0,24}(?:商品名称|商品名|SKU|链接)",
    flags=re.I,
)


def _requested_specific_heat_sources(question: str) -> list[tuple[str, tuple[str, ...]]]:
    text = str(question or "").lower()
    return [
        (canonical, aliases)
        for canonical, aliases in _SPECIFIC_HEAT_SOURCE_ALIASES.items()
        if any(alias.lower() in text for alias in aliases)
    ]


def _has_positive_heat_claim(text: str, aliases: tuple[str, ...]) -> bool:
    value = str(text or "")
    for clause in re.split(r"[。！？!?；;\n]", value):
        if not clause.strip():
            continue
        for alias in aliases:
            for match in re.finditer(re.escape(alias), clause, flags=re.I):
                prefix = clause[max(0, match.start() - 24):match.start()]
                suffix = clause[match.end():match.end() + 16]
                if _HEAT_NEGATIVE_CONTEXT_PATTERN.search(prefix):
                    continue
                if _HEAT_POSITIVE_PATTERN.search(prefix):
                    return True
                if _HEAT_REVERSE_POSITIVE_PATTERN.search(suffix):
                    return True
    return False


def _has_explicit_heat_support(text: str, aliases: tuple[str, ...]) -> bool:
    value = str(text or "")
    for alias in aliases:
        for match in re.finditer(re.escape(alias), value, flags=re.I):
            window = value[max(0, match.start() - 12):match.end() + 12]
            if not re.search(r"不支持|不适合|不建议|不能|不可|未标注|未列出|没有", window):
                return True
    return False


def _meaningful_heat_source(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text not in {"/", "暂无", "未知", "未填写", "未标注"})


def _payload_bound_product_skus(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("explicit_product_skus") or payload.get("bound_product_skus") or []
    values = [raw] if isinstance(raw, str) else list(raw or [])
    return list(dict.fromkeys(
        str(item or "").strip().upper()
        for item in values
        if str(item or "").strip()
    ))


def _asks_to_reidentify_product(answer: str) -> bool:
    return bool(_IDENTITY_REASK_PATTERN.search(str(answer or "")))


def canonical_products(payload: dict[str, Any]) -> list[dict[str, Any]]:
    by_sku = {}
    for key in ('candidate_products', 'previous_context_products', 'active_context_products'):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and item.get('sku') and isinstance(item.get('specs'), dict):
                by_sku[str(item['sku']).upper()] = item
    for row in payload.get('evidence') or []:
        if not isinstance(row, dict) or row.get('fact_authority') is False:
            continue
        if row.get('authority_level') != 'canonical' and row.get('source_type') not in {'product_record', 'canonical_product_record'}:
            continue
        item = row.get('content')
        if isinstance(item, str):
            try: item = json.loads(item)
            except (ValueError, TypeError): continue
        if isinstance(item, dict) and item.get('sku') and isinstance(item.get('specs'), dict):
            by_sku[str(item['sku']).upper()] = item
    return list(by_sku.values())


def _unsupported_specific_heat_source_issues(
    response: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    requested = _requested_specific_heat_sources(str(payload.get("current_question") or ""))
    if not requested:
        return []
    answer = str(response.get("answer") or "")
    products = canonical_products(payload)
    selected = (
        response.get("selected_skus")
        or payload.get("explicit_product_skus")
        or payload.get("bound_product_skus")
        or []
    )
    selected_skus = {
        str(item or "").strip().upper()
        for item in ([selected] if isinstance(selected, str) else selected or [])
        if str(item or "").strip()
    }
    if selected_skus:
        products = [
            item for item in products
            if str(item.get("sku") or "").strip().upper() in selected_skus
        ]
    all_aliases = tuple(alias for _, aliases in requested for alias in aliases)
    if not products or not _has_positive_heat_claim(answer, all_aliases):
        return []

    issues: list[dict[str, str]] = []
    for product in products:
        specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
        heat_source = str(specs.get("heat_source") or "")
        usage_instruction = str(specs.get("usage_instruction") or "")
        for canonical, aliases in requested:
            if _meaningful_heat_source(heat_source):
                # A non-empty closed compatibility field is authoritative;
                # another QA row cannot silently add a new heat source.
                supported = _has_explicit_heat_support(heat_source, aliases)
            else:
                supported = _has_explicit_heat_support(usage_instruction, aliases)
                if not supported:
                    sku = str(product.get("sku") or "").strip().upper()
                    for row in payload.get("evidence") or []:
                        if not isinstance(row, dict):
                            continue
                        if str(row.get("sku") or "").strip().upper() != sku:
                            continue
                        if str(row.get("source_type") or "").strip() != "product_qa":
                            continue
                        if row.get("fact_authority") is False:
                            continue
                        content = row.get("content")
                        if isinstance(content, (dict, list)):
                            content = json.dumps(content, ensure_ascii=False)
                        if _has_explicit_heat_support(str(content or ""), aliases):
                            supported = True
                            break
            if not supported:
                issues.append({
                    "code": "unsupported_specific_heat_source",
                    "sku": str(product.get("sku") or "").strip().upper(),
                    "requested_heat_source": canonical,
                    "confirmed_heat_source": heat_source,
                    "reason": (
                        f"回答把{canonical}说成可用，但同 SKU 的封闭热源资料没有明确支持该选项；"
                        "宽泛的明火或燃气不能自动推出具体兼容性。"
                    ),
                })
    return issues


def _is_alcohol_cookware_recommendation(question: str) -> bool:
    value = str(question or "")
    return (
        any(term in value for term in ("酒精炉", "液体酒精", "固体酒精"))
        and any(term in value for term in ("锅", "锅具", "套锅", "单锅", "炊具"))
        and any(term in value for term in ("推荐", "选择", "哪些", "几个", "给"))
    )


def _supports_alcohol_stove(product: dict[str, Any]) -> bool:
    specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
    alcohol_terms = ("酒精炉", "液体酒精", "固体酒精", "alcohol stove")
    negative_pattern = re.compile(
        r"(?:不支持|未显示支持|不适合|不建议|不能|不可|未标注).{0,12}"
        r"(?:酒精炉|液体酒精|固体酒精|alcohol stove)",
        flags=re.I,
    )
    heat_source = str(specs.get("heat_source") or "")
    if any(term.lower() in heat_source.lower() for term in alcohol_terms) and not negative_pattern.search(heat_source):
        return True
    usage_instruction = str(specs.get("usage_instruction") or "")
    return bool(
        any(term.lower() in usage_instruction.lower() for term in alcohol_terms)
        and re.search(r"支持|适合|可用|可以用|能用|兼容|适配|均可", usage_instruction)
        and not negative_pattern.search(usage_instruction)
    )


def _is_cookware_product(product: dict[str, Any]) -> bool:
    category = str(product.get("category") or product.get("product_category") or "")
    return any(term in category for term in ("锅具", "炊具"))


def alcohol_stove_recommendation_skus(payload: dict[str, Any]) -> list[str]:
    """Return only catalogue candidates that satisfy the explicit request."""
    if not _is_alcohol_cookware_recommendation(payload.get("current_question")):
        return []
    result: list[str] = []
    for product in canonical_products(payload):
        sku = str(product.get("sku") or "").strip().upper()
        if sku and _is_cookware_product(product) and _supports_alcohol_stove(product):
            result.append(sku)
    return list(dict.fromkeys(result))


def safe_alcohol_stove_recommendation(payload: dict[str, Any]) -> str | None:
    """Build a bounded fallback when the answer model violates the heat boundary."""
    if not _is_alcohol_cookware_recommendation(payload.get("current_question")):
        return None
    skus = alcohol_stove_recommendation_skus(payload)
    if not skus:
        return (
            "当前没有明确标注适合酒精炉的锅具，不能把仅标注明火、卡式炉、分体炉或一体炉的普通锅具"
            "直接当作酒精炉适配推荐。若你接受带酒精炉的一体组合，我可以按这个范围继续筛选。"
        )
    products = {
        str(item.get("sku") or "").strip().upper(): item
        for item in canonical_products(payload)
        if str(item.get("sku") or "").strip()
    }
    labels = []
    for sku in skus[:3]:
        product = products.get(sku) or {}
        name = str(product.get("product_name_cn") or product.get("name") or sku).strip()
        labels.append(f"{name}（{sku}）")
    return (
        "可优先看" + "、".join(labels) + "。它们的同款资料明确写有酒精炉或液体酒精热源；"
        "仅标注明火、卡式炉、分体炉或一体炉的普通锅具不作为酒精炉适配推荐。"
    )


def safe_specific_heat_source_answer(
    payload: dict[str, Any],
    issues: list[dict[str, str]],
) -> str | None:
    """Keep an unsupported compatibility claim customer-safe after one retry."""
    issue = next(
        (item for item in issues if item.get("code") == "unsupported_specific_heat_source"),
        None,
    )
    if not issue and any(item.get("code") == "generic_explicit_product_fallback" for item in issues):
        requested = _requested_specific_heat_sources(str(payload.get("current_question") or ""))
        bound_skus = _payload_bound_product_skus(payload)
        products = canonical_products(payload)
        if requested and bound_skus and products:
            bound_set = set(bound_skus)
            product = next(
                (
                    item for item in products
                    if str(item.get("sku") or "").strip().upper() in bound_set
                ),
                products[0],
            )
            specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
            issue = {
                "code": "unsupported_specific_heat_source",
                "sku": str(product.get("sku") or bound_skus[0]).strip().upper(),
                "requested_heat_source": requested[0][0],
                "confirmed_heat_source": str(specs.get("heat_source") or ""),
            }
    if not issue:
        return None
    requested = str(issue.get("requested_heat_source") or "该热源").strip()
    sku = str(issue.get("sku") or "").strip().upper()
    product = next(
        (
            item for item in canonical_products(payload)
            if str(item.get("sku") or "").strip().upper() == sku
        ),
        {},
    )
    name = str(product.get("product_name_cn") or product.get("name") or sku).strip()
    confirmed_heat_source = str(issue.get("confirmed_heat_source") or "").strip()
    if _meaningful_heat_source(confirmed_heat_source):
        return (
            f"{name}（{sku}）暂时不能确认支持{requested}；"
            f"已明确列出的适用热源包括{confirmed_heat_source}。"
        )
    return (
        f"{name}（{sku}）暂时不能确认支持{requested}，"
        "请以所购版本的使用说明或下单前向店铺人工核实。"
    )


def answer_consistency_issues(response: dict[str, Any] | None, payload: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(response, dict): return []
    answer = str(response.get('answer') or '')
    question = str(payload.get('current_question') or '')
    unsupported_heat_issues = _unsupported_specific_heat_source_issues(response, payload)
    if unsupported_heat_issues:
        return unsupported_heat_issues
    if _is_alcohol_cookware_recommendation(question) and "暂时无法确认这个问题的答案" in answer:
        return [{
            "code": "generic_alcohol_recommendation_fallback",
            "reason": "酒精炉锅具推荐不能用无具体原因的通用兜底；应只保留同 SKU 热源明确支持的锅具，或明确说明没有符合项。",
        }]
    if (
        _is_alcohol_cookware_recommendation(question)
        and str(response.get("answer_type") or "").strip().lower() in {"recommendation", "comparison"}
    ):
        selected = response.get("selected_skus")
        selected_values = [selected] if isinstance(selected, str) else list(selected or [])
        for claim in response.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            claim_skus = claim.get("skus")
            selected_values.extend(
                [claim_skus] if isinstance(claim_skus, str) else list(claim_skus or [])
            )
            if claim.get("sku"):
                selected_values.append(claim.get("sku"))
        selected_skus = list(dict.fromkeys(
            str(item or "").strip().upper()
            for item in selected_values
            if str(item or "").strip()
        ))
        products = {
            str(item.get("sku") or "").strip().upper(): item
            for item in canonical_products(payload)
            if str(item.get("sku") or "").strip()
        }
        invalid_skus = [
            sku for sku in selected_skus
            if sku in products
            and (not _is_cookware_product(products[sku]) or not _supports_alcohol_stove(products[sku]))
        ]
        if invalid_skus:
            return [{
                "code": "alcohol_stove_candidate_mismatch",
                "sku": ",".join(invalid_skus[:8]),
                "reason": (
                    "酒精炉锅具推荐只能保留同 SKU 资料明确写有酒精炉/液体或固体酒精，且品类为锅具或炊具的候选；"
                    "仅支持明火、卡式炉、分体炉或一体炉不能推出酒精炉适配。"
                ),
            }]
    bound_product_skus = _payload_bound_product_skus(payload)
    if (
        bound_product_skus
        and canonical_products(payload)
        and str(response.get("answer_type") or "").strip().lower()
        in {"clarification", "comparison", "product_detail"}
        and (
            "暂时无法确认这个问题的答案" in answer
            or _asks_to_reidentify_product(answer)
        )
    ):
        return [{
            "code": "generic_explicit_product_fallback",
            "reason": "已明确商品且本轮有同 SKU 商品资料，不能用无具体缺失项的通用兜底，应直接回答可确认事实或说明具体未确认维度。",
            "sku": ",".join(bound_product_skus[:8]),
        }]
    # A narrow missing-aspect check, not an intent router or quality score.
    if re.search(r'(?:什么|哪些|何种).{0,8}不适合|优缺点|利弊', question) and not re.search(
            r'不适合|不太适合|不建议|多余|重复|取舍|不足|缺点|偏重|负担|不能保证|无法确认|不能确认', answer):
        return [{'code':'missing_requested_tradeoff', 'reason':'顾客明确要求双向判断，上一版只有适合和优点。补答基于已确认容量、毛重、配置的取舍；不得编造缺点或差评原因。'}]
    if re.search(r'(?:没有|未有|未确认|未验证).{0,12}(?:耐用|高频|重度).{0,20}(?:因此|所以|故).{0,6}不适合', answer):
        return [{'code':'unknown_is_not_negative', 'reason':'缺少验证不等于已确认不适合；保留不能承诺，不作负面性能断言。'}]
    products = canonical_products(payload)
    selected = response.get('selected_skus') or payload.get('explicit_product_skus') or payload.get('bound_product_skus') or []
    if selected:
        selected = {str(s).upper() for s in selected}
        products = [p for p in products if str(p['sku']).upper() in selected]
    # Never transfer one product's permission to another product or component.
    if len(products) != 1: return []
    product = products[0]
    specs = product['specs']
    notes = product.get('interpretation_constraints') or {}
    if notes.get('unassigned_capacity') and re.search(r'(?:为|是)单件商品', answer):
        return [{'code':'capacity_is_not_package_count', 'sku':str(product['sku']), 'reason':'单杯容量不证明售卖包装是单件。只回答已确认容量，包装数量未知。'}]
    product_text = json.dumps(product, ensure_ascii=False)
    if '导热盘' in product_text and '锅' in str(specs.get('usage_instruction') or ''):
        for clause in re.split(r'[。；;，,\n]', answer):
            if '预热' in clause and not any(x in clause for x in ('锅','不要','禁止','不能','避免','不应')):
                return [{'code':'heating_action_object_unclear','sku':str(product['sku']), 'reason':'原步骤对象是锅具，不应追加操作对象不明的预热指导，让顾客误将导热盘空烧。当前只回答导热效果及已确认限制。'}]
    heat_options = {s.strip() for s in re.split(r'[、，,;；\n]+', str(specs.get('heat_source') or ''))}
    if not heat_options.intersection({'明火', '明火直烧', '明火加热'}): return []
    source = str(specs.get('usage_instruction') or '')
    source += json.dumps(notes.get('conditional_instructions') or {}, ensure_ascii=False)
    if '除非' not in source or '明火' not in source: return []
    if re.search(r'(?:不建议|不能|不应).{0,8}(?:可装热饮|可盛装热饮).{0,12}理解为.{0,8}(?:直接)?加热', answer):
        return [{'code':'supported_heat_presented_as_unknown','sku':str(product['sku']), 'reason':'本款明确支持热源加热，不能追加暗示不能加热的泛化提醒。仅回答能装热饮并保留真实注意事项。'}]
    for sentence in re.split(r'[。；;\n]', str(response.get('answer') or '')):
        if '除非' in sentence: continue
        for clause in re.split(r'[，,]', sentence):
            if any(term in clause for term in ('木柄','手柄','壶盖','杯盖','盖子','室内','帐篷','密闭','干烧','空烧','空杯','空壶','空锅','无水','长时间','大火')):
                continue
            if any(term in clause for term in ('并非', '不代表', '不等于', '不能理解为', '错误')):
                continue
            if re.search(r'(?:不能|不可|不要|禁止|不可以|不支持|不适用)(?:(?:将|把)(?:杯子|水壶|锅具|本品|产品|它))?(?:直接)?(?:放在|放到|置于|在|用)?明火(?:上)?(?:直接)?(?:加热|直烧)', clause):
                return [{'code': 'conditional_heat_denial', 'sku': str(product['sku']),
                         'confirmed_heat_source': str(specs['heat_source']),
                         'reason': '当前热源明确支持明火，原禁令带除非明确支持的例外，不能改成无条件禁止。'}]
    return []


def consistency_repair_instruction(issues: list[dict[str, str]]) -> str:
    if any(issue.get("code") == "invalid_answer_json" for issue in issues):
        return (
            "上一版模型没有返回可解析的 JSON 对象，不能把这次有证据的问题降级成通用兜底。"
            "请重新阅读本轮 payload，只输出一个合法的 JSON object；不要输出 Markdown、代码围栏、"
            "解释文字或 JSON 之外的前后缀。answer 必须是可以直接发送给顾客的自然中文回复，"
            "其余字段按原协议选择性返回；只使用本轮 evidence 中能确认的事实。"
        )
    if any(issue.get("code") == "unsupported_specific_heat_source" for issue in issues):
        return (
            "上一版把具体热源兼容性说成了同 SKU 资料没有明确支持的结论，不能继续发送。"
            "请重新核对该 SKU 的 canonical_product_record、candidate_products 和 evidence："
            "只有同 SKU 的适用热源或使用说明明确写出当前请求的具体热源，才能说支持；"
            "明火、燃气或多热源等宽泛表述不能推出酒精炉、卡式炉、电磁炉等另一个具体选项。"
            "如果没有明确支持，请直接说暂时不能确认支持该热源，并可列出同 SKU 已明确列出的适用热源；"
            "不要用通用兜底，不要猜测，不要提及内部来源或本次重试。只输出原协议要求的合法 JSON。"
            "冲突：" + json.dumps(issues, ensure_ascii=False)
        )
    if any(issue.get("code") == "generic_explicit_product_fallback" for issue in issues):
        return (
            "上一版对已经明确的商品使用了无具体缺失项的通用兜底，但本轮 payload 已提供同一 SKU 的"
            "canonical_product_record、candidate_products 或 evidence。请重新核对 current_question 与这些同 SKU 资料，"
            "不要重复‘暂时无法确认这个问题的答案，建议下单前向店铺人工核实’。"
            "如果所问事项在主产品记录或同 SKU evidence 中有非空值，直接回答具体值并保留正确单位和口径；"
            "如果该事项确实为空、‘/’或未确认，只说明这款对应的具体事项暂时无法确认，"
            "不要把整条问题说成资料不存在。可以补充同一 SKU 能直接支持且有助于当前判断的事实，但不要猜测、"
            "不要提及内部来源、本次重试或检查过程。只输出原协议要求的合法 JSON，answer 必须是顾客可直接发送的自然中文回复。"
            "冲突：" + json.dumps(issues, ensure_ascii=False)
        )
    return ('上一版答案与本轮同SKU明确事实或条件冲突，不能直接发送。'
            '请保留可以确认的回答，只修正冲突，不编造新事实，不追加无关加热步骤。'
            '酒精炉锅具推荐只能保留同SKU资料明确写有酒精炉/液体或固体酒精且品类确为锅具或炊具的候选；'
            '仅写明火、卡式炉、分体炉或一体炉的普通锅具不能当作酒精炉适配推荐。'
            '尤其不能把带有“除非明确支持”的条件句改成绝对禁止。'
            '继续使用原JSON协议，不输出检查过程。冲突：'+json.dumps(issues, ensure_ascii=False))
