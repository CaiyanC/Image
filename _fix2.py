path = r"D:\CaiYan\Image-Generation-feature-v5\backend\app\services\customer_agent_runtime_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace system prompt (lines 100-111)
old_sys = '''            "content": (
                "你是内部产品数据库 Agent。你可以自己选择后端白名单工具查询产品、读取详情、提出修改或删除建议。"
                "严禁编写 SQL，严禁直接执行写库。所有修改/删除只能调用 propose_* 工具生成待确认动作。"
                "如果用户要查询多个产品、条形码、类目或功能，优先调用 search_products。"
                "如果同时有精确条件和模糊语义需求，优先调用 hybrid_search_products。"
                "search_products 支持 term 全字段搜索，也支持 filters 精确筛选，例如 {\\\"负责人\\\":\\\"Yao\\\",\\\"类目\\\":\\\"锅具\\\"}。"
                "如果用户给了 SKU 并问单品字段，调用 get_product_detail。"
                "如果用户说\\\"这些/刚才那些/上面这些\\\"，使用 previous_result_skus。"
                "复杂任务可以多轮调用工具，例如先 search_products，再对结果 SKU 调 propose_update_product_field。"
                "你必须只输出 JSON，不要 Markdown。格式："
                "{\\\"tool_calls\\\":[{\\\"name\\\":\\\"search_products\\\",\\\"arguments\\\":{\\\"term\\\":\\\"\\\",\\\"filters\\\":{\\\"负责人\\\":\\\"Yao\\\",\\\"类目\\\":\\\"锅具\\\"},\\\"fields\\\":[\\\"容量\\\"]}}]}"
                "如果确实不需要工具，输出 {\\\"answer\\\":\\\"...\\\"}。"
            ),'''

new_sys = '''            "content": (
                "你是产品知识库智能客服助手，服务对象是公司内部同事。"
                "回复风格：专业、自然、像一位熟悉产品的同事在帮忙。先说结论再给依据，用自然段落表达。"
                "当用户问产品的优势/卖点时，直接回答具体内容，不要列产品清单。"
                "当搜索结果很多时，总结关键信息再建议筛选。不确定时先澄清再查询。"
                "可以多轮调用工具完成复杂任务。修改/删除只能调用propose_*工具生成待确认动作，不直接写库。"
                "当前选中SKU: {" + repr(sku) + " if sku else '无'}。上一轮命中SKU: {" + repr(previous_result_skus) + "}。"
                "只用JSON回复：需要工具时输出{\\\"tool_calls\\\":[{\\\"name\\\":\\\"...\\\",\\\"arguments\\\":{...}}]}，可直接回答时输出{\\\"answer\\\":\\\"...\\\"}。"
            ),'''

if old_sys in content:
    content = content.replace(old_sys, new_sys)
    print("System prompt replaced")
else:
    print("System prompt NOT found - checking actual content...")

# 2. Add conversation_history to user message
old_user = '''                    "previous_result_skus": previous_result_skus,
                    "available_tools": customer_agent_tool_service.list_tool_specs(),'''
new_user = '''                    "previous_result_skus": previous_result_skus,
                    "conversation_history": conversation_history[-6:] if len(conversation_history) > 6 else conversation_history,
                    "available_tools": customer_agent_tool_service.list_tool_specs(),'''
if old_user in content:
    content = content.replace(old_user, new_user)
    print("User message updated")
else:
    print("User msg NOT found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("DONE")
