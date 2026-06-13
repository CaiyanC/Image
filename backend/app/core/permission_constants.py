MANAGEMENT_GROUP_NAME = "管理层"
PRODUCT_TEAM_GROUP_NAME = "产品团队"
DESIGN_TEAM_GROUP_NAME = "设计团队"
ECOMMERCE_GROUP_NAME = "电商运营"
OVERSEAS_MARKETING_GROUP_NAME = "海外营销"
AI_CONTENT_GROUP_NAME = "AI内容岗"
CUSTOMER_SERVICE_GROUP_NAME = "客服团队"
AI_ENGINEER_GROUP_NAME = "AI工程师"
DEALER_GROUP_NAME = "经销商"
INFLUENCER_GROUP_NAME = "外部达人"
AD_AGENCY_GROUP_NAME = "广告代理商"

DEFAULT_GROUPS = [
    (PRODUCT_TEAM_GROUP_NAME, "产品管理部门，负责产品元数据录入与维护"),
    (DESIGN_TEAM_GROUP_NAME, "设计部门，负责产品视觉素材与 AI 生成"),
    (ECOMMERCE_GROUP_NAME, "电商运营岗位"),
    (OVERSEAS_MARKETING_GROUP_NAME, "海外市场营销"),
    (AI_CONTENT_GROUP_NAME, "AI 内容生成岗位"),
    (CUSTOMER_SERVICE_GROUP_NAME, "客户服务"),
    (MANAGEMENT_GROUP_NAME, "管理决策层"),
    (AI_ENGINEER_GROUP_NAME, "AI 技术团队"),
    (DEALER_GROUP_NAME, "外部经销商"),
    (INFLUENCER_GROUP_NAME, "外部 KOL/达人"),
    (AD_AGENCY_GROUP_NAME, "广告代理商"),
]

PRESET_GROUP_NAMES = {name for name, _ in DEFAULT_GROUPS}

PERMISSION_DEFS = [
    ("history.view", "查看历史记录", "page"),
    ("profile.view", "查看个人资料", "page"),
    ("category.read", "查看产品品类", "api"),
    ("product.read", "查看产品", "page"),
    ("product.create", "创建产品", "button"),
    ("product.edit", "编辑产品", "button"),
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
]

ROUTE_DEFS = [
    ("/customer-service", "智能客服", "page"),
    ("/", "工作区", "page"),
    ("/history", "历史记录", "page"),
    ("/profile", "个人资料", "page"),
    ("/products", "产品管理", "page"),
    ("/products/create", "新增产品", "page"),
    ("/products/edit/:sku", "编辑产品", "page"),
    ("/products/drafts", "草稿箱", "page"),
    ("/admin/users", "用户管理", "page"),
    ("/admin/groups", "团队权限", "page"),
    ("/admin/settings", "系统设置", "page"),
    ("/admin/logs", "操作日志", "page"),
]

COMMON_PERMISSION_KEYS = ["history.view", "profile.view"]

GROUP_PERMISSION_KEYS = {
    MANAGEMENT_GROUP_NAME: [key for key, _, _ in PERMISSION_DEFS],
    PRODUCT_TEAM_GROUP_NAME: [
        "product.read", "product.create", "product.edit", "product.review",
        "media.download", "tag.edit", "ai.call", "ai.generate",
        "ai.customer_service", "competitor.view", "new_product.view",
    ],
    DESIGN_TEAM_GROUP_NAME: [
        "product.read", "product.edit", "media.upload", "media.review",
        "media.download", "ai.call", "ai.generate", "ai.customer_service",
        "new_product.view",
    ],
    AI_ENGINEER_GROUP_NAME: [
        "ai.call", "ai.generate", "ai.customer_service", "ai.authorize",
        "media.download", "new_product.view",
    ],
    AI_CONTENT_GROUP_NAME: [
        "product.read", "media.download", "ai.call", "ai.generate",
        "ai.customer_service", "competitor.view", "new_product.view",
    ],
    ECOMMERCE_GROUP_NAME: [
        "product.read", "product.edit", "media.download", "ai.call",
        "ai.generate", "ai.customer_service", "new_product.view",
    ],
    OVERSEAS_MARKETING_GROUP_NAME: [
        "product.read", "media.download", "ai.call", "ai.generate",
        "ai.customer_service", "competitor.view", "new_product.view",
    ],
    CUSTOMER_SERVICE_GROUP_NAME: ["product.read", "ai.call", "ai.customer_service"],
    DEALER_GROUP_NAME: ["product.read", "media.download"],
    INFLUENCER_GROUP_NAME: ["product.read", "media.download"],
    AD_AGENCY_GROUP_NAME: ["product.read", "media.download"],
}

PERMISSION_ROUTE_MAP = {
    "ai.generate": ["/"],
    "ai.customer_service": ["/customer-service"],
    "history.view": ["/history"],
    "profile.view": ["/profile"],
    "product.read": ["/products", "/products/drafts"],
    "product.create": ["/products/create"],
    "product.edit": ["/products/create", "/products/edit/:sku", "/products/drafts"],
    "product.delete": ["/products"],
}
