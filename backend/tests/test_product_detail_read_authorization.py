"""Real permission dependencies over isolated SQLite; no company accounts changed."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import products
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models import User, Group, UserGroup, Permission, GroupPermission


class ProductDetailReadAuthorizationTest(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.enterContext = stack.enter_context
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine, tables=[m.__table__ for m in (User, Group, UserGroup, Permission, GroupPermission)])
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(id='employee', username='employee', password_hash='unused', is_active=True)
        self.db.add_all([self.user, Group(id='department', group_name='Test department'),
                         UserGroup(user_id='employee', group_id='department', group_role='member')])
        self.db.commit()
        self.app = FastAPI()
        self.app.include_router(products.router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(self.app)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.addCleanup(self.client.close)
        # Shared full-detail cache must never be read before the access gate.
        self.detail = {'sku': 'A', 'business': {'internal': 'private'}, 'specs': {'capacity': '1L'}}
        self.detail_mock = self.enterContext(patch.object(products.product_service, 'get_product_detail', return_value=self.detail))
        self.enterContext(patch.object(products.product_service, 'get_products', return_value=([{'sku': 'A'}], 1)))
        self.enterContext(patch.object(products.product_service, 'advanced_search_products', return_value=([self.detail], 1)))
        self.enterContext(patch.object(products.product_service, 'get_product_filter_options', return_value={'capacity': ['1L']}))

    def grants(self, *keys):
        self.db.query(GroupPermission).delete()
        for key in keys:
            row = self.db.query(Permission).filter_by(permission_key=key).first()
            if not row:
                row = Permission(permission_key=key, permission_name=key)
                self.db.add(row)
                self.db.flush()
            self.db.add(GroupPermission(group_id='department', permission_id=row.id))
        self.db.commit()

    def test_permission_matrix(self):
        for keys, detail_status, full_status in [
            ((), 403, 403), (('product.read',), 403, 403),
            (('product.create',), 403, 403), (('product.qa.manage',), 403, 403),
            (('product.audit.view',), 403, 403), (('media.read',), 403, 403),
            (('product.full.view',), 200, 200), (('product.edit',), 200, 403),
            (('product.read', 'product.full.view'), 200, 200),
        ]:
            self.grants(*keys)
            for path, expected in [('/api/products/A', detail_status),
                                   ('/api/products/by-sku/A', detail_status),
                                   ('/api/products/A/full-view', full_status),
                                   ('/api/products/filter-options', detail_status)]:
                with self.subTest(keys=keys, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, expected, response.text)
                    if expected == 403:
                        self.assertNotIn('private', response.text)
            with self.subTest(keys=keys, path='advanced-search'):
                self.assertEqual(self.client.post('/api/products/advanced-search', json={}).status_code, detail_status)

    def test_read_only_catalogue_and_search_remain_available(self):
        self.grants('product.read')
        for path in ['/api/products', '/api/products/search?q=A']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['items'], [{'sku': 'A'}])
        self.detail_mock.assert_not_called()

    def test_revocation_denies_even_after_full_detail_was_cached(self):
        self.grants('product.read', 'product.full.view')
        self.assertEqual(self.client.get('/api/products/A').status_code, 200)
        self.detail_mock.reset_mock()
        self.grants('product.read')
        for path in ['/api/products/A', '/api/products/by-sku/A', '/api/products/A/full-view']:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.detail_mock.assert_not_called()
        self.assertEqual(self.detail['business']['internal'], 'private')

    def test_anonymous_denied(self):
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.get('/api/products/A').status_code, 401)

    def test_management_keeps_full_access_without_explicit_grants(self):
        self.db.get(Group, 'department').group_name = 'IT部'
        self.db.query(UserGroup).one().group_role = 'admin'
        self.db.commit()
        self.assertEqual(self.client.get('/api/products/A').status_code, 200)
        self.assertEqual(self.client.get('/api/products/A/full-view').status_code, 200)


if __name__ == '__main__':
    unittest.main()
