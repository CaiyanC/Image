"""Read a small, public listing preview from known marketplace product hosts."""

from html.parser import HTMLParser
import json

import httpx


def listing_url(platform: str, item_id: str) -> str:
    if platform == "jd":
        return f"https://item.jd.com/{item_id}.html"
    if platform == "taobao":
        return f"https://item.taobao.com/item.htm?id={item_id}"
    return f"https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id={item_id}"


def _products(value):
    if isinstance(value, list):
        for item in value:
            yield from _products(item)
    elif isinstance(value, dict):
        kinds = value.get("@type")
        if kinds == "Product" or isinstance(kinds, list) and "Product" in kinds:
            yield value
        yield from _products(value.get("@graph"))


class ListingMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.json_ld = None
        self.products = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.json_ld = []

    def handle_data(self, data):
        if self.json_ld is not None:
            self.json_ld.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or self.json_ld is None:
            return
        data, self.json_ld = self.json_ld, None
        try:
            self.products.extend(_products(json.loads("".join(data))))
        except (ValueError, RecursionError):
            pass


async def fetch_listing_preview(platform: str, item_id: str) -> dict:
    url = listing_url(platform, item_id)
    unavailable = {"status": "unavailable", "url": url, "message": "网页未提供可读取的商品资料，请粘贴商品页规格或详情。"}
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200 or "html" not in response.headers.get("content-type", "").lower():
                    return unavailable
                data = bytearray()
                async for part in response.aiter_bytes(chunk_size=8192):
                    data.extend(part)
                    if len(data) > 768_000:
                        return unavailable
                parser = ListingMarkup()
                parser.feed(data.decode(response.encoding or "utf-8", errors="replace"))
    except (httpx.HTTPError, ValueError, LookupError):
        return unavailable
    if len(parser.products) != 1:
        return unavailable
    product = parser.products[0]
    lines = [f"{label}：{product[key].strip()[:3000]}" for key, label in (
        ("name", "商品名称"), ("description", "商品说明"), ("material", "材质"),
        ("model", "型号"), ("color", "颜色"), ("size", "尺寸"),
    ) if isinstance(product.get(key), str) and product[key].strip()]
    if len(lines) < 2:
        return unavailable
    return {"status": "preview", "url": url, "text": "\n".join(lines)[:6000]}
