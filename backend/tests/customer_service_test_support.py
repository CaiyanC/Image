from app.models import Product, ProductBusiness, ProductContent, ProductQa, ProductSpecs


def _add_product(
    db,
    sku,
    name,
    category,
    capacity,
    material,
    heat_source,
    features,
    scenarios,
    weight,
    *,
    sub_category=None,
    price_positioning="中端",
):
    product = db.query(Product).filter(Product.sku == sku).first()
    if product is None:
        product = Product(id=f"route-{sku}", sku=sku)
        db.add(product)
    product.barcode = f"{sum((index + 1) * ord(char) for index, char in enumerate(str(sku))):012d}"
    product.product_name_cn = name
    product.product_name_en = name
    product.brand = "alocs爱路客"
    product.category = category
    product.sub_category = sub_category
    product.product_level = "A类品"
    product.lifecycle_status = "常规品"
    product.person_in_charge = "RouteTest"

    specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
    if specs is None:
        specs = ProductSpecs(id=f"route-specs-{sku}", product_id=product.id)
        db.add(specs)
    specs.capacity = capacity
    specs.gross_weight_g = weight
    specs.body_material = material
    specs.color = "本色"
    specs.surface_finish = "硬质氧化"
    specs.heat_source = heat_source
    specs.power = "/"
    specs.technical_advantages = features

    business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).first()
    if business is None:
        business = ProductBusiness(id=f"route-biz-{sku}", product_id=product.id)
        db.add(business)
    business.top_selling_points = features
    business.target_audience = "户外用户"
    business.positioning = features
    business.price_positioning = price_positioning
    business.usage_scenarios = scenarios

    content = db.query(ProductContent).filter(ProductContent.product_id == product.id).first()
    if content is None:
        content = ProductContent(id=f"route-content-{sku}", product_id=product.id)
        db.add(content)
    content.title_cn = name
    content.long_description_cn = f"{name} {features} {scenarios}"
    content.search_keywords = f"{name},{category},{heat_source}"


def _add_product_qa(db, sku, question, answer, *, tags="", priority=100):
    product = db.query(Product).filter(Product.sku == sku).first()
    assert product is not None, sku
    db.add(
        ProductQa(
            id=f"route-qa-{sku}-{abs(hash((question, answer))) % 10_000_000}",
            product_id=product.id,
            question=question,
            answer=answer,
            tags=tags,
            priority=priority,
            integrity_status="approved",
        )
    )
