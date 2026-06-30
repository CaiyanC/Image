import json
from pathlib import Path

from scripts import run_current_acceptance_overlay as overlay


def test_overlay_reclassifies_known_legacy_text_assertion_cases(tmp_path):
    report = {
        "results": [
            {
                "编号": "35",
                "测试问题": "我下周带3个人去户外露营，需要能煮饭也能烧水的套装，推荐一下",
                "判定标准": "返回产品推荐（如CW-C05-37）；理由含人数/场景匹配依据；不返回澄清提示",
                "实际回答": "优先推荐2-4人野餐锅10件套（CW-C05-37），适合3-4人，兼容酒精炉。",
                "intent": "recommendation",
                "answer_type": "recommendation",
                "agent_mode": "",
                "result_skus": ["CW-C05-37", "CW-C19T-37"],
                "llm_call_count": 1,
                "是否通过": "失败",
                "失败原因": ["missing_required_text:产品推荐（如CW-C05-37）"],
                "conversation_id": "conv-35",
            },
            {
                "编号": "36",
                "测试问题": "两个人周末野餐，想要轻便一点的套装，预算中等，推荐哪款",
                "判定标准": "返回推荐+具体匹配理由（容量/重量/价格定位）；不返回澄清",
                "实际回答": "优先推荐激川单锅（CW-S10-1），净重约300g。",
                "intent": "recommendation",
                "answer_type": "recommendation",
                "agent_mode": "",
                "result_skus": ["CW-S10-1", "CW-C19T-37"],
                "llm_call_count": 1,
                "是否通过": "失败",
                "失败原因": ["missing_required_text:推荐+具体匹配理由（容量/重量/价格定位）"],
                "conversation_id": "conv-36",
            },
            {
                "编号": "40",
                "测试问题": "今年夏天天气热，想找个适合装凉水的户外水壶，推荐一下",
                "判定标准": "返回水壶推荐；不被天气二字触发护栏；理由有实质内容",
                "实际回答": "优先推荐1.4升户外水壶（CW-K03-37），容量约1400ml。",
                "intent": "recommendation",
                "answer_type": "recommendation",
                "agent_mode": "",
                "result_skus": ["CW-K03-37", "CW-K02-37"],
                "llm_call_count": 1,
                "是否通过": "失败",
                "失败原因": ["missing_required_text:水壶推荐"],
                "conversation_id": "conv-40",
            },
            {
                "编号": "41",
                "测试问题": "锅具类产品里，哪些最适合4人以上使用？",
                "判定标准": "返回大容量锅具推荐（如CW-C05-37）；理由含容量/人数匹配",
                "实际回答": "优先推荐炊墨套锅（CW-C83），也可以考虑2-4人野餐锅10件套（CW-C05-37）。",
                "intent": "recommendation",
                "answer_type": "recommendation",
                "agent_mode": "",
                "result_skus": ["CW-C83", "CW-C05-37"],
                "llm_call_count": 1,
                "是否通过": "失败",
                "失败原因": ["missing_required_text:大容量锅具推荐（如CW-C05-37）"],
                "conversation_id": "conv-41",
            },
            {
                "编号": "71",
                "测试问题": "你们有没有那种可以直接放在酒精炉上用的锅具",
                "判定标准": "返回热源含酒精炉的套装产品；不返回不支持酒精炉的产品",
                "实际回答": "先说结论：共找到 50 个符合筛选条件的候选产品。",
                "intent": "query_products",
                "answer_type": "product_query",
                "agent_mode": "",
                "result_skus": [f"CW-{index:03d}" for index in range(50)],
                "llm_call_count": 1,
                "是否通过": "失败",
                "失败原因": ["missing_required_text:热源含酒精炉的套装产品"],
                "conversation_id": "conv-71",
            },
            {
                "编号": "80",
                "测试问题": "发一段200字左右含天气/海拔/三人/煮饭/轻便等词的露营攻略，最后问哪款产品适合",
                "判定标准": "返回产品推荐；不被天气等词触发护栏；推荐理由有实质内容",
                "实际回答": "优先推荐乐途3-4人野餐锅7件套（CW-C06S-37），适合3-4人露营。",
                "intent": "recommendation",
                "answer_type": "recommendation",
                "agent_mode": "",
                "result_skus": ["CW-C06S-37", "CW-C19T-37"],
                "llm_call_count": 1,
                "是否通过": "失败",
                "失败原因": ["missing_required_text:产品推荐"],
                "conversation_id": "conv-80",
            },
        ]
    }
    report_path = tmp_path / "legacy.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    records = overlay.build_overlay_records(old_report_path=report_path)
    verdicts = {record["case_id"]: record["current_verdict"] for record in records}

    assert verdicts["35"] == "pass"
    assert verdicts["36"] == "quality_issue"
    assert verdicts["40"] == "pass"
    assert verdicts["41"] == "manual"
    assert verdicts["71"] == "quality_issue"
    assert verdicts["80"] == "pass"


def test_overlay_writes_json_and_xlsx_outputs(tmp_path):
    report_path = tmp_path / "legacy.json"
    report_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "编号": "35",
                        "测试问题": "推荐锅具",
                        "判定标准": "返回产品推荐（如CW-C05-37）",
                        "实际回答": "优先推荐2-4人野餐锅10件套（CW-C05-37）。",
                        "intent": "recommendation",
                        "answer_type": "recommendation",
                        "result_skus": ["CW-C05-37"],
                        "llm_call_count": 1,
                        "是否通过": "失败",
                        "失败原因": ["missing_required_text:产品推荐（如CW-C05-37）"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    json_path = tmp_path / "overlay.json"
    xlsx_path = tmp_path / "overlay.xlsx"

    summary = overlay.run_overlay(
        old_report_path=report_path,
        new_report_path=None,
        json_path=json_path,
        xlsx_path=xlsx_path,
        include_frozen=False,
        include_qa=False,
    )

    assert summary["total"] == 1
    assert summary["by_verdict"]["pass"] == 1
    assert json_path.exists()
    assert xlsx_path.exists()
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["records"][0]["case_id"] == "35"
