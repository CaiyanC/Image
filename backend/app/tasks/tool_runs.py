from pathlib import Path

from ..core.celery_app import celery_app
from ..core.database import SessionLocal
from ..models.tool_run import ToolRun
from ..services import tool_run_service
from ..tool_runtimes.ecommerce_data_fill.runner import ToolRuntimeError, run_ecommerce_data_fill


@celery_app.task(name="run_ecommerce_data_fill_tool_run")
def run_ecommerce_data_fill_tool_run(run_id: str) -> dict:
    db = SessionLocal()
    try:
        run = tool_run_service.get_run(db, run_id)
        tool_run_service.mark_running(db, run)
        root = tool_run_service.run_directory(run.id)
        parameters = dict(run.parameters or {})
        mode = str(parameters.pop("mode", ""))
        outputs = run_ecommerce_data_fill(mode, root / "input", root / "output", parameters)
        output_files = [
            {
                "display_name": path.name,
                "relative_path": str(path.relative_to(root)).replace("\\", "/"),
                "size": path.stat().st_size,
            }
            for path in outputs
        ]
        tool_run_service.mark_succeeded(db, run, output_files)
        return {"ok": True, "run_id": run.id, "output_files": output_files}
    except (ToolRuntimeError, ValueError) as exc:
        db.rollback()
        run = db.get(ToolRun, run_id)
        if run:
            tool_run_service.mark_failed(db, run, str(exc))
        return {"ok": False, "run_id": run_id, "error": str(exc)}
    except Exception:
        db.rollback()
        run = db.get(ToolRun, run_id)
        if run:
            tool_run_service.mark_failed(db, run, "Excel processing failed")
        return {"ok": False, "run_id": run_id, "error": "Excel processing failed"}
    finally:
        db.close()
