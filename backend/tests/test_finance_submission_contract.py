import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from fastapi import HTTPException
from app.api import tools
from app.schemas.tool import ToolRunConfirmRequest
from app.tool_runtimes.ecommerce_data_fill import runner


class FinanceSubmissionContractTest(unittest.TestCase):
    def test_amazon_only_accepts_empty_parameters(self):
        self.assertEqual(runner.validate_parameters('amazon', {}), {})
        for parameters in [{'cycle_type': '周'}, {'start_date': ''}, {'mode': 'kepule'}, {'_detections': {}}]:
            with self.subTest(parameters=parameters), self.assertRaises(runner.ToolRuntimeError):
                runner.validate_parameters('amazon', parameters)

    def test_period_workflows_validate_parameters_without_changing_values(self):
        for mode in ['ecommerce', 'kepule']:
            with self.subTest(mode=mode):
                values = {'cycle_type': '周', 'cycle_code': '2026W27', 'start_date': '2026-06-29', 'end_date': '2026-07-05'}
                self.assertEqual(runner.validate_parameters(mode, values), values)
                self.assertEqual(runner.validate_parameters(mode, {'cycle_code': '', 'start_date': None}), {})
                for bad in [{'cycle_type': '季'}, {'start_date': '2026-02-30'}, {'start_date': []}, {'unexpected': 'x'}, {'start_date': '2026-07-10', 'end_date': '2026-07-01'}]:
                    with self.subTest(bad=bad), self.assertRaises(runner.ToolRuntimeError):
                        runner.validate_parameters(mode, bad)

    def test_worker_rejects_bad_parameters_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(runner.ToolRuntimeError):
                runner.run_ecommerce_data_fill('amazon', root, root / 'output', {'cycle_type': '周'})
            self.assertFalse((root / 'output').exists())

    def test_precheck_returns_selected_file_not_just_role(self):
        file = {'storage_name': 'one.xlsx', 'display_name': '原始模板.xlsx', 'relative_path': 'input/one.xlsx'}
        run = SimpleNamespace(parameters={'mode': 'amazon'}, input_files=[file])
        with patch.object(tools.tool_run_service, 'input_directory', return_value=Path('input')), patch.object(tools, 'resolve_input_bindings', return_value={'amazon_inventory_target': SimpleNamespace(path=Path('input/one.xlsx'))}):
            result = tools._precheck_draft(run, {})
        self.assertEqual(result['slots'][0]['file'], {'display_name': '原始模板.xlsx', 'relative_path': 'input/one.xlsx'})
        self.assertFalse(result['can_run'])
        self.assertIsNone(result['slots'][1]['file'])

    def test_confirm_bad_params_does_not_queue_or_modify_draft(self):
        run = SimpleNamespace(status='draft', parameters={'mode': 'amazon'}, input_files=[])
        db = Mock()
        with patch.object(tools, '_ensure_draft_access', return_value=run), patch.object(tools, '_enqueue_tool_run') as enqueue:
            with self.assertRaises(HTTPException) as caught:
                tools.confirm_ecommerce_data_fill_draft('id', ToolRunConfirmRequest(parameters={'cycle_type': '周'}), Mock(), SimpleNamespace(id='user'), db)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(run.status, 'draft')
        self.assertEqual(run.parameters, {'mode': 'amazon'})
        db.commit.assert_not_called()
        enqueue.assert_not_called()

    def test_manual_replacement_is_real_selected_file_and_wrong_role_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['a.xlsx', 'z.xlsx']:
                (root / name).touch()
            files = [{'storage_name': name, 'manual_role': None} for name in ['a.xlsx', 'z.xlsx']]
            def detect(paths):
                return {'amazon_inventory_target': SimpleNamespace(path=paths[0])} if paths else {}
            with patch.object(runner, '_load_core_app', return_value=SimpleNamespace(_detect_files=detect)):
                self.assertEqual(runner.resolve_input_bindings(root, files)['amazon_inventory_target'].path.name, 'a.xlsx')
                files[1]['manual_role'] = 'amazon_inventory_target'
                self.assertEqual(runner.resolve_input_bindings(root, files)['amazon_inventory_target'].path.name, 'z.xlsx')
                files[1]['manual_role'] = 'fba_inventory'
                with self.assertRaises(runner.ToolRuntimeError):
                    runner.resolve_input_bindings(root, files)
                with self.assertRaises(runner.ToolRuntimeError):
                    runner.resolve_input_bindings(root, [{'storage_name': '../outside.xlsx'}])

    def test_worker_passes_same_resolver_result_to_core(self):
        with tempfile.TemporaryDirectory() as directory:
            core = SimpleNamespace(run_amazon_inventory_fill=Mock(), run_ecommerce_fill=Mock(), run_kepule_fill=Mock())
            bindings = {'amazon_inventory_target': object()}
            with patch.object(runner, '_load_core_app', return_value=core), patch.object(runner, 'resolve_input_bindings', return_value=bindings):
                runner.run_ecommerce_data_fill('amazon', Path(directory), Path(directory) / 'output', {}, input_files=[])
            self.assertIs(core.run_amazon_inventory_fill.call_args.kwargs['_detections'], bindings)


if __name__ == '__main__':
    unittest.main()
