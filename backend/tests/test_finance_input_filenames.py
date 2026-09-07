import io
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.services import tool_run_service


class FinanceInputFilenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = patch.object(tool_run_service.settings, 'UPLOAD_DIR', str(self.root))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.run = SimpleNamespace(id=str(uuid.uuid4()))

    def save(self, name, payload=b'storage test only'):
        item = tool_run_service.save_input_file(self.run, filename=name, source=io.BytesIO(payload))
        target = tool_run_service.resolve_run_file(self.run, item['relative_path'])
        self.assertTrue(target.is_relative_to(tool_run_service.run_directory(self.run.id) / 'input'))
        self.assertEqual(target.read_bytes(), payload)
        self.assertRegex(item['storage_name'], r'^[0-9a-f]{32}_')
        return item

    def test_business_tokens_retained(self):
        for name in ['4个平台30天销售主题分析.xlsx', '亚马逊库存每周更新20260721.xlsx', '亚马逊2026年最新库存明细表_待填写.xlsx']:
            with self.subTest(name=name):
                item = self.save(name)
                self.assertTrue(item['storage_name'].endswith(name))

    def test_both_path_separators_and_unc_are_removed(self):
        for name in [r'C:\fakepath\30天销售.xlsx', r'..\..\30天销售.xlsx', '../../30天销售.xlsx', r'\\server\share\30天销售.xlsx', 'mixed\\dir/30天销售.xlsx']:
            with self.subTest(name=name):
                self.assertEqual(self.save(name)['display_name'], '30天销售.xlsx')

    def test_invalid_windows_characters_and_length(self):
        item = self.save('30天' + '长' * 250 + ':?<bad>|\x00.xlsx')
        self.assertLessEqual(len(item['display_name']), tool_run_service.MAX_INPUT_BASENAME_LENGTH)
        self.assertIsNone(re.search(r'[\x00-\x1f<>:"/\\|?*]', item['storage_name']))
        self.assertIn('30天', item['storage_name'])
        self.save('CON.xlsx')  # UUID prefix avoids Windows reserved basenames.

    def test_duplicate_names_are_isolated(self):
        first = self.save('30天销售.xlsx', b'first')
        second = self.save('30天销售.xlsx', b'second')
        self.assertNotEqual(first['relative_path'], second['relative_path'])
        self.assertEqual(tool_run_service.resolve_run_file(self.run, first['relative_path']).read_bytes(), b'first')

    def test_unsupported_extension_is_rejected(self):
        for name in ['../bad.exe', 'file.xlsx.exe', 'xlsx', '..\\']:
            with self.subTest(name=name), self.assertRaises(HTTPException) as caught:
                self.save(name)
            self.assertEqual(caught.exception.status_code, 400)

    def test_case_and_trailing_whitespace(self):
        self.assertEqual(self.save('30天销售.XLSX ')['display_name'], '30天销售.xlsx')


if __name__ == '__main__':
    unittest.main()
