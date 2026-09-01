import base64
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models.product import Product
from app.models.product_asset import ProductAsset
from app.services.product_asset_mcp_service import ProductAssetMcpService

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import product_asset_mcp_server as mcp_server


class ProductAssetMcpServerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.previous_upload_dir = settings.UPLOAD_DIR
        settings.UPLOAD_DIR = self.temp_dir.name
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[Product.__table__, ProductAsset.__table__])
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(Product(
            id="mcp-product",
            sku="MCP-1",
            barcode="mcp-barcode",
            product_name_cn="MCP测试商品",
            product_name_en="MCP Test Product",
            brand="alocs",
        ))
        self.db.commit()
        self.asset_dir = Path(self.temp_dir.name) / "assets" / "MCP-1"
        self.asset_dir.mkdir(parents=True)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        settings.UPLOAD_DIR = self.previous_upload_dir
        self.temp_dir.cleanup()

    def _add_asset(self, *, asset_id: str, file_name: str, review_status: str = "approved", quality_status: str = "usable", duplicate_status: str = "unique", seq: int = 1):
        data = io.BytesIO()
        Image.new("RGB", (12, 8), color=(20, 80, 140)).save(data, format="PNG")
        (self.asset_dir / file_name).write_bytes(data.getvalue())
        asset = ProductAsset(
            id=asset_id,
            sku="MCP-1",
            category_code="04",
            category_name="场景内容图",
            asset_type="image",
            url=f"/uploads/assets/MCP-1/{file_name}",
            mime_type="image/png",
            file_format="png",
            file_size_bytes=len(data.getvalue()),
            width=12,
            height=8,
            review_status=review_status,
            quality_status=quality_status,
            duplicate_status=duplicate_status,
            authorization_status="internal_test",
            is_public=True,
            ai_reference_usable=True,
            seq=seq,
            tags=json.dumps({"expression_tags": ["场景图"], "scene_tags": ["森林"]}, ensure_ascii=False),
        )
        self.db.add(asset)
        self.db.commit()
        return asset

    def test_initialize_and_tool_catalog_are_standard_json_rpc(self):
        service = ProductAssetMcpService(self.db, upload_dir=self.temp_dir.name)
        initialized = mcp_server.dispatch_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}
        }, service)
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "caiyan-product-assets")
        tools = mcp_server.dispatch_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, service)
        self.assertEqual({tool["name"] for tool in tools["result"]["tools"]}, {"list_product_assets", "read_product_asset"})
        self.assertIsNone(mcp_server.dispatch_request({"jsonrpc": "2.0", "method": "notifications/initialized"}, service))

    def test_list_and_read_return_only_approved_usable_assets_and_image_content(self):
        approved = self._add_asset(asset_id="approved", file_name="approved.png")
        self._add_asset(asset_id="pending", file_name="pending.png", review_status="pending")
        self._add_asset(asset_id="invalid", file_name="invalid.png", quality_status="invalid")
        self._add_asset(asset_id="duplicate", file_name="duplicate.png", duplicate_status="suspected_duplicate")
        service = ProductAssetMcpService(self.db, upload_dir=self.temp_dir.name)

        listed = mcp_server.dispatch_request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_product_assets", "arguments": {"sku": "MCP-1", "scene_tags": ["森林"]}},
        }, service)
        items = listed["result"]["structuredContent"]["items"]
        self.assertEqual([item["id"] for item in items], [approved.id])
        self.assertTrue(items[0]["resource_uri"].startswith("caiyan://product-assets/MCP-1/"))

        read = mcp_server.dispatch_request({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "read_product_asset", "arguments": {"sku": "MCP-1", "asset_id": approved.id}},
        }, service)
        image_block = next(block for block in read["result"]["content"] if block["type"] == "image")
        self.assertEqual(image_block["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(image_block["data"])[:8], b"\x89PNG\r\n\x1a\n")

    def test_publication_requires_authorization_public_and_ai_reference_flags(self):
        for field, value in (
            ("authorization_status", "unknown"),
            ("is_public", False),
            ("ai_reference_usable", False),
        ):
            asset = self._add_asset(asset_id=f"blocked-{field}", file_name=f"blocked-{field}.png")
            setattr(asset, field, value)
            self.db.commit()

            service = ProductAssetMcpService(self.db, upload_dir=self.temp_dir.name)
            self.assertEqual(service.list_assets({"sku": "MCP-1", "limit": 50}), [], field)
            blocked = mcp_server.dispatch_request({
                "jsonrpc": "2.0", "id": 40, "method": "tools/call",
                "params": {
                    "name": "read_product_asset",
                    "arguments": {"sku": "MCP-1", "asset_id": asset.id},
                },
            }, service)
            self.assertTrue(blocked["result"]["isError"], field)

            self.db.delete(asset)
            self.db.commit()

    def test_list_applies_publication_filter_before_limit(self):
        for index in range(1, 102):
            self._add_asset(
                asset_id=f"pending-{index}",
                file_name=f"pending-{index}.png",
                review_status="pending",
                seq=index,
            )
        approved = self._add_asset(
            asset_id="approved-after-pending-page",
            file_name="approved-after-pending-page.png",
            seq=102,
        )
        service = ProductAssetMcpService(self.db, upload_dir=self.temp_dir.name)

        listed = service.list_assets({"sku": "MCP-1", "limit": 1})

        self.assertEqual([item["id"] for item in listed], [approved.id])

    def test_resource_read_and_path_escape_are_bounded(self):
        asset = self._add_asset(asset_id="resource", file_name="resource.png")
        service = ProductAssetMcpService(self.db, upload_dir=self.temp_dir.name)
        uri = service.resource_uri("MCP-1", asset.id)
        response = mcp_server.dispatch_request({
            "jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {"uri": uri}
        }, service)
        self.assertEqual(response["result"]["contents"][0]["mimeType"], "image/png")

        escaped = ProductAsset(
            id="escape",
            sku="MCP-1",
            category_code="04",
            category_name="场景内容图",
            asset_type="image",
            url="/uploads/assets/MCP-1/../../outside.png",
            review_status="approved",
            quality_status="usable",
            duplicate_status="unique",
            seq=2,
        )
        self.db.add(escaped)
        self.db.commit()
        blocked = mcp_server.dispatch_request({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "read_product_asset", "arguments": {"sku": "MCP-1", "asset_id": "escape"}},
        }, service)
        self.assertTrue(blocked["result"]["isError"])

    def test_stdio_process_emits_utf8_json_rpc(self):
        root = Path(__file__).resolve().parents[2]
        python_exe = root / "backend" / "venv" / "Scripts" / "python.exe"
        server = root / "backend" / "scripts" / "product_asset_mcp_server.py"
        env_file = root / "backend" / ".env.dev"
        process = subprocess.Popen(
            [str(python_exe), str(server), "--env-file", str(env_file)],
            cwd=str(root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            process.stdin.write((json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }, ensure_ascii=False) + "\n").encode("utf-8"))
            process.stdin.flush()
            line = process.stdout.readline()
            payload = json.loads(line.decode("utf-8"))
            self.assertEqual(payload["result"]["serverInfo"]["name"], "caiyan-product-assets")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
