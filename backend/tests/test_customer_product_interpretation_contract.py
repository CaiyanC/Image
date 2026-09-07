import copy
import json

import pytest

from app.services.customer_product_interpretation_contract import product_interpretation_constraints


def test_comparison_keeps_weight_scope():
    detail = {'specs': {'gross_weight_g': '220.000'}}
    assert product_interpretation_constraints(detail)['weight_scope']['net_weight'] == 'not_established_by_gross_weight'


def test_shared_product_packet_carries_constraints_without_replacing_facts():
    from app.services.customer_service_semantic_rag_v2_service import _compact_product_detail
    detail = {'sku': 'TEST-1', 'lifecycle_status': '老款无货不补',
              'specs': {'capacity': [{'label': '', 'value': '450', 'unit': 'ml'}],
                        'gross_weight_g': 220,
                        'usage_instruction': '不可明火加热（除非产品明确支持）。'}}
    before = copy.deepcopy(detail)
    packet = _compact_product_detail(detail)
    assert packet['interpretation_constraints']['new_purchase']['eligible'] is False
    assert packet['interpretation_constraints']['weight_scope']['gross_weight_g'] == 220
    assert packet['specs']['capacity'] == before['specs']['capacity']
    assert packet['specs']['usage_instruction'] == before['specs']['usage_instruction']
    assert detail == before


def test_rag_pointer_target_retains_lifecycle_and_safety_conditions():
    from app.services.customer_service_workbuddy_rag_service import _compact_product_for_prompt
    instruction = '先核对配套炉具。' * 30 + '不可直接明火加热（除非产品明确支持）。避免骤冷骤热。'
    packet = _compact_product_for_prompt({'sku': 'TEST-1', 'lifecycle_status': '老款无货不补',
        'active_flag': True, 'specs': {'usage_instruction': instruction, 'heat_source': '明火直烧'}})
    assert packet['lifecycle_status'] == '老款无货不补'
    assert packet['specs']['usage_instruction'] == instruction
    assert packet['interpretation_constraints']['new_purchase']['eligible'] is False
    assert '除非产品明确支持' in packet['interpretation_constraints']['conditional_instructions']['source_clauses'][0]


@pytest.mark.parametrize('encoded', [False, True])
def test_unlabeled_capacity_never_establishes_package_quantity(encoded):
    capacity = [{'label': '', 'value': '450ml', 'unit': ''}]
    detail = {'specs': {'capacity': json.dumps(capacity) if encoded else capacity}}
    before = copy.deepcopy(detail)
    notes = product_interpretation_constraints(detail)
    assert notes['unassigned_capacity']['aggregate_capacity'] == 'not_established_by_capacity'
    assert notes['unassigned_capacity']['package_quantity'] == 'not_established_by_capacity'
    assert detail == before


@pytest.mark.parametrize('capacity', [
    [{'label': '锅', 'value': '450', 'unit': 'ml'}],
    [{'label': '', 'value': '炉芯：100ml', 'unit': ''}],
    [{'label': '', 'value': '/', 'unit': ''}],
    None, 'invalid',
])
def test_named_or_missing_capacity_is_not_reassigned(capacity):
    assert 'unassigned_capacity' not in product_interpretation_constraints({'specs': {'capacity': capacity}})


@pytest.mark.parametrize('status', ['老款无货不补', '停产', '停售'])
def test_retired_product_is_not_a_new_purchase_candidate(status):
    assert product_interpretation_constraints({'lifecycle_status': status})['new_purchase']['eligible'] is False


@pytest.mark.parametrize('status', ['常规品', '新品', '清仓品', None])
def test_unknown_stock_and_clearance_are_not_invented_as_unavailable(status):
    assert 'new_purchase' not in product_interpretation_constraints({'lifecycle_status': status})


def test_safety_exception_is_retained_not_resolved_by_text_replacement():
    clause = '不可直接明火加热（除非产品明确支持）'
    detail = {'specs': {'usage_instruction': clause + '。避免骤冷骤热。'}}
    before = copy.deepcopy(detail)
    notes = product_interpretation_constraints(detail)
    assert notes['conditional_instructions']['source_clauses'] == [clause]
    assert detail == before
