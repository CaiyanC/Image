import sys, asyncio, json, logging, time
logging.disable(logging.CRITICAL)
sys.path.insert(0, r"D:\CaiYan\Image-Generation-feature-v5\backend")
from app.core.database import SessionLocal
from app.services import customer_agent_intent_service as intent_svc, knowledge_service, customer_agent_service as cas

db = SessionLocal()

results = []

async def test(cat, q, expected):
    t0 = time.time()
    r = {"category": cat, "question": q, "expected": expected, "status": "FAIL"}

    # 1. Intent parsing
    llm_intent = None
    try:
        llm_intent = await intent_svc._llm_parse_intent(db, q)
    except:
        pass
    regex_intent = intent_svc.parse_intent(q)
    intent = llm_intent or regex_intent
    if not intent:
        r["detail"] = "No intent parsed"
        results.append(r)
        return

    # Merge
    if llm_intent and regex_intent and regex_intent.intent == llm_intent.intent:
        for k, v in (regex_intent.filters or {}).items():
            if k not in (llm_intent.filters or {}):
                llm_intent.filters[k] = v
        intent = llm_intent

    r["intent"] = f"{intent.intent} filters={intent.filters}"
    r["llm_used"] = bool(llm_intent)

    # 2. DB search
    term = intent.term or q
    db_rows = cas.search_products(db, term, limit=5, filters=intent.filters)
    r["db_count"] = len(db_rows)
    r["db_skus"] = [row["sku"] for row in db_rows[:5]]

    # 3. Vector search
    try:
        kb = await knowledge_service.semantic_retrieve(db, q, limit=5)
        r["vec_count"] = len(kb)
        r["vec_top"] = [f"{k.get('sku','?')}|{k.get('content','')[:60]}" for k in kb[:3]] if kb else []
    except:
        r["vec_count"] = 0
        r["vec_top"] = []

    # 4. QA search
    qas = []
    for row in db_rows[:3]:
        qas.extend(intent_svc._search_product_qa(db, row["sku"], q))
    r["qa_count"] = len(qas)
    r["qa_top"] = [f"{qa['question'][:40]} -> {qa['answer'][:40]}" for qa in qas[:2]] if qas else []

    # 5. Pass/fail
    checks = expected.split(",")
    passed = []
    for check in checks:
        check = check.strip()
        if check.startswith("sku:"):
            sku = check[4:]
            if sku in r["db_skus"] or any(sku in v for v in r["vec_top"]):
                passed.append(check)
        elif check.startswith("cat:"):
            cat_val = check[4:]
            if intent.filters.get("product.category") == cat_val:
                passed.append(check)
        elif check.startswith("intent:"):
            i = check[7:]
            if intent.intent == i:
                passed.append(check)
        elif check.startswith("qa:"):
            qa_key = check[3:]
            if any(qa_key in str(q) for q in qas):
                passed.append(check)
        elif check == "vec_hit":
            if r["vec_count"] > 0:
                passed.append(check)
    r["passed"] = ", ".join(passed) if passed else "none"
    r["status"] = "PASS" if len(passed) >= len(checks) * 0.5 else "PARTIAL" if passed else "FAIL"
    r["time"] = f"{time.time()-t0:.1f}s"
    results.append(r)

async def main():
    await test("语义理解", "哪些炉子能用酒精当燃料", "cat:炉具,sku:CS-B14,sku:CS-G25,vec_hit")
    await test("语义理解", "一个人去爬山带什么锅比较轻", "intent:recommend_products,cat:锅具,sku:CW-C93")
    await test("语义理解", "烧水最快的锅是哪个", "sku:CW-C93,vec_hit")
    await test("QA知识库", "小青炉可以用酒精吗", "sku:CS-G25,qa:酒精,vec_hit")
    await test("QA知识库", "行山单锅有涂层吗", "sku:CW-C93,qa:涂层,vec_hit")
    await test("QA知识库", "小青炉火力多大", "sku:CS-G25,qa:火力,vec_hit")
    await test("口语化", "锅具有啥", "cat:锅具,sku:CW-C93")
    await test("口语化", "Greta管哪些东西", "sku:CW-C93")
    await test("多轮-1", "Greta负责哪些产品", "sku:CW-C93,intent:query_products")
    await test("边界", "这个能用电磁炉吗", "intent:clarify")

    # Print report
    print(f"\n{'='*80}")
    print(f"  智能客服测试报告  ({len(results)} 项)")
    print(f"{'='*80}")
    total_pass = sum(1 for r in results if r["status"] == "PASS")
    total_partial = sum(1 for r in results if r["status"] == "PARTIAL")
    total_fail = sum(1 for r in results if r["status"] == "FAIL")

    for r in results:
        icon = "PASS" if r["status"] == "PASS" else "PART" if r["status"] == "PARTIAL" else "FAIL"
        print(f"\n[{icon}] {r['category']}: {r['question']}")
        print(f"  意图: {r['intent']}  (LLM={'Y' if r.get('llm_used') else 'N'})")
        print(f"  DB: {r['db_count']}条 {r['db_skus']}")
        if r['vec_top']:
            print(f"  向量: {r['vec_count']}条")
            for vt in r['vec_top']:
                print(f"    -> {vt}")
        if r['qa_top']:
            print(f"  QA: {r['qa_count']}条")
            for qt in r['qa_top']:
                print(f"    -> {qt}")
        print(f"  期望: {r['expected']}  |  命中: {r['passed']}  |  {r['time']}")

    print(f"\n{'='*80}")
    print(f"  通过: {total_pass}  部分通过: {total_partial}  失败: {total_fail}")
    print(f"{'='*80}")

    db.close()

asyncio.run(main())
