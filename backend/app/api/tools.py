import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.permission_constants import ECOMMERCE_DATA_FILL_PERMISSION
from ..core.security import get_current_user, get_user_permissions, is_management_user, require_permission
from ..models.tool import Tool
from ..models.tool_run import ToolRun
from ..models.user import User
from ..schemas.tool import ToolResponse, ToolRunConfirmRequest, ToolRunResponse
from ..services import ecommerce_precheck_service, operation_log_service, tool_registry_service, tool_run_service
from ..tasks.tool_runs import run_ecommerce_data_fill_tool_run
from ..tool_runtimes.ecommerce_data_fill.runner import ToolRuntimeError, recognize_ecommerce_input_files


router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=list[ToolResponse])
def list_available_tools(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    permissions = get_user_permissions(db, current_user.id)
    return tool_registry_service.list_visible_tools(db, permissions)


def _get_ecommerce_tool(db: Session) -> Tool:
    tool = db.query(Tool).filter_by(tool_key="ecommerce_data_fill", is_enabled=True).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool is disabled")
    return tool


def _ensure_draft_access(db: Session, run_id: str, user_id: str) -> ToolRun:
    run = tool_run_service.get_run(db, run_id)
    tool_run_service.ensure_run_access(run, user_id=user_id, is_management=is_management_user(db, user_id))
    if run.tool_key != "ecommerce_data_fill" or run.status != "draft":
        raise HTTPException(status_code=400, detail="Tool draft is not available")
    return run


def _precheck_draft(run: ToolRun) -> dict:
    mode = str((run.parameters or {}).get("mode", ""))
    try:
        roles = recognize_ecommerce_input_files(tool_run_service.input_directory(run))
    except ToolRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    roles.update(
        str(item.get("manual_role"))
        for item in (run.input_files or [])
        if item.get("manual_role") in ecommerce_precheck_service.WORKFLOW_ROLE_ORDER[mode]
    )
    result = ecommerce_precheck_service.build_precheck(mode, roles)
    result["recognized_roles"] = sorted(roles)
    return result


@router.post("/ecommerce-data-fill/drafts", response_model=ToolRunResponse)
def create_ecommerce_data_fill_draft(
    mode: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    current_user: User = Depends(require_permission(ECOMMERCE_DATA_FILL_PERMISSION)),
    db: Session = Depends(get_db),
):
    if mode not in {"ecommerce", "kepule", "amazon"}:
        raise HTTPException(status_code=400, detail="Unsupported spreadsheet workflow")
    if len(files) > tool_run_service.MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail="Invalid number of Excel files")
    tool = _get_ecommerce_tool(db)
    draft = tool_run_service.create_run(db, tool_key=tool.tool_key, created_by=current_user.id, parameters={"mode": mode}, status="draft")
    draft.input_files = [tool_run_service.save_input_file(draft, filename=file.filename, source=file.file) for file in files]
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/ecommerce-data-fill/drafts/{draft_id}/files", response_model=ToolRunResponse)
def add_ecommerce_data_fill_draft_files(
    draft_id: str,
    files: list[UploadFile] = File(...),
    role: str | None = Form(None),
    current_user: User = Depends(require_permission(ECOMMERCE_DATA_FILL_PERMISSION)),
    db: Session = Depends(get_db),
):
    draft = _ensure_draft_access(db, draft_id, current_user.id)
    if not files or len(draft.input_files or []) + len(files) > tool_run_service.MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail="Invalid number of Excel files")
    mode = str((draft.parameters or {}).get("mode", ""))
    if role and role not in ecommerce_precheck_service.WORKFLOW_ROLE_ORDER.get(mode, ()):
        raise HTTPException(status_code=400, detail="Invalid spreadsheet file role")
    additions = [tool_run_service.save_input_file(draft, filename=file.filename, source=file.file) for file in files]
    for item in additions:
        if role:
            item["manual_role"] = role
    draft.input_files = [*list(draft.input_files or []), *additions]
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/ecommerce-data-fill/drafts/{draft_id}/precheck")
def precheck_ecommerce_data_fill_draft(
    draft_id: str,
    current_user: User = Depends(require_permission(ECOMMERCE_DATA_FILL_PERMISSION)),
    db: Session = Depends(get_db),
):
    return _precheck_draft(_ensure_draft_access(db, draft_id, current_user.id))


@router.post("/ecommerce-data-fill/drafts/{draft_id}/confirm", response_model=ToolRunResponse)
def confirm_ecommerce_data_fill_draft(
    draft_id: str,
    payload: ToolRunConfirmRequest,
    request: Request,
    current_user: User = Depends(require_permission(ECOMMERCE_DATA_FILL_PERMISSION)),
    db: Session = Depends(get_db),
):
    draft = _ensure_draft_access(db, draft_id, current_user.id)
    precheck = _precheck_draft(draft)
    if not precheck["can_run"]:
        raise HTTPException(status_code=400, detail="Precheck has missing required files")
    draft.parameters = {**payload.parameters, "mode": precheck["mode"]}
    draft.status = "queued"
    db.commit()
    db.refresh(draft)
    operation_log_service.log_operation(
        db, operator_id=current_user.id, action_type="tool_run", action_name="confirm_ecommerce_data_fill",
        target_type="tool_run", target_id=draft.id, target_name="电商数据分析表自动填写",
        request_data={"mode": precheck["mode"], "file_count": len(draft.input_files)}, response_data={"status": draft.status}, request=request,
    )
    _enqueue_tool_run(db, draft)
    return draft


@router.post("/ecommerce-data-fill/runs", response_model=ToolRunResponse)
def create_ecommerce_data_fill_run(
    request: Request,
    mode: str = Form(...),
    parameters_json: str = Form("{}"),
    files: list[UploadFile] = File(...),
    current_user: User = Depends(require_permission(ECOMMERCE_DATA_FILL_PERMISSION)),
    db: Session = Depends(get_db),
):
    if mode not in {"ecommerce", "kepule", "amazon"}:
        raise HTTPException(status_code=400, detail="Unsupported spreadsheet workflow")
    if not files or len(files) > tool_run_service.MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail="Invalid number of Excel files")
    try:
        parameters = json.loads(parameters_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid tool parameters") from exc
    if not isinstance(parameters, dict):
        raise HTTPException(status_code=400, detail="Invalid tool parameters")
    tool = _get_ecommerce_tool(db)
    run = tool_run_service.create_run(
        db,
        tool_key=tool.tool_key,
        created_by=current_user.id,
        parameters={**parameters, "mode": mode},
    )
    try:
        run.input_files = [
            tool_run_service.save_input_file(run, filename=file.filename, source=file.file)
            for file in files
        ]
        db.commit()
        db.refresh(run)
    except Exception:
        db.rollback()
        raise
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="tool_run",
        action_name="submit_ecommerce_data_fill",
        target_type="tool_run",
        target_id=run.id,
        target_name=tool.name,
        request_data={"mode": mode, "file_count": len(run.input_files)},
        response_data={"status": run.status},
        request=request,
    )
    _enqueue_tool_run(db, run)
    return run


def _enqueue_tool_run(db: Session, run: ToolRun) -> None:
    try:
        run_ecommerce_data_fill_tool_run.apply_async(args=[run.id], task_id=run.id)
    except Exception as exc:
        db.rollback()
        persisted = db.get(ToolRun, run.id)
        if persisted and persisted.status in {"queued", "running"}:
            tool_run_service.mark_failed(db, persisted, "Task queue unavailable")
        raise HTTPException(status_code=503, detail="任务队列暂不可用，运行记录已标记失败") from exc


@router.get("/ecommerce-data-fill/runs", response_model=list[ToolRunResponse])
def list_ecommerce_data_fill_runs(
    current_user: User = Depends(require_permission(ECOMMERCE_DATA_FILL_PERMISSION)),
    db: Session = Depends(get_db),
):
    query = db.query(ToolRun).filter_by(tool_key="ecommerce_data_fill")
    if not is_management_user(db, current_user.id):
        query = query.filter_by(created_by=current_user.id)
    return query.order_by(ToolRun.created_at.desc()).all()


@router.get("/ecommerce-data-fill/runs/{run_id}", response_model=ToolRunResponse)
def get_ecommerce_data_fill_run(
    run_id: str,
    current_user: User = Depends(require_permission(ECOMMERCE_DATA_FILL_PERMISSION)),
    db: Session = Depends(get_db),
):
    run = tool_run_service.get_run(db, run_id)
    return tool_run_service.ensure_run_access(run, user_id=current_user.id, is_management=is_management_user(db, current_user.id))


@router.get("/ecommerce-data-fill/runs/{run_id}/files/{file_index}")
def download_ecommerce_data_fill_file(
    run_id: str,
    file_index: int,
    current_user: User = Depends(require_permission(ECOMMERCE_DATA_FILL_PERMISSION)),
    db: Session = Depends(get_db),
):
    run = tool_run_service.get_run(db, run_id)
    tool_run_service.ensure_run_access(run, user_id=current_user.id, is_management=is_management_user(db, current_user.id))
    if file_index < 0 or file_index >= len(run.output_files or []):
        raise HTTPException(status_code=404, detail="Run file not found")
    item = run.output_files[file_index]
    path = tool_run_service.resolve_run_file(run, str(item.get("relative_path") or ""))
    return FileResponse(path, filename=str(item.get("display_name") or path.name))
