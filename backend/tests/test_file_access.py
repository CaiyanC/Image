import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import files as files_api
from app.api import knowledge_base as kb_api
from app.core.config import settings
from app.core.database import Base
from app.core.permission_constants import MANAGEMENT_GROUP_NAME
from app.core.rate_limit import reset_rate_limits, set_rate_limit_redis_client
from app.models.generation import Generation
from app.models.group import Group
from app.models.knowledge_base import KnowledgeDocument
from app.models.permissions import GroupPermission, Permission
from app.models.product import Product
from app.models.user import User
from app.models.user_group import UserGroup
from tests.rate_limit_fakes import FakeRedis


class FileAccessTest(unittest.TestCase):
    def setUp(self):
        set_rate_limit_redis_client(FakeRedis())
        reset_rate_limits()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.upload_dir = self.temp_path / "uploads"
        self.image_dir = self.upload_dir / "images"
        self.generated_dir = self.upload_dir / "generated"
        self.knowledge_dir = self.upload_dir / "knowledge-files"
        for path in (self.image_dir, self.generated_dir, self.knowledge_dir):
            path.mkdir(parents=True, exist_ok=True)
        (self.image_dir / "sample.png").write_bytes(b"image")
        (self.generated_dir / "gen_sample.png").write_bytes(b"generated")
        self.knowledge_file = self.knowledge_dir / "doc.txt"
        self.knowledge_file.write_text("knowledge", encoding="utf-8")

        self.original_upload_dir = settings.UPLOAD_DIR
        settings.UPLOAD_DIR = str(self.upload_dir)

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                Group.__table__,
                UserGroup.__table__,
                Permission.__table__,
                GroupPermission.__table__,
                Product.__table__,
                Generation.__table__,
                KnowledgeDocument.__table__,
            ],
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.user = self._create_user("user-1", product_read=True)
        self.no_permission_user = self._create_user("user-2", product_read=False)
        self.manager = self._create_user("manager", management=True)
        self.db.add(
            Generation(
                id="gen-1",
                user_id=self.user.id,
                type="txt2img",
                prompt="p",
                model_name="m",
                status="completed",
                result_image_path="/uploads/generated/gen_sample.png",
            )
        )
        self.db.add(
            KnowledgeDocument(
                id="doc-1",
                source_type="file",
                source_id="hash-1",
                title="doc",
                content="",
                file_name="doc.txt",
                file_path=str(self.knowledge_file),
                file_type="txt",
                file_hash="hash-1",
                parse_status="done",
            )
        )
        self.db.commit()

    def tearDown(self):
        reset_rate_limits()
        set_rate_limit_redis_client(None)
        settings.UPLOAD_DIR = self.original_upload_dir
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_product_image_sign_requires_product_read_permission(self):
        response = files_api.sign_file(
            files_api.FileSignRequest(path="/uploads/images/sample.png"),
            current_user=self.user,
            db=self.db,
        )
        self.assertTrue(response.url.startswith("/api/files/signed/"))
        self.assertEqual(response.expires_in, files_api.SIGNED_FILE_EXPIRE_SECONDS)

        with self.assertRaises(HTTPException) as ctx:
            files_api.sign_file(
                files_api.FileSignRequest(path="/uploads/images/sample.png"),
                current_user=self.no_permission_user,
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_knowledge_files_cannot_use_signed_public_path(self):
        with self.assertRaises(HTTPException) as ctx:
            files_api.sign_file(
                files_api.FileSignRequest(path="/uploads/knowledge-files/doc.txt"),
                current_user=self.manager,
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_generated_file_requires_owner_or_management(self):
        owner_response = files_api.sign_file(
            files_api.FileSignRequest(path="/uploads/generated/gen_sample.png"),
            current_user=self.user,
            db=self.db,
        )
        self.assertTrue(owner_response.url.startswith("/api/files/signed/"))

        manager_response = files_api.sign_file(
            files_api.FileSignRequest(path="/uploads/generated/gen_sample.png"),
            current_user=self.manager,
            db=self.db,
        )
        self.assertTrue(manager_response.url.startswith("/api/files/signed/"))

        with self.assertRaises(HTTPException) as ctx:
            files_api.sign_file(
                files_api.FileSignRequest(path="/uploads/generated/gen_sample.png"),
                current_user=self.no_permission_user,
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_signed_token_expires_and_rejects_path_traversal(self):
        original_expire = files_api.SIGNED_FILE_EXPIRE_SECONDS
        try:
            files_api.SIGNED_FILE_EXPIRE_SECONDS = -1
            token = files_api._create_file_token("/uploads/images/sample.png")
            with self.assertRaises(HTTPException) as ctx:
                files_api._decode_file_token(token)
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            files_api.SIGNED_FILE_EXPIRE_SECONDS = original_expire

        with self.assertRaises(HTTPException) as ctx:
            files_api._normalize_upload_url("/uploads/images/../knowledge-files/doc.txt")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_knowledge_file_download_requires_safe_file_path(self):
        response = kb_api.download_knowledge_file("doc-1", current_user=self.manager, db=self.db)
        self.assertEqual(Path(response.path), self.knowledge_file)

        with self.assertRaises(HTTPException) as ctx:
            kb_api.download_knowledge_file("doc-1", current_user=self.no_permission_user, db=self.db)
        self.assertEqual(ctx.exception.status_code, 403)

        bad_doc = KnowledgeDocument(
            id="doc-bad",
            source_type="file",
            source_id="hash-bad",
            title="bad",
            content="",
            file_name="bad.txt",
            file_path=str(self.temp_path / "outside.txt"),
            file_type="txt",
            file_hash="hash-bad",
            parse_status="done",
        )
        self.db.add(bad_doc)
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            kb_api.download_knowledge_file("doc-bad", current_user=self.manager, db=self.db)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_file_sign_rate_limit_returns_429(self):
        for _ in range(files_api.FILE_SIGN_LIMIT_PER_MINUTE):
            files_api.sign_file(
                files_api.FileSignRequest(path="/uploads/images/sample.png"),
                current_user=self.user,
                db=self.db,
            )

        with self.assertRaises(HTTPException) as ctx:
            files_api.sign_file(
                files_api.FileSignRequest(path="/uploads/images/sample.png"),
                current_user=self.user,
                db=self.db,
            )

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "请求过于频繁，请稍后再试")

    def _create_user(self, user_id: str, *, product_read: bool = False, management: bool = False):
        user = User(id=user_id, username=user_id, password_hash="hash", is_active=True)
        group = Group(id=f"group-{user_id}", group_name=MANAGEMENT_GROUP_NAME if management else f"group-{user_id}")
        self.db.add(user)
        self.db.add(group)
        self.db.flush()
        self.db.add(UserGroup(user_id=user.id, group_id=group.id, group_role="admin" if management else "member"))
        if product_read:
            permission = self.db.query(Permission).filter(Permission.permission_key == "product.read").first()
            if not permission:
                permission = Permission(permission_key="product.read", permission_name="Product read", permission_type="api")
                self.db.add(permission)
                self.db.flush()
            self.db.add(GroupPermission(group_id=group.id, permission_id=permission.id))
        self.db.commit()
        return user


if __name__ == "__main__":
    unittest.main()
