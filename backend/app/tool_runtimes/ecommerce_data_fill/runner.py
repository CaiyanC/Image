import importlib.util
import sys
from pathlib import Path


SUPPORTED_MODES = ("ecommerce", "kepule", "amazon")
_CORE_ROOT = Path(__file__).resolve().parent / "core"


class ToolRuntimeError(RuntimeError):
    pass


def validate_parameters(mode: str, parameters: dict) -> dict[str, str]:
    if mode not in SUPPORTED_MODES or not isinstance(parameters, dict):
        raise ToolRuntimeError("不支持的填表模式或参数格式")
    allowed = set() if mode == "amazon" else {
        "cycle_type", "cycle_code", "start_date", "end_date", "inventory_date",
        "kepule_sales_date", "kepule_inventory_date",
    }
    if set(parameters) - allowed:
        raise ToolRuntimeError("当前填表模式不支持参数：" + ", ".join(sorted(set(parameters) - allowed)))
    result = {}
    for key, value in parameters.items():
        if value is None:
            continue
        if not isinstance(value, str):
            raise ToolRuntimeError(f"{key}必须为文本")
        if value.strip():
            result[key] = value.strip()
    if mode != "amazon":
        if result.get("cycle_type", "周").lower() not in {"周", "月", "weekly", "week", "monthly", "month"}:
            raise ToolRuntimeError("周期类型必须为周或月")
        try:
            _, config = _load_core_app()._workflow_config(".", ".", result)
        except (ValueError, TypeError) as exc:
            raise ToolRuntimeError(str(exc)) from exc
        if config.start_date > config.end_date:
            raise ToolRuntimeError("开始日期不能晚于结束日期")
    return result


def _load_core_app():
    module_name = "app.tool_runtimes.ecommerce_data_fill._core_app"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    sys.path.insert(0, str(_CORE_ROOT))
    try:
        spec = importlib.util.spec_from_file_location(module_name, _CORE_ROOT / "app.py")
        if spec is None or spec.loader is None:
            raise ToolRuntimeError("Unable to load spreadsheet runtime")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if sys.path and sys.path[0] == str(_CORE_ROOT):
            sys.path.pop(0)


def run_ecommerce_data_fill(mode: str, input_dir: Path, output_dir: Path, parameters: dict[str, str | None], *, input_files: list[dict] | None = None) -> list[Path]:
    parameters = validate_parameters(mode, parameters)
    core_app = _load_core_app()
    runners = {
        "ecommerce": core_app.run_ecommerce_fill,
        "kepule": core_app.run_kepule_fill,
        "amazon": core_app.run_amazon_inventory_fill,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        if input_files is None:
            runners[mode](str(input_dir), str(output_dir), **parameters)
        else:
            detections = resolve_input_bindings(input_dir, input_files)
            runners[mode](str(input_dir), str(output_dir), _detections=detections, **parameters)
    except (ValueError, KeyError, OSError) as exc:
        raise ToolRuntimeError(str(exc)) from exc
    return [
        path
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.suffix.lower() in {".xlsx", ".txt"}
    ]


def recognize_ecommerce_input_files(input_dir: Path) -> set[str]:
    """Use the copied desktop runtime's role detector before a run is queued."""
    if not input_dir.exists():
        return set()
    core_app = _load_core_app()
    try:
        detections = core_app._detect_files(sorted(path for path in input_dir.iterdir() if path.is_file()))
    except (OSError, ValueError, KeyError) as exc:
        raise ToolRuntimeError(str(exc)) from exc
    return set(detections)


def resolve_input_bindings(input_dir: Path, input_files: list[dict]) -> dict:
    """Use the same validated file choices for precheck and execution.

    Automatic duplicates follow the desktop scanner's sorted first match.
    An explicit replacement wins only if its workbook really matches the role.
    """
    core = _load_core_app()
    root = input_dir.resolve()
    paths = []
    for item in input_files:
        name = str(item.get("storage_name") or Path(str(item.get("relative_path") or "")).name)
        path = (root / name).resolve()
        if path.parent != root or not path.is_file() or path.suffix.lower() != ".xlsx":
            raise ToolRuntimeError("输入文件不存在或路径无效，请重新上传")
        paths.append(path)
    detections = core._detect_files(sorted(paths))
    for item, path in zip(input_files, paths):
        role = item.get("manual_role")
        if not role:
            continue
        found = core._detect_files([path])
        if role not in found:
            raise ToolRuntimeError(f"文件“{item.get('display_name', path.name)}”与指定文件槽不匹配，请重新选择")
        detections[role] = found[role]
    return detections
