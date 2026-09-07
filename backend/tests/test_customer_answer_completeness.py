from app.services.customer_answer_consistency_contract import answer_consistency_issues

def test_explicit_two_sided_question_requires_tradeoff():
    payload={'current_question':'什么需求下适合，什么需求下不适合？'}
    assert answer_consistency_issues({'answer':'适合两人露营，容量3L。'},payload)
    assert not answer_consistency_issues({'answer':'适合两人露营；单人只烧水则配置多余。'},payload)
    assert not answer_consistency_issues({'answer':'适合两人露营。'},{'current_question':'适合什么场景？'})

def test_uncertainty_is_not_a_product_defect():
    payload={'candidate_products':[{'sku':'TEST','specs':{}}]}
    assert answer_consistency_issues({'answer':'没有耐用测试，因此不适合高频使用。'},payload)
    assert not answer_consistency_issues({'answer':'不能据此认定不适合高频使用。'},payload)

def test_capacity_does_not_prove_sold_quantity():
    p={'candidate_products':[{'sku':'TEST','specs':{},'interpretation_constraints':{'unassigned_capacity':{'rule':'unknown count'}}}]}
    assert answer_consistency_issues({'answer':'这是单件商品。'},p)
    assert not answer_consistency_issues({'answer':'单杯容量160ml，包装数量未知。'},p)

def test_pot_preheat_must_not_be_transferred_to_diffuser():
    p={'candidate_products':[{'sku':'TEST','name':'导热盘','specs':{'usage_instruction':'将锅具预热'}}]}
    assert answer_consistency_issues({'answer':'有助均匀导热，请用中小火预热。'},p)
    assert not answer_consistency_issues({'answer':'避免导热盘空烧，不要单独预热。'},p)

def test_known_heat_is_not_presented_as_unknown():
    p={'candidate_products':[{'sku':'TEST','specs':{'heat_source':'明火直烧','usage_instruction':'不可明火加热，除非明确支持'}}]}
    assert answer_consistency_issues({'answer':'不建议将“可装热饮”理解为可直接加热饮品。'},p)
    assert not answer_consistency_issues({'answer':'可以装热饮，避免骤冷骤热。'},p)
