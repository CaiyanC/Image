"""Seed globally reusable experience cards distilled from reviewed good/bad cases.

These cards are communication guidance only.  They deliberately contain no
product fact, SKU choice, price, compatibility claim, or operating parameter.
The product evidence packet remains the only source for those facts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import database_name_from_url, settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.knowledge_base import KnowledgeChunk, KnowledgeDocument  # noqa: E402
from app.services import knowledge_service, product_vector_index_service  # noqa: E402


SOURCE_FILE = (
    "D:/CaiYan/用户评价与客服对话/"
    "爱路客_多平台客服RAG整理_含千牛_20260903_v12/"
    "09_严格产品映射与三链路RAG"
)


CARDS = [
    {
        "slug": "recommendation-clear-choice",
        "intent": "选购与推荐",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_46",
            "chat_jdpop_21bd4f0b618c3644f61fc51b1ee60343",
            "review_抖音_72e1205d92f8",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
            "修复话术库",
        ],
        "content": (
            "推荐怎么选、我想买一套锅、买锅怎么选、哪款锅合适、帮我挑一款、哪个更适合我、适合新手吗、送人买哪个。\n"
            "做法：先给明确倾向，再用当前商品证据解释一到两个取舍；已有条件够用就直接答，只有关键变量会改变结论时才问一个问题。\n"
            "避免：不要只说‘看需求’或‘都可以’，不要把人数适配、效果、耐用、够用等未被证据支持的判断说成保证。"
        ),
    },
    {
        "slug": "comparison-concrete-tradeoff",
        "intent": "选购与推荐",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛_137",
            "chat_qianniu_千牛_千牛5月11~17日聊天明细_130",
            "chat_jdpop_234eae58-59cc-4c3e-86e2-bb818f67c929",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
        ],
        "content": (
            "对比一下、两款有什么区别、差在哪、哪个更好、哪个更值得、同系列怎么选、一个偏煎炒一个偏收纳怎么取舍、按侧重点选哪个、A和B分别适合谁。\n"
            "做法：先确认要比较的商品和目标，只选两三个相关维度，分别说清事实、取舍和适合情形，最后给条件式倾向。\n"
            "避免：不要用‘各有优点’结束，不要把一款的参数或适用性套给另一款；缺资料的维度就明确说未确认。具体事实始终按对应 SKU。"
        ),
    },
    {
        "slug": "field-first-no-guess",
        "intent": "规格参数",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛_157",
            "chat_qianniu_千牛_千牛5月18~24日聊天明细_86",
            "chat_qianniu_千牛_千牛3月16~22日聊天明细_86",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
        ],
        "content": (
            "规格参数怎么问：容量多少升/多少毫升、重量多少克/多重、尺寸多大、什么材质/什么做的、涂层是什么、几件套、包含什么。\n"
            "做法：先直接回答所问字段，带上单位、版本或必要限定；客户没有继续追问时，不要扩写成整张参数表。\n"
            "边界：资料未登记就说未记录或暂不能确认；不能从相邻 SKU、图片印象、容量或重量推导材质、人数、效果、耐用或‘无负担’。同 SKU 事实不能跨 SKU 合并。"
        ),
    },
    {
        "slug": "heat-source-boundary",
        "intent": "适用热源与兼容性",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛3月09~15日聊天明细_38",
            "chat_raw_京东_b547f4d25a4e",
            "chat_raw_京东_9ebff44e8502",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "差评/顾客不满意原因库",
            "修复话术库",
        ],
        "content": (
            "能用酒精炉吗、卡式炉可以吗、能放电磁炉吗、适配什么炉具、明火行不行、室内能用吗。\n"
            "做法：按当前 SKU 的证据分别回答‘明确支持’、‘资料未确认’或‘有条件支持’，把热源兼容和室内使用分开。\n"
            "边界：不能把明火、燃气、开放火焰或户外使用自动推成酒精炉、电磁炉、木柴或室内安全，也不能套用其他商品的兼容性。"
        ),
    },
    {
        "slug": "safe-operation-response",
        "intent": "使用方法与安全",
        "source_record_ids": [
            "chat_jdpop_20aa0d55f5039f81a0c640b7ac1bd0d0",
            "chat_raw_京东_875d90ae4ff1",
            "chat_raw_京东_594d511e1990",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
            "修复话术库",
        ],
        "content": (
            "怎么点火、怎么熄火、燃料怎么加、第一次怎么用、怎么清洗、漏气/打不着怎么办、这样安全吗。\n"
            "做法：先回答当前操作是否有资料依据，再给必要步骤和一条最重要的安全提醒；异常、漏气或无法确认时先停止继续操作。\n"
            "避免：不要用一句‘安全’代替说明，不要复用历史客服未经核实的危险操作，不要补写说明书没有的参数。需要核实时收集 SKU、订单或照片视频。"
        ),
    },
    {
        "slug": "kit-version-scope",
        "intent": "套装与配件",
        "source_record_ids": [
            "chat_jdpop_21bd4f0b618c3644f61fc51b1ee60343",
            "chat_jdpop_35b640c1e2b9b5c22ae09a0e992e9415",
            "chat_qianniu_千牛_千牛_137",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
        ],
        "content": (
            "套装随货清单、套装几件、有哪些锅、配盖子吗、有没有收纳袋/包装袋/网袋/锅夹、配件是否随货、送不送配件、还要另买吗、不同版本差什么。\n"
            "做法：先列当前版本能确认的随货项目，再区分‘商品具备的能力’和‘此版本实际包含’；配置不明时让客户核对页面版本。\n"
            "边界：不能因为图片、标题或另一版本出现过某配件就说当前订单包含；清单未列出的项目就说资料未登记。"
        ),
    },
    {
        "slug": "price-value-condition",
        "intent": "价格、活动与赠品",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛5月11~17日聊天明细_130",
            "chat_qianniu_千牛_千牛_170",
            "review_抖音_d8f59c58731a",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "客服说话风格库",
        ],
        "content": (
            "多少钱、贵不贵、值不值得、性价比怎么样、和普通款差什么、有没有优惠/活动、送什么、现在能买吗。\n"
            "做法：先承接客户在比较价值，再讲两三个与其场景相关且有当前商品证据的差异，最后给条件式建议。\n"
            "避免：不要说‘贵就是质量好’、‘买到就是赚到’、‘不会失望’或未经证明的更耐用/更健康/更高级；实时价格、活动和赠品不要凭经验承诺。"
        ),
    },
    {
        "slug": "after-sales-first-response",
        "intent": "售后与问题处理",
        "source_record_ids": [
            "review_抖音_7c5e223c18ec",
            "review_抖音_0794c0698969",
            "chat_qianniu_千牛_千牛5月18~24日聊天明细_86",
        ],
        "source_libraries": [
            "差评/顾客不满意原因库",
            "修复话术库",
            "待复核/评估测试集",
        ],
        "content": (
            "少件、漏发、收到后发现少配件、配件没收到、发错、到货破损、磕碰、收到后发现表面有划痕/刮痕、外观瑕疵、掉漆、变形、不能用、漏气、售后怎么处理、退换退款。\n"
            "做法：先承接问题并说明要核实，再收集订单、SKU、照片或视频；涉及安全先停止使用。\n"
            "避免：不要先归责客户，不要用空泛安慰敷衍，不要未经核实承诺赔付、补发或一定退成功；资料不足时只问最关键的一项。"
        ),
    },
    {
        "slug": "review-response-natural-tone",
        "intent": "评价回应与回访",
        "source_record_ids": [
            "review_抖音_72e1205d92f8",
            "review_抖音_d8f59c58731a",
            "review_抖音_2360c383de0b",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "客服说话风格库",
            "禁止话术/风险表达库",
        ],
        "content": (
            "好评怎么回、差评怎么回、顾客说好用/满意/不满意、用过感觉怎么样、使用体验如何、评价留言怎么回复。\n"
            "做法：先回应顾客明确提到的体验，再用简短真诚的话感谢或承接问题；顾客没问事实时不要硬塞卖点。\n"
            "避免：不要复制长商品名，不要补写未登记的卖点、时效、优惠或承诺，也不要把内部标签发给顾客。通常一到三句即可。"
        ),
    },
    {
        "slug": "context-one-question-clarify",
        "intent": "其他咨询",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_46",
            "chat_jdpop_234eae58-59cc-4c3e-86e2-bb818f67c929",
            "chat_raw_京东_594d511e1990",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
            "客服说话风格库",
        ],
        "content": (
            "对话上下文承接：指刚才那款、上一款、另一款、前面说的那个、我换个产品、按刚才继续、它可以吗。\n"
            "做法：继承已确认的商品和比较对象，先回答本轮新增内容；客户明确换款、扩大范围或纠正对象时再更新上下文。\n"
            "避免：不要让新召回的相邻商品静默替换上一轮对象，不要反复问已经给过的 SKU，也不要把上下文记忆当成新的商品事实。有歧义时只问一个影响答案的问题。"
        ),
    },
    {
        "slug": "material-finish-boundary",
        "intent": "规格参数",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛_157",
            "chat_qianniu_千牛_千牛5月18~24日聊天明细_86",
            "chat_qianniu_千牛_千牛3月16~22日聊天明细_86",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
        ],
        "content": (
            "材质是什么、什么材质做的、锅身是什么、是不锈钢还是铝合金、涂层是什么、有没有涂层。\n"
            "做法：只回答当前 SKU 主数据或同 SKU 已审核 QA 明确记录的材质/表面处理，区分锅身材质和涂层。\n"
            "边界：不能根据颜色、重量、容量、图片或相邻商品猜材质，资料没写就明确未记录；材质事实不要升级成更健康、更耐用或无负担。"
        ),
    },
    {
        "slug": "capacity-weight-direct",
        "intent": "规格参数",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛_157",
            "chat_qianniu_千牛_千牛5月18~24日聊天明细_86",
            "chat_qianniu_千牛_千牛3月16~22日聊天明细_86",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
        ],
        "content": (
            "容量多少升、多少毫升、能装多少、重量多少克、多重、单锅多大。\n"
            "做法：先给当前 SKU 记录的容量或重量，写清单位和对应部件；只回答客户问到的字段。\n"
            "边界：容量、重量不能推出人数、够不够用或携带感受；资料没有数值就明确未记录，不用相邻 SKU 的数字补答。"
        ),
    },
    {
        "slug": "dimensions-and-count-direct",
        "intent": "规格参数",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛_157",
            "chat_qianniu_千牛_千牛5月18~24日聊天明细_86",
            "chat_qianniu_千牛_千牛3月16~22日聊天明细_86",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
        ],
        "content": (
            "尺寸多大、展开尺寸、收纳尺寸、收纳后多大、收起来多大、折叠后多大、长宽高多少、几件、多少件套、里面有几个锅。\n"
            "做法：先按当前 SKU 的记录列出对应尺寸或数量，说明是展开还是收纳、整套还是单件；只回答问到的字段。\n"
            "边界：不能用相邻套装的尺寸或件数补答，也不能从尺寸、件数推导容量、重量或使用效果，资料没有登记就明确未记录。"
        ),
    },
    {
        "slug": "context-object-resolution",
        "intent": "其他咨询",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_46",
            "chat_jdpop_234eae58-59cc-4c3e-86e2-bb818f67c929",
            "chat_raw_京东_594d511e1990",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
            "客服说话风格库",
        ],
        "content": (
            "上一轮继续、刚才那款、前面那个、你说的商品、这个/它还可以吗、我说的不是这款。\n"
            "做法：先沿用对话中已经确认的商品和问题对象；客户说‘换款’或‘不是这款’时再更新对象。\n"
            "边界：新召回的近似商品不能静默替换当前对象，已知 SKU 不要重复追问；上下文只能帮助指代，不是新的商品事实。"
        ),
    },
    {
        "slug": "shipping-delivery-expectation",
        "intent": "发货与物流",
        "source_record_ids": [
            "chat_raw_京东_5282458c85a0",
            "chat_raw_京东_67a695a8ac0b",
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_228",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
        ],
        "content": (
            "发货了吗、什么时候发、几天到、今天能送到吗、发什么快递、快递单号、物流轨迹不动、正在派送、能改地址吗。\n"
            "做法：先区分发货、运输和预计到达，只引用当前订单或页面能确认的信息；看不到地区仓配时明确说明以页面时效为准。\n"
            "避免：不要凭历史经验承诺当天到、固定几天到或一定从某地发货；查不到订单状态时先请客户提供订单或平台信息。"
        ),
    },
    {
        "slug": "stock-and-order-status",
        "intent": "其他咨询",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_228",
            "chat_jdpop_c8fef046266cae15127a0d72dd12e4d5",
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_46",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
            "客服说话风格库",
        ],
        "content": (
            "有货吗、现在能买不、为什么拍不了、什么时候补货、下架了吗、还有这个版本吗、老款还有吗。\n"
            "做法：先核对当前商品页面、版本和库存状态，再给能确认的结果；商品或版本不明确时先请客户发链接或说明正在看的规格。\n"
            "避免：不要把相邻 SKU、旧批次或历史库存当成当前有货，不要承诺补货时间；查不到实时状态就明确说需要以页面或人工核实为准。"
        ),
    },
    {
        "slug": "cleaning-maintenance-concrete",
        "intent": "使用方法与安全",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛3月02~08日聊天明细_15",
            "chat_qianniu_千牛_千牛3月09~15日聊天明细_38",
            "chat_qianniu_千牛_千牛_157",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
            "修复话术库",
        ],
        "content": (
            "怎么清洗油污/残渣/焦痕、怎么保养、第一次要不要开锅、能用洗洁精吗、能不能泡水、能放洗碗机吗。\n"
            "做法：先按当前 SKU 的说明回答清洗和养护步骤，只说必要的注意事项；没有登记的清洁方式就说暂不能确认。\n"
            "避免：不要把另一种材质或另一款锅的养护方法套过来，不要凭经验保证不粘、耐用或一定能用某种清洁设备。"
        ),
    },
    {
        "slug": "opening-low-friction",
        "intent": "开场与接待",
        "source_record_ids": [
            "chat_raw_京东_913a75e59ff3",
            "chat_raw_京东_c07c0b071294",
            "chat_raw_京东_22a16ae52aea",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "客服说话风格库",
            "禁止话术/风险表达库",
        ],
        "content": (
            "你好、在吗、有人吗、想咨询一下、好的谢谢、收到、稍等一下。\n"
            "做法：短句回应并承接客户下一步；客户已经提出商品问题时直接回答问题，不要重复一整段欢迎词。\n"
            "避免：不要发送内部字段、自动模板、无关卖点或空泛承诺；客户只说谢谢时自然收尾即可。"
        ),
    },
    {
        "slug": "abnormal-fire-safety-first",
        "intent": "使用方法与安全",
        "source_record_ids": [
            "chat_raw_京东_153aa7fd11c3",
            "chat_qianniu_千牛_千牛4月20~26日聊天明细_12",
            "chat_raw_京东_f34bc3bfcd03",
        ],
        "source_libraries": [
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
            "修复话术库",
            "待复核/评估测试集",
        ],
        "content": (
            "燃料洒漏、炉具翻倒着火、火焰异常、漏气怎么办。\n"
            "做法：先让客户停止继续操作并远离火源、保持通风；异常或安全原因未确认时，先收集商品/订单和现场照片视频，再按售后核实。\n"
            "避免：不要把异常说成正常，不要让客户继续试危险操作，不要编造灭火、点火距离、燃料参数或‘一定安全’结论。"
        ),
    },
    {
        "slug": "fuel-connector-compatibility",
        "intent": "适用热源与兼容性",
        "source_record_ids": [
            "chat_raw_京东_b547f4d25a4e",
            "chat_raw_京东_9ebff44e8502",
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_228",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
            "修复话术库",
        ],
        "content": (
            "高山气罐、卡式气罐、气罐接口、转接头、液体酒精、固体酒精、酒精块用哪种，需不需要另买转接头。\n"
            "做法：先按当前 SKU 资料确认燃料类型、接口和是否需要转接，再说明可选项；客户只问配件时直接说随货或另购状态。\n"
            "边界：不能把‘户外炉具’或‘通用’当成所有气罐都兼容，不能把高山气罐、卡式气罐、酒精和固体燃料互相替换，也不能凭历史链接承诺配件库存或连接安全。"
        ),
    },
    {
        "slug": "ignition-troubleshooting-boundary",
        "intent": "使用方法与安全",
        "source_record_ids": [
            "chat_raw_京东_875d90ae4ff1",
            "chat_raw_京东_594d511e1990",
            "chat_raw_京东_9ebff44e8502",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "差评/顾客不满意原因库",
            "禁止话术/风险表达库",
            "修复话术库",
        ],
        "content": (
            "怎么点火、点火器、打火针、火花、电池、没有火花、点不着、点火失败、火焰不稳怎么处理。\n"
            "做法：先区分普通使用咨询和异常故障；按当前 SKU 说明给最少必要步骤，点火失败、火焰异常或疑似漏气时先停用、通风，再收集订单、SKU 和照片视频交售后核实。\n"
            "边界：不要复述历史客服未经核实的刮针、按针、调整距离等危险操作，不要让客户反复试火，不要凭经验补写电池型号、点火间隙或故障结论。"
        ),
    },
    {
        "slug": "scene-fit-conditional",
        "intent": "选购与推荐",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_46",
            "chat_qianniu_千牛_千牛5月18~24日聊天明细_86",
            "review_京东POP_c407ceb4f0bf",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "差评/顾客不满意原因库",
            "客服说话风格库",
        ],
        "content": (
            "一个人、两个人、多人、露营、行山单锅、单人背包、轻量徒步、高海拔、家庭、煮水、煎炒、携带方便吗、拿着轻松吗、负担大不大，适不适合某个场景。\n"
            "做法：先看当前 SKU 是否直接记录了目标场景，再用一到两个相关事实解释条件式倾向；把‘产品定位’、‘规格事实’和‘实际环境表现’分开说。\n"
            "边界：不能只凭容量或重量保证人数、够用、烧开速度、火力、携带轻松或无负担；没有高海拔、低温、强风等专项证据时，只能说明已登记的场景定位并保留环境条件。"
        ),
    },
    {
        "slug": "appearance-defect-after-sales",
        "intent": "售后与问题处理",
        "source_record_ids": [
            "review_抖音_7c5e223c18ec",
            "review_抖音_0794c0698969",
            "chat_qianniu_千牛_千牛5月18~24日聊天明细_86",
        ],
        "source_libraries": [
            "差评/顾客不满意原因库",
            "修复话术库",
            "待复核/评估测试集",
        ],
        "content": (
            "收到后有划痕、刮痕、磕碰、掉漆、变形、外观瑕疵、锅体有伤怎么处理。\n"
            "做法：先承接并区分外观问题、功能问题和安全问题，收集订单、SKU 及清晰照片或视频；可能影响安全时先停止使用，再按售后流程核实。\n"
            "边界：不能直接说划痕正常或不影响使用，不能凭一张照片下质量结论，也不能未经核实承诺补偿、维修、补发或一定退换成功。"
        ),
    },
    {
        "slug": "product-link-identity",
        "intent": "其他咨询",
        "source_record_ids": [
            "chat_raw_京东_f1ce5e955152",
            "chat_raw_京东_5282458c85a0",
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_228",
        ],
        "source_libraries": [
            "成交/好评成功案例库",
            "未转化原因分析库",
            "客服说话风格库",
            "禁止话术/风险表达库",
        ],
        "content": (
            "商品链接、购买链接、发个链接、链接在哪、这是哪个商品、链接里的是什么、能发链接吗。\n"
            "做法：先确认客户要找的商品、平台和版本；已有商品链接时沿用原链接或请客户补充链接，用链接辅助确认产品身份，再回答本轮问题。\n"
            "边界：不能凭链接标题、店铺文案或历史聊天新建产品/SKU，不能把相邻商品链接当成当前商品，也不要编造链接、库存、价格或活动。"
        ),
    },
    {
        "slug": "received-order-problem-intake",
        "intent": "售后与问题处理",
        "source_record_ids": [
            "review_抖音_7c5e223c18ec",
            "review_抖音_0794c0698969",
            "chat_qianniu_千牛_千牛5月18~24日聊天明细_86",
        ],
        "source_libraries": [
            "差评/顾客不满意原因库",
            "修复话术库",
            "待复核/评估测试集",
        ],
        "content": (
            "收货后发现商品有问题、收到货不对、到货不能用、收到有问题怎么办、想申请售后。\n"
            "做法：先承接收货后的具体现象，再确认订单、SKU 和照片或视频；先分清少件、外观、功能和安全问题，再给当前平台可核实的处理路径。\n"
            "边界：不能把收货问题转成库存或发货问题，不能先下质量结论，也不能未经核实承诺补发、赔付、维修或一定退换成功。"
        ),
    },
]


def _metadata(card: dict) -> dict:
    source_record_ids = list(card["source_record_ids"])
    return {
        "productKey": None,
        "productName": None,
        "sku": None,
        "productRefs": [],
        "productMatchStatus": "not_applicable_global_guidance",
        "quality": "mixed_experience",
        "result": {
            "label": "manually_reviewed_experience_card",
            "sourceQuality": ["good", "bad", "neutral"],
            "sourceLibraries": list(card["source_libraries"]),
        },
        "reviewStatus": "approved_pilot",
        "review_status": "approved_pilot",
        "productionUse": "experience_guidance_only",
        "production_use": "experience_guidance_only",
        "answerApprovedForStandard": False,
        "sourceRecordId": source_record_ids[0],
        "sourceRecordIds": source_record_ids,
        "sourceFile": SOURCE_FILE,
        "intent": card["intent"],
        "authority_level": "candidate_only",
        "fact_authority": False,
        "manual_reviewed": True,
        "pilot_version": "experience-rag-v2",
    }


def _upsert_card(db, card: dict) -> tuple[KnowledgeDocument, str, bool]:
    source_id = f"customer_experience:pilot:v2:global:{card['slug']}"
    metadata_json = json.dumps(_metadata(card), ensure_ascii=False)
    chunk_metadata_json = json.dumps(
        {"title": card["slug"], **_metadata(card)},
        ensure_ascii=False,
    )
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.source_type == knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
        KnowledgeDocument.source_id == source_id,
    ).first()
    action = "updated"
    document_changed = False
    if document is None:
        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            source_type=knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
            source_id=source_id,
            sku=None,
            title=card["slug"],
            content=card["content"],
            metadata_json=metadata_json,
            file_hash=hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
            parse_status="done",
            is_active=True,
        )
        db.add(document)
        db.flush()
        action = "created"
        document_changed = True
    else:
        document_changed = any((
            document.sku is not None,
            document.title != card["slug"],
            document.content != card["content"],
            document.metadata_json != metadata_json,
            document.parse_status != "done",
            document.parse_error is not None,
            document.is_active is not True,
        ))
        document.sku = None
        document.title = card["slug"]
        document.content = card["content"]
        document.metadata_json = metadata_json
        document.parse_status = "done"
        document.parse_error = None
        document.is_active = True

    chunks = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.document_id == document.id
    ).order_by(KnowledgeChunk.chunk_index.asc()).all()
    chunk_created = not chunks
    chunk = chunks[0] if chunks else KnowledgeChunk(
        id=str(uuid.uuid4()), document_id=document.id, chunk_index=0
    )
    content_changed = chunk_created or chunk.content != card["content"]
    chunk_changed = chunk_created or any((
        chunk.sku is not None,
        chunk.source_type != knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
        content_changed,
        chunk.metadata_json != chunk_metadata_json,
    ))
    chunk.sku = None
    chunk.source_type = knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE
    chunk.content = card["content"]
    chunk.metadata_json = chunk_metadata_json
    needs_embedding = content_changed or chunk.embedding_status != "synced"
    if needs_embedding:
        chunk.embedding_status = "pending"
        chunk.embedding_error = None
    db.add(chunk)
    for extra in chunks[1:]:
        db.delete(extra)
    if action != "created":
        action = "updated" if document_changed or chunk_changed or len(chunks) > 1 else "unchanged"
    db.commit()
    db.refresh(document)
    return document, action, needs_embedding


async def main() -> int:
    database_name = database_name_from_url(settings.DATABASE_URL)
    if settings.APP_ENV != "dev" or database_name != "product_knowledge_dev":
        raise RuntimeError(
            f"Refusing to seed outside dev: APP_ENV={settings.APP_ENV!r}, database={database_name!r}"
        )

    db = SessionLocal()
    try:
        created = updated = unchanged = embedded = failed = 0
        for card in CARDS:
            document, action, needs_embedding = _upsert_card(db, card)
            created += int(action == "created")
            updated += int(action == "updated")
            unchanged += int(action == "unchanged")
            if needs_embedding:
                result = await product_vector_index_service.embed_pending_chunks(
                    db,
                    document_id=document.id,
                )
                embedded += int(result.get("embedded") or 0)
                failed += int(result.get("failed") or 0)

        print(json.dumps({
            "database": database_name,
            "cards": len(CARDS),
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "embedded": embedded,
            "failed": failed,
            "scope": "global_guidance_only",
        }, ensure_ascii=False))
        return 0 if failed == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
