"""Product scope: keep retired feature data, but do not expose execution."""

BUSINESS_TOOL_KEYS = frozenset({'customer_service', 'product_management', 'asset_library'})
RETIRED_API_PREFIXES = (
    '/api/generation', '/api/history', '/api/loading-rates',
    '/api/tools/ecommerce-data-fill', '/api/admin/tools',
)


def is_retired_api(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + '/') for prefix in RETIRED_API_PREFIXES)
