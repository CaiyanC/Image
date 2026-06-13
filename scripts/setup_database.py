"""
Complete database setup script – drops old tables and creates all 34 new tables
based on 字段—数据库设计 5.25.docx
"""
import os

import psycopg2
from psycopg2 import sql

CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "database": os.getenv("PGDATABASE", "product_knowledge"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", ""),
}


def get_connection():
    return psycopg2.connect(**CONFIG)


# ── DROP ALL EXISTING TABLES (CASCADE handles FK dependencies) ──────────
DROP_TABLES = [
    "product_drafts",
    "product_prompts",
    "generations",
    "product_certifications",
    "product_keywords",
    "product_listing_channels",
    "product_sales_regions",
    "qa_tag_relations",
    "qa_answers",
    "product_qa_negative",
    "product_qa",
    "product_media",
    "ai_generated_assets",
    "product_specs",
    "product_business",
    "product_content",
    "user_groups",
    "group_permissions",
    "permission_routes",
    "operation_logs",
    "field_configs",
    "entity_field_values",
    "system_config",
    "product_categories",
    "listing_channels",
    "sales_regions",
    "certifications",
    "keywords",
    "qa_tags",
    "permissions",
    "routes",
    "groups",
    "users",
    "products",
]


# ── CREATE ALL TABLES ───────────────────────────────────────────────────
CREATE_STATEMENTS = [
    # ===================================================================
    # 一、核心业务表 L1-L7
    # ===================================================================

    # L1: 产品主表
    """
    CREATE TABLE products (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        sku VARCHAR(100) NOT NULL UNIQUE,
        barcode VARCHAR(100),
        product_name_cn VARCHAR(255) NOT NULL,
        product_name_en VARCHAR(255),
        brand VARCHAR(100) NOT NULL,
        series VARCHAR(100),
        category VARCHAR(100),
        sub_category VARCHAR(100),
        listing_channel TEXT,
        sales_region TEXT,
        product_level VARCHAR(20),
        launch_date DATE,
        lifecycle_status VARCHAR(50),
        person_in_charge VARCHAR(100),
        active_flag BOOLEAN NOT NULL DEFAULT TRUE,
        sync_flag BOOLEAN DEFAULT FALSE,
        quality_note TEXT,
        status_note TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # L2: 规格表
    """
    CREATE TABLE product_specs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        size_info TEXT,
        capacity TEXT,
        gross_weight_g NUMERIC(10,3),
        body_material TEXT,
        color TEXT,
        surface_finish TEXT,
        heat_source TEXT,
        power TEXT,
        technical_advantages TEXT,
        usage_instruction TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # L3: 商业信息表
    """
    CREATE TABLE product_business (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        top_selling_points TEXT,
        target_audience TEXT,
        positioning TEXT,
        price_positioning TEXT,
        emotional_value TEXT,
        usage_scenarios TEXT,
        competitor_benchmark TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # L4: 内容素材表
    """
    CREATE TABLE product_content (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        title_en TEXT,
        title_cn TEXT,
        long_description_en TEXT,
        long_description_cn TEXT,
        long_description_ja TEXT,
        search_keywords TEXT,
        amazon_title TEXT,
        website_title TEXT,
        bullet_points TEXT,
        a_plus_content TEXT,
        listing_cn TEXT,
        listing_en TEXT,
        listing_ja TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # L5: QA 问答表
    """
    CREATE TABLE product_qa (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        tags TEXT,
        priority INTEGER,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # L5 差评与应对表
    """
    CREATE TABLE product_qa_negative (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        high_freq_negative_words TEXT,
        response_tone TEXT,
        priority INTEGER,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # L5: QA 答案子表（一个QA多个答案）
    """
    CREATE TABLE qa_answers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        qa_id UUID NOT NULL REFERENCES product_qa(id) ON DELETE CASCADE,
        answer_text TEXT NOT NULL,
        answer_lang VARCHAR(20),
        answer_type VARCHAR(50),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # L6: 视觉素材表
    """
    CREATE TABLE product_media (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        sku VARCHAR(100) NOT NULL,
        media_layer VARCHAR(50) NOT NULL DEFAULT 'raw',
        media_group VARCHAR(100) NOT NULL,
        media_type VARCHAR(100),
        channel_name VARCHAR(100),
        page_type VARCHAR(100),
        media_version VARCHAR(50),
        file_name VARCHAR(255) NOT NULL,
        file_path TEXT NOT NULL,
        file_url TEXT,
        file_format VARCHAR(20),
        media_level VARCHAR(10) NOT NULL DEFAULT 'C',
        is_real_product BOOLEAN NOT NULL DEFAULT TRUE,
        is_ai_generated BOOLEAN NOT NULL DEFAULT FALSE,
        is_competitor BOOLEAN NOT NULL DEFAULT FALSE,
        is_public BOOLEAN NOT NULL DEFAULT FALSE,
        ai_customer_usable BOOLEAN NOT NULL DEFAULT FALSE,
        ai_marketing_usable BOOLEAN NOT NULL DEFAULT FALSE,
        ai_reference_usable BOOLEAN NOT NULL DEFAULT FALSE,
        editable_flag BOOLEAN NOT NULL DEFAULT FALSE,
        review_status VARCHAR(50) NOT NULL DEFAULT 'pending',
        authorization_status VARCHAR(50) NOT NULL DEFAULT 'unknown',
        forbidden_usage TEXT,
        language VARCHAR(20),
        tag_list TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # L7: AI 生成资产表
    """
    CREATE TABLE ai_generated_assets (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        sku VARCHAR(100) NOT NULL,
        prompt_text TEXT NOT NULL,
        generated_file_name VARCHAR(255) NOT NULL,
        generated_file_path TEXT NOT NULL,
        usage_scenario VARCHAR(100),
        review_status VARCHAR(50) NOT NULL DEFAULT 'pending',
        is_available BOOLEAN NOT NULL DEFAULT FALSE,
        is_public BOOLEAN NOT NULL DEFAULT FALSE,
        is_for_reference_only BOOLEAN NOT NULL DEFAULT TRUE,
        created_by VARCHAR(100),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # ===================================================================
    # 二、字典表 + 多对多关联表
    # ===================================================================

    # 渠道字典
    """
    CREATE TABLE listing_channels (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        channel_name VARCHAR(100) NOT NULL UNIQUE,
        channel_code VARCHAR(50),
        description TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 产品-渠道关联
    """
    CREATE TABLE product_listing_channels (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        channel_id UUID NOT NULL REFERENCES listing_channels(id) ON DELETE CASCADE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(product_id, channel_id)
    )
    """,

    # 地区字典
    """
    CREATE TABLE sales_regions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        region_name VARCHAR(100) NOT NULL UNIQUE,
        region_code VARCHAR(50),
        description TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 产品-地区关联
    """
    CREATE TABLE product_sales_regions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        region_id UUID NOT NULL REFERENCES sales_regions(id) ON DELETE CASCADE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(product_id, region_id)
    )
    """,

    # 认证字典
    """
    CREATE TABLE certifications (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        certification_name VARCHAR(100) NOT NULL UNIQUE,
        certification_code VARCHAR(50),
        description TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 产品-认证关联
    """
    CREATE TABLE product_certifications (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        certification_id UUID NOT NULL REFERENCES certifications(id) ON DELETE CASCADE,
        certification_file_path TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(product_id, certification_id)
    )
    """,

    # 关键词字典
    """
    CREATE TABLE keywords (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        keyword VARCHAR(255) NOT NULL,
        keyword_level VARCHAR(20),
        description TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 产品-关键词关联
    """
    CREATE TABLE product_keywords (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        keyword_id UUID NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(product_id, keyword_id)
    )
    """,

    # QA标签字典
    """
    CREATE TABLE qa_tags (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tag_name VARCHAR(100) NOT NULL UNIQUE,
        tag_type VARCHAR(50),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # QA-标签关联
    """
    CREATE TABLE qa_tag_relations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        qa_id UUID NOT NULL REFERENCES product_qa(id) ON DELETE CASCADE,
        tag_id UUID NOT NULL REFERENCES qa_tags(id) ON DELETE CASCADE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(qa_id, tag_id)
    )
    """,

    # ===================================================================
    # 三、用户与权限系统
    # ===================================================================

    # 用户表
    """
    CREATE TABLE users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username VARCHAR(100) NOT NULL UNIQUE,
        user_type VARCHAR(50) NOT NULL DEFAULT 'human',
        password_hash TEXT NOT NULL,
        display_name VARCHAR(100),
        email VARCHAR(255),
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 用户组/角色表
    """
    CREATE TABLE groups (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        group_name VARCHAR(100) NOT NULL UNIQUE,
        description TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 用户-用户组关联
    """
    CREATE TABLE user_groups (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        group_role VARCHAR(50) DEFAULT 'member',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(user_id, group_id)
    )
    """,

    # 权限表
    """
    CREATE TABLE permissions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        permission_key VARCHAR(100) NOT NULL UNIQUE,
        permission_name VARCHAR(100) NOT NULL,
        permission_type VARCHAR(50),
        description TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 用户组-权限关联
    """
    CREATE TABLE group_permissions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(group_id, permission_id)
    )
    """,

    # 路由表
    """
    CREATE TABLE routes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        route_path VARCHAR(255) NOT NULL,
        route_name VARCHAR(100),
        parent_id UUID REFERENCES routes(id),
        route_type VARCHAR(50),
        component_path VARCHAR(255),
        description TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 权限-路由关联
    """
    CREATE TABLE permission_routes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
        route_id UUID NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(permission_id, route_id)
    )
    """,

    # ===================================================================
    # 四、日志与配置
    # ===================================================================

    # 操作日志表
    """
    CREATE TABLE operation_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        operator_id UUID REFERENCES users(id),
        operator_type VARCHAR(20) NOT NULL,
        action_type VARCHAR(50) NOT NULL,
        action_name VARCHAR(255) NOT NULL,
        target_type VARCHAR(100) NOT NULL,
        target_id VARCHAR(100) NOT NULL,
        target_name VARCHAR(255),
        request_data JSONB,
        response_data JSONB,
        status VARCHAR(50) NOT NULL,
        error_message TEXT,
        ip_address VARCHAR(50),
        user_agent TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 字段配置表
    """
    CREATE TABLE field_configs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        table_name VARCHAR(100) NOT NULL,
        field_name VARCHAR(100) NOT NULL,
        field_label VARCHAR(255),
        is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        is_visible BOOLEAN NOT NULL DEFAULT TRUE,
        is_required BOOLEAN NOT NULL DEFAULT FALSE,
        is_readonly BOOLEAN NOT NULL DEFAULT FALSE,
        is_editable BOOLEAN NOT NULL DEFAULT TRUE,
        is_list_visible BOOLEAN NOT NULL DEFAULT TRUE,
        is_detail_visible BOOLEAN NOT NULL DEFAULT TRUE,
        is_filterable BOOLEAN NOT NULL DEFAULT FALSE,
        is_searchable BOOLEAN NOT NULL DEFAULT FALSE,
        placeholder_text VARCHAR(255),
        help_text TEXT,
        default_value TEXT,
        config_scope VARCHAR(50) DEFAULT 'global',
        role_id UUID REFERENCES groups(id),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(table_name, field_name)
    )
    """,

    # 实体扩展字段值表（EAV）
    """
    CREATE TABLE entity_field_values (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        entity_type VARCHAR(100) NOT NULL,
        entity_id VARCHAR(100) NOT NULL,
        field_name VARCHAR(100) NOT NULL,
        field_value TEXT,
        value_type VARCHAR(50),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # ===================================================================
    # 五、遗留/兼容表
    # ===================================================================

    # 系统配置表（KV存储）
    """
    CREATE TABLE system_config (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        config_key VARCHAR(100) NOT NULL UNIQUE,
        config_value TEXT NOT NULL,
        description TEXT,
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 产品草稿表
    """
    CREATE TABLE product_drafts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID REFERENCES products(id),
        sku VARCHAR(100),
        draft_data JSONB NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'draft',
        created_by VARCHAR(100),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 类目字典表
    """
    CREATE TABLE product_categories (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        category_name VARCHAR(100) NOT NULL UNIQUE,
        parent_id UUID REFERENCES product_categories(id),
        description TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # 提示词模板表
    """
    CREATE TABLE product_prompts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID REFERENCES products(id),
        sku VARCHAR(100),
        prompt_name VARCHAR(255),
        prompt_type VARCHAR(100),
        prompt_text TEXT NOT NULL,
        version VARCHAR(50),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,

    # AI 生成历史记录表
    """
    CREATE TABLE generations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID REFERENCES users(id),
        product_id UUID REFERENCES products(id),
        sku VARCHAR(100),
        type VARCHAR(20) NOT NULL,
        prompt TEXT NOT NULL,
        negative_prompt TEXT,
        source_image_path TEXT,
        result_image_path TEXT,
        result_images JSONB,
        result_video_path TEXT,
        model_name VARCHAR(100) NOT NULL,
        parameters JSONB,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        error_message TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
]

# ── INDEXES ─────────────────────────────────────────────────────────────
INDEXES = [
    # products
    "CREATE INDEX idx_products_sku ON products(sku)",
    "CREATE INDEX idx_products_category ON products(category)",
    "CREATE INDEX idx_products_brand ON products(brand)",

    # product_specs
    "CREATE INDEX idx_product_specs_product_id ON product_specs(product_id)",

    # product_business
    "CREATE INDEX idx_product_business_product_id ON product_business(product_id)",

    # product_content
    "CREATE INDEX idx_product_content_product_id ON product_content(product_id)",

    # product_qa
    "CREATE INDEX idx_product_qa_product_id ON product_qa(product_id)",

    # product_qa_negative
    "CREATE INDEX idx_product_qa_negative_product_id ON product_qa_negative(product_id)",

    # qa_answers
    "CREATE INDEX idx_qa_answers_qa_id ON qa_answers(qa_id)",

    # product_media
    "CREATE INDEX idx_product_media_product_id ON product_media(product_id)",
    "CREATE INDEX idx_product_media_sku ON product_media(sku)",
    "CREATE INDEX idx_product_media_media_layer ON product_media(media_layer)",
    "CREATE INDEX idx_product_media_media_group ON product_media(media_group)",
    "CREATE INDEX idx_product_media_review_status ON product_media(review_status)",
    "CREATE INDEX idx_product_media_channel_name ON product_media(channel_name)",
    "CREATE INDEX idx_product_media_page_type ON product_media(page_type)",
    "CREATE INDEX idx_product_media_media_version ON product_media(media_version)",

    # ai_generated_assets
    "CREATE INDEX idx_ai_generated_assets_product_id ON ai_generated_assets(product_id)",
    "CREATE INDEX idx_ai_generated_assets_sku ON ai_generated_assets(sku)",
    "CREATE INDEX idx_ai_generated_assets_review_status ON ai_generated_assets(review_status)",

    # M2M tables
    "CREATE INDEX idx_plc_product_id ON product_listing_channels(product_id)",
    "CREATE INDEX idx_plc_channel_id ON product_listing_channels(channel_id)",
    "CREATE INDEX idx_psr_product_id ON product_sales_regions(product_id)",
    "CREATE INDEX idx_psr_region_id ON product_sales_regions(region_id)",
    "CREATE INDEX idx_pc_product_id ON product_certifications(product_id)",
    "CREATE INDEX idx_pc_certification_id ON product_certifications(certification_id)",
    "CREATE INDEX idx_pk_product_id ON product_keywords(product_id)",
    "CREATE INDEX idx_pk_keyword_id ON product_keywords(keyword_id)",

    # users & groups
    "CREATE UNIQUE INDEX idx_users_username ON users(username)",
    "CREATE UNIQUE INDEX idx_users_email ON users(email)",
    "CREATE INDEX idx_user_groups_user_id ON user_groups(user_id)",
    "CREATE INDEX idx_user_groups_group_id ON user_groups(group_id)",

    # permissions
    "CREATE INDEX idx_group_permissions_group_id ON group_permissions(group_id)",
    "CREATE INDEX idx_permission_routes_permission_id ON permission_routes(permission_id)",

    # operation_logs
    "CREATE INDEX idx_operation_logs_operator_id ON operation_logs(operator_id)",
    "CREATE INDEX idx_operation_logs_target_type_id ON operation_logs(target_type, target_id)",
    "CREATE INDEX idx_operation_logs_created_at ON operation_logs(created_at)",

    # generations
    "CREATE INDEX idx_generations_user_id ON generations(user_id)",
    "CREATE INDEX idx_generations_product_id ON generations(product_id)",
    "CREATE INDEX idx_generations_status ON generations(status)",

    # product_drafts
    "CREATE INDEX idx_product_drafts_status ON product_drafts(status)",
    "CREATE INDEX idx_product_drafts_product_id ON product_drafts(product_id)",

    # product_prompts
    "CREATE INDEX idx_product_prompts_product_id ON product_prompts(product_id)",

    # field_configs
    "CREATE INDEX idx_field_configs_table_field ON field_configs(table_name, field_name)",
]


# ── SEED DATA ────────────────────────────────────────────────────────────
def seed_data(conn):
    cur = conn.cursor()

    # 默认类目
    categories = [
        "待分类", "餐具", "茶具", "炊具", "锅具",
        "酒具", "炉具", "水具", "咖啡器具", "户外家具",
        "收纳包具", "登山杖", "电商专供", "经销商专供", "配件",
    ]
    for name in categories:
        cur.execute(
            "INSERT INTO product_categories (category_name) VALUES (%s) ON CONFLICT DO NOTHING",
            (name,),
        )

    # 默认渠道
    channels = [
        ("淘宝", "taobao"),
        ("京东", "jd"),
        ("拼多多", "pdd"),
        ("独立站", "d2c"),
        ("Amazon", "amazon"),
        ("eBay", "ebay"),
        ("阿里国际站", "alibaba"),
        ("速卖通", "aliexpress"),
        ("抖音", "douyin"),
        ("小红书", "xiaohongshu"),
        ("快手", "kuaishou"),
        ("得物", "dewu"),
    ]
    for name, code in channels:
        cur.execute(
            "INSERT INTO listing_channels (channel_name, channel_code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (name, code),
        )

    # 默认售卖地区
    regions = [
        ("国内", "CN"),
        ("美国", "US"),
        ("日本", "JP"),
        ("欧洲", "EU"),
    ]
    for name, code in regions:
        cur.execute(
            "INSERT INTO sales_regions (region_name, region_code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (name, code),
        )

    # 默认认证类型
    certs = [
        ("CE", "CE", "欧盟安全认证"),
        ("FCC", "FCC", "美国联邦通信认证"),
        ("RoHS", "RoHS", "有害物质限制"),
        ("FDA", "FDA", "美国食品药品认证"),
        ("LFGB", "LFGB", "德国食品接触材料"),
        ("GB", "GB", "中国国家标准"),
        ("UL", "UL", "美国保险商实验室"),
    ]
    for name, code, desc in certs:
        cur.execute(
            "INSERT INTO certifications (certification_name, certification_code, description) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (name, code, desc),
        )

    # 默认用户组
    groups = [
        ("产品团队", "产品管理部门，负责产品元数据录入与维护"),
        ("设计团队", "设计部门，负责产品视觉素材与 AI 生成"),
        ("电商运营", "电商运营岗位"),
        ("海外营销", "海外市场营销"),
        ("AI内容岗", "AI 内容生成岗位"),
        ("客服团队", "客户服务"),
        ("管理层", "管理决策层"),
        ("AI工程师", "AI 技术团队"),
        ("经销商", "外部经销商"),
        ("外部达人", "外部 KOL/达人"),
        ("广告代理商", "广告代理商"),
    ]
    for name, desc in groups:
        cur.execute(
            "INSERT INTO groups (group_name, description) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (name, desc),
        )

    # 默认权限
    perms = [
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
        ("competitor.view", "查看竞品图", "page"),
        ("new_product.view", "查看新品图", "page"),
        ("export.approved", "导出审批", "button"),
    ]
    for key, name, ptype in perms:
        cur.execute(
            "INSERT INTO permissions (permission_key, permission_name, permission_type) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (key, name, ptype),
        )

    # 默认路由
    route_list = [
        ("/", "工作区", None, "page"),
        ("/customer-service", "智能客服", None, "page"),
        ("/history", "历史记录", None, "page"),
        ("/products", "产品管理", None, "page"),
        ("/products/create", "新增产品", None, "page"),
        ("/products/drafts", "草稿箱", None, "page"),
        ("/admin/users", "用户管理", None, "page"),
        ("/admin/settings", "系统设置", None, "page"),
        ("/admin/groups", "用户组管理", None, "page"),
    ]
    for path, name, parent, rtype in route_list:
        cur.execute(
            "INSERT INTO routes (route_path, route_name, parent_id, route_type) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (path, name, parent, rtype),
        )

    # 默认管理员用户
    import uuid
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    admin_pw_hash = pwd_context.hash("admin123")
    admin_id = str(uuid.uuid4())
    cur.execute(
        """INSERT INTO users (id, username, user_type, password_hash, display_name, email, is_active)
           VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        (admin_id, "admin", "human", admin_pw_hash, "系统管理员", "admin@example.com", True),
    )

    # 管理员加入产品团队和管理层
    cur.execute("SELECT id FROM groups WHERE group_name IN ('产品团队', '管理层')")
    admin_groups = cur.fetchall()
    for g in admin_groups:
        cur.execute(
            "INSERT INTO user_groups (user_id, group_id, group_role) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (admin_id, g[0], "admin"),
        )

    conn.commit()
    cur.close()
    print("Seed data inserted successfully.")


# ── MAIN ─────────────────────────────────────────────────────────────────
def main():
    conn = get_connection()
    cur = conn.cursor()

    # 1. Drop all existing tables
    print("Dropping existing tables...")
    for table in DROP_TABLES:
        cur.execute(
            sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table))
        )
        print(f"  DROPPED: {table}")
    conn.commit()

    # 2. Create all new tables
    print("\nCreating new tables...")
    for stmt in CREATE_STATEMENTS:
        cur.execute(stmt)
        # Extract table name for logging
        line = stmt.strip().split("\n")[0]
        print(f"  CREATED: {line}")
    conn.commit()

    # 3. Create indexes
    print("\nCreating indexes...")
    for idx in INDEXES:
        cur.execute(idx)
    conn.commit()
    print("  All indexes created.")

    # 4. Seed default data
    print("\nSeeding data...")
    seed_data(conn)

    # 5. Verify
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
    )
    tables = cur.fetchall()
    print(f"\nVerification: {len(tables)} tables in public schema:")
    for t in tables:
        print(f"  ✓ {t[0]}")

    cur.close()
    conn.close()
    print("\nDatabase setup complete!")


if __name__ == "__main__":
    main()
