EXECUTIVE_OFFICE_GROUP_NAME = "总经办"
HR_ADMIN_GROUP_NAME = "人资行政部"
FINANCE_GROUP_NAME = "财务部"
PRODUCT_DEPARTMENT_GROUP_NAME = "产品部"
INTERNATIONAL_TRADE_GROUP_NAME = "国际贸易部"
CROSS_BORDER_ECOMMERCE_GROUP_NAME = "跨境电商部"
ECOMMERCE_ONE_GROUP_NAME = "电商一部"
BUSINESS_GROUP_NAME = "商务部"
QUALITY_GROUP_NAME = "品质部"
VISUAL_ONE_GROUP_NAME = "视觉一部"
BRAND_GROUP_NAME = "品牌部"
MERCHANDISING_GROUP_NAME = "跟单部"
FINANCIAL_SERVICES_GROUP_NAME = "金服"
VISUAL_TWO_GROUP_NAME = "视觉二部"
IT_GROUP_NAME = "IT部"

TOOL_MANAGE_PERMISSION = "tool.manage"
ECOMMERCE_DATA_FILL_PERMISSION = "finance.ecommerce_data_fill"
SYSTEM_ADMIN_PERMISSION = "system.admin"
PRODUCT_QA_MANAGE_PERMISSION = "product.qa.manage"

# Compatibility aliases used by authorization code and older tests.
MANAGEMENT_GROUP_NAME = EXECUTIVE_OFFICE_GROUP_NAME
PRODUCT_TEAM_GROUP_NAME = PRODUCT_DEPARTMENT_GROUP_NAME
DESIGN_TEAM_GROUP_NAME = VISUAL_ONE_GROUP_NAME
ECOMMERCE_GROUP_NAME = CROSS_BORDER_ECOMMERCE_GROUP_NAME
OVERSEAS_MARKETING_GROUP_NAME = INTERNATIONAL_TRADE_GROUP_NAME
AI_CONTENT_GROUP_NAME = BRAND_GROUP_NAME
CUSTOMER_SERVICE_GROUP_NAME = BUSINESS_GROUP_NAME
AI_ENGINEER_GROUP_NAME = IT_GROUP_NAME
FULL_ACCESS_GROUP_NAMES = frozenset({EXECUTIVE_OFFICE_GROUP_NAME, IT_GROUP_NAME})

DEFAULT_GROUPS = [
    (EXECUTIVE_OFFICE_GROUP_NAME, "公司经营管理与系统最高权限"),
    (HR_ADMIN_GROUP_NAME, "人力资源与行政管理"),
    (FINANCE_GROUP_NAME, "财务核算与经营数据管理"),
    (PRODUCT_DEPARTMENT_GROUP_NAME, "产品规划、产品主数据与新品管理"),
    (INTERNATIONAL_TRADE_GROUP_NAME, "国际贸易与海外客户业务"),
    (CROSS_BORDER_ECOMMERCE_GROUP_NAME, "跨境电商渠道运营"),
    (ECOMMERCE_ONE_GROUP_NAME, "国内电商渠道运营"),
    (BUSINESS_GROUP_NAME, "商务合作、客户支持与业务协同"),
    (QUALITY_GROUP_NAME, "产品质量、资料准确性与审核"),
    (VISUAL_ONE_GROUP_NAME, "产品视觉素材制作与审核"),
    (BRAND_GROUP_NAME, "品牌内容、营销与传播"),
    (MERCHANDISING_GROUP_NAME, "订单跟进与产品资料协同"),
    (FINANCIAL_SERVICES_GROUP_NAME, "金融服务业务"),
    (VISUAL_TWO_GROUP_NAME, "产品视觉素材制作与审核"),
    (IT_GROUP_NAME, "系统、AI 与数据技术支持"),
]
DEPARTMENT_ORDER = {name: index for index, (name, _) in enumerate(DEFAULT_GROUPS)}

LEGACY_GROUP_NAME_MAP = {
    "管理层": EXECUTIVE_OFFICE_GROUP_NAME,
    "产品团队": PRODUCT_DEPARTMENT_GROUP_NAME,
    "设计团队": VISUAL_ONE_GROUP_NAME,
    "电商运营": CROSS_BORDER_ECOMMERCE_GROUP_NAME,
    "海外营销": INTERNATIONAL_TRADE_GROUP_NAME,
    "AI内容岗": BRAND_GROUP_NAME,
    "客服团队": BUSINESS_GROUP_NAME,
    "AI工程师": IT_GROUP_NAME,
}

DEPRECATED_EMPTY_GROUP_NAMES = {"经销商", "外部达人", "广告代理商"}
PRESET_GROUP_NAMES = {name for name, _ in DEFAULT_GROUPS}

PERMISSION_DEFS = [
    ("history.view", "查看历史记录", "page"),
    ("profile.view", "查看个人资料", "page"),
    ("category.read", "查看产品品类", "api"),
    ("product.read", "查看产品", "page"),
    ("product.create", "创建产品", "button"),
    ("product.edit", "编辑产品", "button"),
    (PRODUCT_QA_MANAGE_PERMISSION, "管理产品 QA", "button"),
    ("product.delete", "删除产品", "button"),
    ("product.review", "审核产品", "button"),
    ("media.upload", "上传素材", "button"),
    ("media.review", "审核素材", "button"),
    ("media.download", "下载素材", "button"),
    ("tag.edit", "编辑标签", "button"),
    ("ai.call", "AI 调用", "api"),
    ("ai.generate", "AI 生图", "api"),
    ("ai.customer_service", "智能客服", "api"),
    ("ai.authorize", "AI 调用授权", "button"),
    ("competitor.view", "查看竞品", "page"),
    ("new_product.view", "查看新品", "page"),
    ("export.approved", "导出审批", "button"),
    (TOOL_MANAGE_PERMISSION, "管理内部工具", "page"),
    (ECOMMERCE_DATA_FILL_PERMISSION, "电商数据自动填表", "page"),
    (SYSTEM_ADMIN_PERMISSION, "系统管理", "page"),
]

ROUTE_DEFS = [
    ("/customer-service", "智能客服", "page"),
    ("/", "工作区", "page"),
    ("/history", "历史记录", "page"),
    ("/profile", "个人资料", "page"),
    ("/products", "产品管理", "page"),
    ("/assets", "视觉素材库", "page"),
    ("/assets/search", "素材搜索", "page"),
    ("/knowledge-base", "产品知识库", "page"),
    ("/file-knowledge", "文件知识库", "page"),
    ("/products/create", "新增产品", "page"),
    ("/products/create/:draftId", "编辑产品草稿", "page"),
    ("/products/edit/:sku", "编辑产品", "page"),
    ("/products/qa/new", "添加产品 QA", "page"),
    ("/products/drafts", "草稿箱", "page"),
    ("/admin/users", "用户管理", "page"),
    ("/admin/groups", "部门权限", "page"),
    ("/admin/settings", "系统设置", "page"),
    ("/admin/logs", "操作日志", "page"),
    ("/tools", "工具中心", "page"),
    ("/tools/ecommerce-data-fill", "电商数据自动填表", "page"),
    ("/admin/tools", "工具管理", "page"),
    ("/admin/department-workbench", "部门工作台", "page"),
    ("/admin/model-governance", "模型治理", "page"),
]

COMMON_PERMISSION_KEYS = ["history.view", "profile.view"]

_OFFICE_KEYS = ["product.read", "media.download", "ai.call", "ai.generate", "new_product.view"]
_COMMERCE_KEYS = [
    "product.read", "product.edit", "media.download", "ai.call", "ai.generate",
    "ai.customer_service", "competitor.view", "new_product.view",
]
_VISUAL_KEYS = [
    "product.read", "product.edit", "media.upload", "media.review", "media.download",
    "tag.edit", "ai.call", "ai.generate", "ai.customer_service", "new_product.view",
]

GROUP_PERMISSION_KEYS = {
    EXECUTIVE_OFFICE_GROUP_NAME: [key for key, _, _ in PERMISSION_DEFS if key != SYSTEM_ADMIN_PERMISSION],
    HR_ADMIN_GROUP_NAME: list(_OFFICE_KEYS),
    FINANCE_GROUP_NAME: list(_OFFICE_KEYS),
    PRODUCT_DEPARTMENT_GROUP_NAME: [
        "product.read", "product.create", "product.edit", PRODUCT_QA_MANAGE_PERMISSION,
        "product.delete", "product.review",
        "media.download", "tag.edit", "ai.call", "ai.generate", "ai.customer_service",
        "competitor.view", "new_product.view", "export.approved",
    ],
    INTERNATIONAL_TRADE_GROUP_NAME: list(_COMMERCE_KEYS),
    CROSS_BORDER_ECOMMERCE_GROUP_NAME: list(_COMMERCE_KEYS),
    ECOMMERCE_ONE_GROUP_NAME: list(_COMMERCE_KEYS),
    BUSINESS_GROUP_NAME: [
        "product.read", PRODUCT_QA_MANAGE_PERMISSION, "media.download", "ai.call", "ai.generate",
        "ai.customer_service", "new_product.view",
    ],
    QUALITY_GROUP_NAME: [
        "product.read", "product.edit", PRODUCT_QA_MANAGE_PERMISSION, "product.review", "media.review", "media.download",
        "tag.edit", "ai.call", "ai.customer_service", "new_product.view",
    ],
    VISUAL_ONE_GROUP_NAME: list(_VISUAL_KEYS),
    BRAND_GROUP_NAME: list(_VISUAL_KEYS) + ["competitor.view"],
    MERCHANDISING_GROUP_NAME: [
        "product.read", "media.download", "ai.call", "ai.customer_service", "new_product.view",
    ],
    FINANCIAL_SERVICES_GROUP_NAME: list(_OFFICE_KEYS),
    VISUAL_TWO_GROUP_NAME: list(_VISUAL_KEYS),
    IT_GROUP_NAME: [key for key, _, _ in PERMISSION_DEFS if key != SYSTEM_ADMIN_PERMISSION],
}

for _group_name in (EXECUTIVE_OFFICE_GROUP_NAME, IT_GROUP_NAME):
    if TOOL_MANAGE_PERMISSION not in GROUP_PERMISSION_KEYS[_group_name]:
        GROUP_PERMISSION_KEYS[_group_name].append(TOOL_MANAGE_PERMISSION)

for _group_name in (FINANCE_GROUP_NAME, EXECUTIVE_OFFICE_GROUP_NAME, IT_GROUP_NAME):
    if ECOMMERCE_DATA_FILL_PERMISSION not in GROUP_PERMISSION_KEYS[_group_name]:
        GROUP_PERMISSION_KEYS[_group_name].append(ECOMMERCE_DATA_FILL_PERMISSION)

PERMISSION_ROUTE_MAP = {
    "ai.generate": ["/"],
    "ai.customer_service": ["/customer-service"],
    "history.view": ["/history"],
    "profile.view": ["/profile", "/tools"],
    "product.read": ["/products", "/assets", "/assets/search", "/products/drafts"],
    "product.create": ["/products/create", "/products/create/:draftId"],
    "product.edit": ["/products/create", "/products/edit/:sku", "/products/drafts", "/products/qa/new"],
    PRODUCT_QA_MANAGE_PERMISSION: ["/products/qa/new"],
    "product.delete": ["/products"],
    ECOMMERCE_DATA_FILL_PERMISSION: ["/tools/ecommerce-data-fill"],
    SYSTEM_ADMIN_PERMISSION: [
        "/knowledge-base",
        "/file-knowledge",
        "/admin/users",
        "/admin/groups",
        "/admin/settings",
        "/admin/logs",
        "/admin/tools",
        "/admin/department-workbench",
        "/admin/model-governance",
    ],
}

DEFAULT_TOOL_DEFS = [
    {
        "tool_key": "ai_create",
        "name": "AI 创作",
        "description": "图像与视频生成工作区",
        "category": "AI 工具",
        "icon_key": "sparkles",
        "route_path": "/",
        "permission_key": "ai.generate",
        "sort_order": 10,
    },
    {
        "tool_key": "customer_service",
        "name": "智能客服",
        "description": "产品与业务知识问答",
        "category": "AI 工具",
        "icon_key": "message-circle",
        "route_path": "/customer-service",
        "permission_key": "ai.customer_service",
        "sort_order": 20,
    },
    {
        "tool_key": "product_management",
        "name": "产品管理",
        "description": "产品资料与草稿维护",
        "category": "业务工具",
        "icon_key": "package",
        "route_path": "/products",
        "permission_key": "product.read",
        "sort_order": 30,
    },
    {
        "tool_key": "asset_library",
        "name": "素材库",
        "description": "产品视觉素材管理",
        "category": "业务工具",
        "icon_key": "image",
        "route_path": "/assets",
        "permission_key": "product.read",
        "sort_order": 40,
    },
    {
        "tool_key": "ecommerce_data_fill",
        "name": "电商数据自动填表",
        "description": "电商数据分析表、周月报和亚马逊库存表填写",
        "category": "财务工具",
        "icon_key": "table-properties",
        "route_path": "/tools/ecommerce-data-fill",
        "permission_key": ECOMMERCE_DATA_FILL_PERMISSION,
        "sort_order": 50,
    },
]
