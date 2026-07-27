import importlib.util
import sys
from pathlib import Path


SUPPORTED_MODES = ("ecommerce", "kepule", "amazon")
_CORE_ROOT = Path(__file__).resolve().parent / "core"


class ToolRuntimeError(RuntimeError):
    pass


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


def run_ecommerce_data_fill(mode: str, input_dir: Path, output_dir: Path, parameters: dict[str, str | None]) -> list[Path]:
    if mode not in SUPPORTED_MODES:
        raise ToolRuntimeError("不支持的填表模式")
    core_app = _load_core_app()
    runners = {
        "ecommerce": core_app.run_ecommerce_fill,
        "kepule": core_app.run_kepule_fill,
        "amazon": core_app.run_amazon_inventory_fill,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        runners[mode](str(input_dir), str(output_dir), **parameters)
    except (ValueError, KeyError, OSError) as exc:
        raise ToolRuntimeError(str(exc)) from exc
    return [
        path
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.suffix.lower() in {".xlsx", ".txt"}
    ]
