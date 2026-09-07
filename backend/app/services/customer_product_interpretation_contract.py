"""Non-mutating interpretation constraints derived from a live product record.

These are source-reading rules, not new product facts or a question router.
Consumers must retain the original fields and their authority separately.
"""
import json
import re
from typing import Any


def product_interpretation_constraints(detail: dict[str, Any]) -> dict[str, Any]:
    specs = detail.get('specs') if isinstance(detail.get('specs'), dict) else {}
    capacity = specs.get('capacity')
    if isinstance(capacity, str):
        try:
            capacity = json.loads(capacity)
        except (ValueError, TypeError):
            capacity = []
    unassigned = []
    for item in capacity if isinstance(capacity, list) else []:
        if not isinstance(item, dict) or str(item.get('label') or '').strip():
            continue
        value = str(item.get('value') or '').strip()
        if re.fullmatch(r'(?:约\s*)?\d+(?:\.\d+)?\s*(?:ml|mL|ML|l|L|毫升|升)?', value):
            unassigned.append({'value': item.get('value'), 'unit': item.get('unit')})
    result: dict[str, Any] = {}
    weight = specs.get('gross_weight_g')
    if weight is not None and str(weight).strip() not in {'', '/', '未知'}:
        result['weight_scope'] = {
            'gross_weight_g': weight,
            'net_weight': 'not_established_by_gross_weight',
            'rule': '这个数值是毛重；用于选购比较时也必须写明毛重，'
                    '不能把它当成去包装后的锅具净重或实际背负重量。',
        }
    if unassigned:
        result['unassigned_capacity'] = {
            'values': unassigned,
            'package_quantity': 'not_established_by_capacity',
            'aggregate_capacity': 'not_established_by_capacity',
            'rule': '仅禁止由容量数值推断包装数量或整套合计。'
                    '同SKU品名或说明已确认水壶、单杯等容量时，直接回答该容量，不要声称归属未知。'
                    '只有多个器皿且归属不明时，才说明无法分配单件与整套容量。',
        }
    lifecycle = str(detail.get('lifecycle_status') or '').strip()
    if lifecycle in {'老款无货不补', '停产', '停售', '已停售', '已停产'}:
        result['new_purchase'] = {
            'eligible': False,
            'basis': lifecycle,
            'rule': '不要作为新购买首选。若顾客明确询问这款，仍回答其事实并说明供货状态；'
                    '做新购推荐时选择其他候选，不能把旧款参数优势当作当前可购买的依据。',
        }
    instruction = str(specs.get('usage_instruction') or '')
    exceptions = [sentence.strip() for sentence in re.split(r'[。\n]', instruction)
                  if '除非' in sentence]
    if exceptions:
        result['conditional_instructions'] = {
            'source_clauses': exceptions,
            'rule': '这些禁令带有例外条件，不得改写成无条件禁止。'
                    '结合本SKU明确的热源支持范围理解条件；回答无关问题时不附加此禁令。',
        }
    return result
