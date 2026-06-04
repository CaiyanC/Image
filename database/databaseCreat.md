products表：
-- Table: public.products

-- DROP TABLE IF EXISTS public.products;

CREATE TABLE IF NOT EXISTS public.products
(
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    sku character varying(100) COLLATE pg_catalog."default" NOT NULL,
    barcode character varying(100) COLLATE pg_catalog."default",
    product_name_cn character varying(255) COLLATE pg_catalog."default" NOT NULL,
    product_name_en character varying(255) COLLATE pg_catalog."default",
    brand character varying(100) COLLATE pg_catalog."default" NOT NULL,
    series character varying(100) COLLATE pg_catalog."default",
    category character varying(100) COLLATE pg_catalog."default" NOT NULL,
    sub_category character varying(100) COLLATE pg_catalog."default",
    sales_region character varying(100) COLLATE pg_catalog."default",
    listing_channel character varying(255) COLLATE pg_catalog."default",
    product_level character varying(20) COLLATE pg_catalog."default",
    lifecycle_status character varying(50) COLLATE pg_catalog."default",
    launch_date date,
    person_in_charge character varying(100) COLLATE pg_catalog."default",
    active_flag boolean NOT NULL DEFAULT true,
    sync_flag boolean DEFAULT false,
    quality_note text COLLATE pg_catalog."default",
    status_note text COLLATE pg_catalog."default",
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT products_pkey PRIMARY KEY (id),
    CONSTRAINT products_sku_key UNIQUE (sku)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.products
    OWNER to postgres;

product_specs：
-- Table: public.product_specs

-- DROP TABLE IF EXISTS public.product_specs;

CREATE TABLE IF NOT EXISTS public.product_specs
(
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL,
    size_info text COLLATE pg_catalog."default",
    package_size text COLLATE pg_catalog."default",
    gross_weight text COLLATE pg_catalog."default",
    body_material text COLLATE pg_catalog."default",
    surface_finish text COLLATE pg_catalog."default",
    color text COLLATE pg_catalog."default",
    capacity text COLLATE pg_catalog."default",
    power text COLLATE pg_catalog."default",
    heat_source text COLLATE pg_catalog."default",
    certification text COLLATE pg_catalog."default",
    technical_advantages text COLLATE pg_catalog."default",
    usage_instruction text COLLATE pg_catalog."default",
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT product_specs_pkey PRIMARY KEY (id),
    CONSTRAINT product_specs_product_id_fkey FOREIGN KEY (product_id)
        REFERENCES public.products (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.product_specs
    OWNER to postgres;
-- Index: idx_product_specs_product_id

-- DROP INDEX IF EXISTS public.idx_product_specs_product_id;

CREATE INDEX IF NOT EXISTS idx_product_specs_product_id
    ON public.product_specs USING btree
    (product_id ASC NULLS LAST)
    TABLESPACE pg_default;

product_qa：
-- Table: public.product_qa

-- DROP TABLE IF EXISTS public.product_qa;

CREATE TABLE IF NOT EXISTS public.product_qa
(
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL,
    question text COLLATE pg_catalog."default" NOT NULL,
    answer text COLLATE pg_catalog."default" NOT NULL,
    high_freq_negative_words text COLLATE pg_catalog."default",
    response_tone text COLLATE pg_catalog."default",
    tags text COLLATE pg_catalog."default",
    source character varying(100) COLLATE pg_catalog."default",
    ai_usable_flag boolean NOT NULL DEFAULT true,
    priority integer,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT product_qa_pkey PRIMARY KEY (id),
    CONSTRAINT product_qa_product_id_fkey FOREIGN KEY (product_id)
        REFERENCES public.products (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.product_qa
    OWNER to postgres;
-- Index: idx_product_qa_ai_usable_flag

-- DROP INDEX IF EXISTS public.idx_product_qa_ai_usable_flag;

CREATE INDEX IF NOT EXISTS idx_product_qa_ai_usable_flag
    ON public.product_qa USING btree
    (ai_usable_flag ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_product_qa_product_id

-- DROP INDEX IF EXISTS public.idx_product_qa_product_id;

CREATE INDEX IF NOT EXISTS idx_product_qa_product_id
    ON public.product_qa USING btree
    (product_id ASC NULLS LAST)
    TABLESPACE pg_default;

product_media：
-- Table: public.product_media

-- DROP TABLE IF EXISTS public.product_media;

CREATE TABLE IF NOT EXISTS public.product_media
(
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL,
    sku character varying(100) COLLATE pg_catalog."default" NOT NULL,
    media_layer character varying(50) COLLATE pg_catalog."default" NOT NULL DEFAULT 'raw'::character varying,
    media_group character varying(100) COLLATE pg_catalog."default" NOT NULL,
    media_type character varying(100) COLLATE pg_catalog."default" NOT NULL,
    file_name character varying(255) COLLATE pg_catalog."default" NOT NULL,
    file_path text COLLATE pg_catalog."default" NOT NULL,
    media_level character varying(10) COLLATE pg_catalog."default" NOT NULL,
    is_real_product boolean NOT NULL DEFAULT true,
    is_ai_generated boolean NOT NULL DEFAULT false,
    is_competitor boolean NOT NULL DEFAULT false,
    is_public boolean NOT NULL DEFAULT false,
    ai_customer_usable boolean NOT NULL DEFAULT false,
    ai_marketing_usable boolean NOT NULL DEFAULT false,
    ai_reference_usable boolean NOT NULL DEFAULT false,
    editable_flag boolean NOT NULL DEFAULT false,
    review_status character varying(50) COLLATE pg_catalog."default" NOT NULL DEFAULT 'pending'::character varying,
    authorization_status character varying(50) COLLATE pg_catalog."default" NOT NULL DEFAULT 'unknown'::character varying,
    forbidden_usage text COLLATE pg_catalog."default",
    channel_name character varying(100) COLLATE pg_catalog."default",
    language character varying(20) COLLATE pg_catalog."default",
    media_version character varying(50) COLLATE pg_catalog."default",
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    page_type character varying(100) COLLATE pg_catalog."default",
    file_url text COLLATE pg_catalog."default",
    file_format character varying(20) COLLATE pg_catalog."default",
    tag_list text COLLATE pg_catalog."default",
    CONSTRAINT product_media_pkey PRIMARY KEY (id),
    CONSTRAINT product_media_product_id_fkey FOREIGN KEY (product_id)
        REFERENCES public.products (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.product_media
    OWNER to postgres;
-- Index: idx_product_media_channel_name

-- DROP INDEX IF EXISTS public.idx_product_media_channel_name;

CREATE INDEX IF NOT EXISTS idx_product_media_channel_name
    ON public.product_media USING btree
    (channel_name COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_product_media_media_group

-- DROP INDEX IF EXISTS public.idx_product_media_media_group;

CREATE INDEX IF NOT EXISTS idx_product_media_media_group
    ON public.product_media USING btree
    (media_group COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_product_media_media_layer

-- DROP INDEX IF EXISTS public.idx_product_media_media_layer;

CREATE INDEX IF NOT EXISTS idx_product_media_media_layer
    ON public.product_media USING btree
    (media_layer COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_product_media_media_version

-- DROP INDEX IF EXISTS public.idx_product_media_media_version;

CREATE INDEX IF NOT EXISTS idx_product_media_media_version
    ON public.product_media USING btree
    (media_version COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_product_media_page_type

-- DROP INDEX IF EXISTS public.idx_product_media_page_type;

CREATE INDEX IF NOT EXISTS idx_product_media_page_type
    ON public.product_media USING btree
    (page_type COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_product_media_product_id

-- DROP INDEX IF EXISTS public.idx_product_media_product_id;

CREATE INDEX IF NOT EXISTS idx_product_media_product_id
    ON public.product_media USING btree
    (product_id ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_product_media_review_status

-- DROP INDEX IF EXISTS public.idx_product_media_review_status;

CREATE INDEX IF NOT EXISTS idx_product_media_review_status
    ON public.product_media USING btree
    (review_status COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_product_media_sku

-- DROP INDEX IF EXISTS public.idx_product_media_sku;

CREATE INDEX IF NOT EXISTS idx_product_media_sku
    ON public.product_media USING btree
    (sku COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;

product_content：
-- Table: public.product_content

-- DROP TABLE IF EXISTS public.product_content;

CREATE TABLE IF NOT EXISTS public.product_content
(
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL,
    title_cn text COLLATE pg_catalog."default",
    title_en text COLLATE pg_catalog."default",
    long_description_cn text COLLATE pg_catalog."default",
    long_description_en text COLLATE pg_catalog."default",
    long_description_ja text COLLATE pg_catalog."default",
    search_keywords text COLLATE pg_catalog."default",
    amazon_title text COLLATE pg_catalog."default",
    website_title text COLLATE pg_catalog."default",
    bullet_points text COLLATE pg_catalog."default",
    a_plus_content text COLLATE pg_catalog."default",
    listing_cn text COLLATE pg_catalog."default",
    listing_en text COLLATE pg_catalog."default",
    listing_ja text COLLATE pg_catalog."default",
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT product_content_pkey PRIMARY KEY (id),
    CONSTRAINT product_content_product_id_fkey FOREIGN KEY (product_id)
        REFERENCES public.products (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.product_content
    OWNER to postgres;
-- Index: idx_product_content_product_id

-- DROP INDEX IF EXISTS public.idx_product_content_product_id;

CREATE INDEX IF NOT EXISTS idx_product_content_product_id
    ON public.product_content USING btree
    (product_id ASC NULLS LAST)
    TABLESPACE pg_default;

product_business：
-- Table: public.product_business

-- DROP TABLE IF EXISTS public.product_business;

CREATE TABLE IF NOT EXISTS public.product_business
(
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL,
    top_selling_points text COLLATE pg_catalog."default",
    target_audience text COLLATE pg_catalog."default",
    positioning text COLLATE pg_catalog."default",
    price_positioning character varying(50) COLLATE pg_catalog."default",
    emotional_value text COLLATE pg_catalog."default",
    usage_scenarios text COLLATE pg_catalog."default",
    competitor_benchmark text COLLATE pg_catalog."default",
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT product_business_pkey PRIMARY KEY (id),
    CONSTRAINT product_business_product_id_fkey FOREIGN KEY (product_id)
        REFERENCES public.products (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.product_business
    OWNER to postgres;
-- Index: idx_product_business_product_id

-- DROP INDEX IF EXISTS public.idx_product_business_product_id;

CREATE INDEX IF NOT EXISTS idx_product_business_product_id
    ON public.product_business USING btree
    (product_id ASC NULLS LAST)
    TABLESPACE pg_default;

ai_generated_assets：
-- Table: public.ai_generated_assets

-- DROP TABLE IF EXISTS public.ai_generated_assets;

CREATE TABLE IF NOT EXISTS public.ai_generated_assets
(
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL,
    sku character varying(100) COLLATE pg_catalog."default" NOT NULL,
    prompt_text text COLLATE pg_catalog."default" NOT NULL,
    generated_file_name character varying(255) COLLATE pg_catalog."default" NOT NULL,
    generated_file_path text COLLATE pg_catalog."default" NOT NULL,
    usage_scenario character varying(100) COLLATE pg_catalog."default",
    review_status character varying(50) COLLATE pg_catalog."default" NOT NULL DEFAULT 'pending'::character varying,
    is_available boolean NOT NULL DEFAULT false,
    is_public boolean NOT NULL DEFAULT false,
    is_for_reference_only boolean NOT NULL DEFAULT true,
    created_by character varying(100) COLLATE pg_catalog."default",
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    CONSTRAINT ai_generated_assets_pkey PRIMARY KEY (id),
    CONSTRAINT ai_generated_assets_product_id_fkey FOREIGN KEY (product_id)
        REFERENCES public.products (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.ai_generated_assets
    OWNER to postgres;
-- Index: idx_ai_generated_assets_product_id

-- DROP INDEX IF EXISTS public.idx_ai_generated_assets_product_id;

CREATE INDEX IF NOT EXISTS idx_ai_generated_assets_product_id
    ON public.ai_generated_assets USING btree
    (product_id ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_ai_generated_assets_review_status

-- DROP INDEX IF EXISTS public.idx_ai_generated_assets_review_status;

CREATE INDEX IF NOT EXISTS idx_ai_generated_assets_review_status
    ON public.ai_generated_assets USING btree
    (review_status COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: idx_ai_generated_assets_sku

-- DROP INDEX IF EXISTS public.idx_ai_generated_assets_sku;

CREATE INDEX IF NOT EXISTS idx_ai_generated_assets_sku
    ON public.ai_generated_assets USING btree
    (sku COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;

users：
-- Table: public.users

-- DROP TABLE IF EXISTS public.users;

CREATE TABLE IF NOT EXISTS public.users
(
    id character varying(36) COLLATE pg_catalog."default" NOT NULL,
    username character varying(50) COLLATE pg_catalog."default" NOT NULL,
    email character varying(100) COLLATE pg_catalog."default",
    hashed_password character varying(255) COLLATE pg_catalog."default" NOT NULL,
    role character varying(20) COLLATE pg_catalog."default" NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT users_pkey PRIMARY KEY (id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.users
    OWNER to postgres;
-- Index: ix_users_email

-- DROP INDEX IF EXISTS public.ix_users_email;

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email
    ON public.users USING btree
    (email COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
-- Index: ix_users_username

-- DROP INDEX IF EXISTS public.ix_users_username;

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username
    ON public.users USING btree
    (username COLLATE pg_catalog."default" ASC NULLS LAST)
    TABLESPACE pg_default;
