from __future__ import annotations

import json
import logging
import mimetypes
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from urllib.parse import quote

import mistune
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from .audit import add_audit
from .config import settings
from .db import Base, SessionLocal, engine, ensure_schema_compatibility, get_db
from .project_types import PROJECT_TYPE_LABELS, RESOURCE_CATEGORY_LABELS, SUPPORTED_PLATFORMS
from .models import AuditLog, Project, ProjectResource, Release, ReleaseFile, ShareLink, User
from .security import hash_password, verify_password
from .services.managed_resources import is_managed_path_from_roots, is_managed_project_path, is_protected_storage_path, is_trash_path, managed_project_roots
from .services.project_lifecycle import ProjectLifecycleError, delete_project_with_compensation, get_deleted_project, restore_project_with_compensation
from .services.project_resource_service import DuplicateProjectResourceError, ProjectResourceError, ProjectResourceService, normalize_resource_category
from .services.project_service import ensure_release, get_active_project, normalize_platforms, normalize_project_type, normalize_source_url, normalize_website_url, project_release_path, project_storage_path, refresh_latest_flags, refresh_primary_file, unique_slug
from .services.file_tree import move_destination
from .services.smart_upload import analyze_filename, hash_and_spool
from .services.storage import StorageError, get_storage, normalize_repo_path
from .services.trash_service import move_to_trash, restore_from_trash

logger = logging.getLogger(__name__)
app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
markdown = mistune.create_markdown(escape=True)


def template_context(request: Request, **kwargs):
    user = None
    if request.session.get("user_id"):
        with SessionLocal() as db:
            user = db.get(User, request.session["user_id"])
    return {
        "request": request,
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "storage_label": settings.storage_label,
        "show_env_badge": settings.show_env_badge,
        "current_user": user,
        "project_type_labels": PROJECT_TYPE_LABELS,
        "resource_category_labels": RESOURCE_CATEGORY_LABELS,
        "supported_platforms": SUPPORTED_PLATFORMS,
        **kwargs,
    }


def require_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401)
    user = db.get(User, user_id)
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=401)
    return user


def require_admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403)
    return user


def safe_filename(name: str) -> str:
    name = PurePosixPath((name or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="잘못된 파일명입니다.")
    return name


def ensure_dirs(storage, path: str) -> None:
    path = normalize_repo_path(path)
    if not path:
        return
    current = ""
    for part in path.split("/"):
        current = f"{current}/{part}".strip("/")
        if not storage.exists(current):
            try:
                storage.mkdir(current)
            except StorageError:
                if not storage.exists(current):
                    raise


def ensure_unmanaged_storage_path(db: Session, *paths: str) -> None:
    if any(is_protected_storage_path(db, path) for path in paths):
        raise HTTPException(status_code=409, detail="프로젝트에서 관리되는 항목입니다. 프로젝트 관리 화면에서 변경하세요.")


def fmt_size(value: int | None) -> str:
    if value is None:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


templates.env.filters["filesize"] = fmt_size


@app.on_event("startup")
def startup() -> None:
    if settings.database_url.startswith("sqlite"):
        from pathlib import Path
        db_path = settings.database_url.removeprefix("sqlite:///")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    ensure_schema_compatibility()
    storage = get_storage()
    if settings.storage_type.lower() == "local":
        storage.list("")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == settings.admin_username))
        if not user:
            db.add(User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                display_name=settings.admin_display_name,
                is_admin=True,
                is_active=True,
            ))
            db.commit()


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return Response(content=json.dumps({"detail": "로그인이 필요합니다."}, ensure_ascii=False), media_type="application/json", status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.app_env, "storage": settings.storage_type}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/projects", status_code=303)
    return templates.TemplateResponse(request, "login.html", template_context(request))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", template_context(request, error="아이디 또는 비밀번호가 올바르지 않습니다."), status_code=400)
    request.session["user_id"] = user.id
    add_audit(db, user.id, "LOGIN", user.username)
    db.commit()
    return RedirectResponse("/projects", status_code=303)


@app.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if user_id:
        add_audit(db, user_id, "LOGOUT")
        db.commit()
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/")
def root(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/projects", status_code=303)


# ---------------- Files ----------------
@app.get("/files", response_class=HTMLResponse)
def files_page(request: Request, path: str = "", db: Session = Depends(get_db)):
    require_user(request, db)
    storage = get_storage()
    try:
        current_path = normalize_repo_path(path)
        if is_trash_path(current_path):
            raise StorageError("Trash 영역은 프로젝트 관리 화면에서만 접근할 수 있습니다.")
        entries = storage.list(current_path)
        if not current_path:
            entries = [entry for entry in entries if entry.name != "_trash"]
    except StorageError as exc:
        entries = []
        current_path = ""
        error = str(exc)
    else:
        error = None
    managed_roots = managed_project_roots(db)
    managed_paths = {entry.path for entry in entries if is_managed_path_from_roots(entry.path, managed_roots)}
    managed_current = is_managed_path_from_roots(current_path, managed_roots)
    breadcrumbs = []
    accum = ""
    for part in current_path.split("/") if current_path else []:
        accum = f"{accum}/{part}".strip("/")
        breadcrumbs.append((part, accum))
    return templates.TemplateResponse(request, "files.html", template_context(
        request, entries=entries, path=current_path, breadcrumbs=breadcrumbs, error=error, managed_paths=managed_paths, managed_current=managed_current
    ))


@app.post("/files/folder")
def create_folder(request: Request, path: str = Form(""), name: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    storage = get_storage()
    folder = safe_filename(name)
    parent = normalize_repo_path(path)
    target = str(PurePosixPath(parent) / folder)
    ensure_unmanaged_storage_path(db, parent, target)
    try:
        storage.mkdir(target)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    add_audit(db, user.id, "CREATE_FOLDER", target)
    db.commit()
    return RedirectResponse(f"/files?path={quote(normalize_repo_path(path))}", status_code=303)


@app.post("/files/upload")
def upload_files(request: Request, path: str = Form(""), files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    storage = get_storage()
    base = normalize_repo_path(path)
    ensure_unmanaged_storage_path(db, base)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    for item in files:
        filename = safe_filename(item.filename or "")
        target = str(PurePosixPath(base) / filename)
        temp, _, _ = hash_and_spool(item.file, max_bytes)
        try:
            storage.write_stream(target, temp, item.content_type)
        finally:
            temp.close()
        add_audit(db, user.id, "UPLOAD_FILE", target)
    db.commit()
    return RedirectResponse(f"/files?path={quote(base)}", status_code=303)


@app.get("/files/download")
def download_file(request: Request, path: str, db: Session = Depends(get_db)):
    user = require_user(request, db)
    storage = get_storage()
    rel = normalize_repo_path(path)
    try:
        data = storage.read_bytes(rel)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    add_audit(db, user.id, "DOWNLOAD_FILE", rel)
    db.commit()
    filename = PurePosixPath(rel).name
    return Response(
        data,
        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.post("/files/delete")
def delete_file(request: Request, path: str = Form(...), return_path: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    storage = get_storage()
    rel = normalize_repo_path(path)
    ensure_unmanaged_storage_path(db, rel)
    try:
        storage.delete(rel)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    add_audit(db, user.id, "DELETE", rel)
    db.commit()
    return RedirectResponse(f"/files?path={quote(normalize_repo_path(return_path))}", status_code=303)


@app.get("/api/files/tree")
def file_tree_children(request: Request, path: str = "", db: Session = Depends(get_db)):
    require_user(request, db)
    storage = get_storage()
    parent = normalize_repo_path(path)
    if is_trash_path(parent):
        raise HTTPException(status_code=400, detail="Trash 영역은 프로젝트 관리 화면에서만 접근할 수 있습니다.")
    try:
        entries = storage.list(parent)
        if not parent:
            entries = [entry for entry in entries if entry.name != "_trash"]
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    managed_roots = managed_project_roots(db)
    folders = [
        {"name": entry.name, "path": entry.path, "managed": is_managed_path_from_roots(entry.path, managed_roots)}
        for entry in entries
        if entry.is_dir
    ]
    return {"path": parent, "folders": folders}


@app.post("/api/files/move")
async def move_file_api(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    payload = await request.json()
    source = normalize_repo_path(str(payload.get("source", "")))
    destination_dir = normalize_repo_path(str(payload.get("destination_dir", "")))
    destination = move_destination(source, destination_dir)
    ensure_unmanaged_storage_path(db, source, destination_dir, destination)
    if destination == source:
        return {"ok": True, "path": destination, "unchanged": True}
    storage = get_storage()
    try:
        storage.move(source, destination, overwrite=False)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    add_audit(db, user.id, "MOVE", source, f"→ {destination}")
    db.commit()
    return {"ok": True, "path": destination}


@app.post("/files/rename")
def rename_file(request: Request, path: str = Form(...), new_name: str = Form(...), return_path: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    storage = get_storage()
    src = normalize_repo_path(path)
    dst = str(PurePosixPath(src).parent / safe_filename(new_name))
    if dst.startswith("./"):
        dst = dst[2:]
    ensure_unmanaged_storage_path(db, src, dst)
    try:
        storage.move(src, dst, overwrite=False)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    add_audit(db, user.id, "RENAME", src, f"→ {dst}")
    db.commit()
    return RedirectResponse(f"/files?path={quote(normalize_repo_path(return_path))}", status_code=303)


# ---------------- Projects / Smart Upload ----------------
@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    require_user(request, db)
    stmt = select(Project).where(Project.is_deleted.is_(False)).options(selectinload(Project.releases).selectinload(Release.files)).order_by(desc(Project.updated_at))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Project.name.ilike(like), Project.description.ilike(like)))
    projects = list(db.scalars(stmt).unique().all())
    latest_map = {}
    for project in projects:
        latest_map[project.id] = next((r for r in project.releases if r.is_latest), None)
    recent_releases = list(db.scalars(
        select(Release).join(Release.project).where(Project.is_deleted.is_(False)).options(selectinload(Release.project)).order_by(desc(Release.created_at)).limit(6)
    ).all())
    return templates.TemplateResponse(request, "projects.html", template_context(
        request, projects=projects, latest_map=latest_map, recent_releases=recent_releases, q=q
    ))


@app.post("/projects")
def create_project(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    project_type: str = Form(...),
    platforms: list[str] = Form([]),
    website_url: str = Form(""),
    source_url: str = Form(""),
    icon: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="프로젝트명을 입력하세요.")
    if db.scalar(select(Project).where(func.lower(Project.name) == clean_name.lower())):
        raise HTTPException(status_code=409, detail="동일한 프로젝트명이 이미 존재합니다.")
    try:
        clean_project_type = normalize_project_type(project_type)
        clean_platforms = normalize_platforms(platforms)
        clean_website_url = normalize_website_url(website_url, clean_project_type)
        clean_source_url = normalize_source_url(source_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project_slug = unique_slug(db, clean_name)
    project = Project(
        name=clean_name,
        slug=project_slug,
        storage_root=f"프로젝트/{project_slug}",
        description=description.strip() or None,
        project_type=clean_project_type,
        platforms=clean_platforms,
        website_url=clean_website_url,
        source_url=clean_source_url,
        created_by_id=user.id,
    )
    db.add(project)
    db.flush()
    storage = get_storage()
    ensure_dirs(storage, project_storage_path(project))
    if icon and icon.filename:
        icon_name = safe_filename(icon.filename)
        ext = PurePosixPath(icon_name).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            raise HTTPException(status_code=400, detail="프로젝트 아이콘은 PNG/JPG/WEBP/GIF만 지원합니다.")
        icon_target = f"{project_storage_path(project)}/icon{ext}"
        temp, _, _ = hash_and_spool(icon.file, 5 * 1024 * 1024)
        try:
            storage.write_stream(icon_target, temp, icon.content_type or mimetypes.guess_type(icon_name)[0])
        finally:
            temp.close()
        project.icon_path = icon_target
    add_audit(db, user.id, "CREATE_PROJECT", project.name)
    db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@app.get("/projects/{project_id}/icon")
def project_icon(project_id: int, db: Session = Depends(get_db)):
    project = get_active_project(db, project_id)
    if not project or not project.icon_path:
        raise HTTPException(status_code=404)
    try:
        data = get_storage().read_bytes(project.icon_path)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(data, media_type=mimetypes.guess_type(project.icon_path)[0] or "application/octet-stream", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/projects/{project_id}/icon")
def upload_project_icon(request: Request, project_id: int, icon: UploadFile = File(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    project = get_active_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404)
    icon_name = safe_filename(icon.filename or "")
    ext = PurePosixPath(icon_name).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        raise HTTPException(status_code=400, detail="프로젝트 아이콘은 PNG/JPG/WEBP/GIF만 지원합니다.")
    target = f"{project_storage_path(project)}/icon{ext}"
    temp, _, _ = hash_and_spool(icon.file, 5 * 1024 * 1024)
    try:
        get_storage().write_stream(target, temp, icon.content_type or mimetypes.guess_type(icon_name)[0])
    finally:
        temp.close()
    project.icon_path = target
    project.updated_at = datetime.now(timezone.utc)
    add_audit(db, user.id, "UPLOAD_PROJECT_ICON", target)
    db.commit()
    return RedirectResponse(f"/projects/{project.id}?tab=settings&notice=saved", status_code=303)


@app.get("/projects/deleted", response_class=HTMLResponse)
def deleted_projects_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    projects = list(db.scalars(select(Project).where(Project.is_deleted.is_(True)).order_by(Project.deleted_at.desc())).all())
    return templates.TemplateResponse(request, "deleted_projects.html", template_context(request, projects=projects))


@app.post("/projects/{project_id}/restore")
def restore_deleted_project(request: Request, project_id: int, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    project = get_deleted_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404)
    storage = get_storage()
    try:
        restore_project_with_compensation(
            db,
            project,
            user.id,
            storage,
            lambda: add_audit(db, user.id, "PROJECT_RESTORE", project.name, f"slug={project.slug}"),
        )
    except ProjectLifecycleError as exc:
        logger.exception("Project restore failed: %s", project.slug)
        raise HTTPException(status_code=500, detail="프로젝트 복구를 완료하지 못했습니다.") from exc
    except StorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(f"/projects/{project.id}?tab=settings&notice=project-restored", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.is_deleted.is_(False))
        .options(selectinload(Project.releases).selectinload(Release.files))
    )
    if not project:
        raise HTTPException(status_code=404)
    active_tab = request.query_params.get("tab", "overview")
    if active_tab not in {"overview", "releases", "resources", "settings"}:
        active_tab = "overview"
    releases = sorted(project.releases, key=lambda r: r.created_at, reverse=True)
    latest = next((r for r in releases if r.is_latest), None)
    primary_file = next((f for f in latest.files if f.is_primary_download), latest.files[0]) if latest and latest.files else None
    resource_service = ProjectResourceService(db, get_storage())
    resource_counts = resource_service.counts(project.id)
    resource_category = request.query_params.get("category") if active_tab == "resources" else None
    if resource_category:
        try:
            resource_category = normalize_resource_category(resource_category)
        except ProjectResourceError:
            resource_category = None
    resources = resource_service.list(project.id, resource_category)
    readme_html = None
    if project.readme_path:
        try:
            readme_text = get_storage().read_bytes(project.readme_path).decode("utf-8")
            readme_html = markdown(readme_text)
        except Exception:
            readme_html = None
    return templates.TemplateResponse(request, "project_detail.html", template_context(
        request,
        project=project,
        releases=releases,
        latest=latest,
        primary_file=primary_file,
        resource_counts=resource_counts,
        resources=resources,
        resource_category=resource_category,
        readme_html=readme_html,
        active_tab=active_tab,
    ))


@app.post("/projects/{project_id}/resources")
def upload_project_resources(
    request: Request,
    project_id: int,
    files: list[UploadFile] = File(...),
    category: str = Form(...),
    titles: list[str] = Form([]),
    description: str = Form(""),
    overwrite: bool = Form(False),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    project = get_active_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404)
    try:
        category = normalize_resource_category(category)
        filenames = [safe_filename(item.filename or "") for item in files]
        duplicates = ProjectResourceService(db, get_storage()).duplicates(project.id, category, filenames)
    except ProjectResourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if duplicates and not overwrite:
        names = ", ".join(resource.original_filename for resource in duplicates)
        raise HTTPException(status_code=409, detail=f"동일한 이름의 자료가 이미 존재합니다: {names}")

    service = ProjectResourceService(db, get_storage())
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        for index, item in enumerate(files):
            filename = filenames[index]
            temp, size, sha256 = hash_and_spool(item.file, max_bytes)
            try:
                resource = service.save(
                    project=project,
                    user_id=user.id,
                    category=category,
                    filename=filename,
                    title=titles[index] if index < len(titles) else None,
                    description=description,
                    stream=temp,
                    file_size=size,
                    mime_type=item.content_type,
                    sha256=sha256,
                    overwrite=overwrite,
                )
            finally:
                temp.close()
            add_audit(db, user.id, "RESOURCE_REPLACE" if overwrite else "RESOURCE_UPLOAD", resource.storage_path)
        db.commit()
    except DuplicateProjectResourceError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ProjectResourceError, StorageError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/projects/{project.id}?tab=resources&notice=resource-uploaded", status_code=303)


@app.get("/projects/{project_id}/resources/{resource_id}/download")
def download_project_resource(request: Request, project_id: int, resource_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    service = ProjectResourceService(db, get_storage())
    try:
        resource = service.get(project_id, resource_id)
        data = get_storage().read_bytes(resource.storage_path)
    except (ProjectResourceError, StorageError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    add_audit(db, user.id, "RESOURCE_DOWNLOAD", resource.storage_path)
    db.commit()
    return Response(
        data,
        media_type=resource.mime_type or mimetypes.guess_type(resource.original_filename)[0] or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(resource.original_filename)}"},
    )


@app.post("/projects/{project_id}/resources/{resource_id}/delete")
def delete_project_resource(request: Request, project_id: int, resource_id: int, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    service = ProjectResourceService(db, get_storage())
    try:
        resource = service.get(project_id, resource_id)
        service.delete_with_compensation(
            resource,
            user.id,
            lambda original, trash: add_audit(db, user.id, "RESOURCE_DELETE", original, f"trash={trash}"),
        )
    except (ProjectResourceError, StorageError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/projects/{project_id}?tab=resources&notice=resource-deleted", status_code=303)


@app.post("/projects/{project_id}/resources/{resource_id}/restore")
def restore_project_resource(request: Request, project_id: int, resource_id: int, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if not get_active_project(db, project_id):
        raise HTTPException(status_code=404)
    service = ProjectResourceService(db, get_storage())
    original_path = None
    trash_path = None
    try:
        resource = service.get_deleted(project_id, resource_id)
        original_path, trash_path = service.restore(resource)
        add_audit(db, user.id, "RESOURCE_RESTORE", original_path, f"trash={trash_path}")
        db.commit()
    except (ProjectResourceError, StorageError) as exc:
        db.rollback()
        if original_path and trash_path:
            try:
                get_storage().move(original_path, trash_path, overwrite=False)
            except StorageError:
                logger.exception("ProjectResource restore rollback failed: %s", trash_path)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        if original_path and trash_path:
            try:
                get_storage().move(original_path, trash_path, overwrite=False)
            except StorageError:
                logger.exception("ProjectResource restore rollback failed: %s", trash_path)
        raise
    return RedirectResponse(f"/projects/{project_id}?tab=resources&notice=resource-restored", status_code=303)


@app.post("/projects/{project_id}/delete")
def delete_project(request: Request, project_id: int, confirm_name: str = Form(...), db: Session = Depends(get_db)):
    user = require_admin(request, db)
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.is_deleted.is_(False))
        .options(selectinload(Project.releases).selectinload(Release.files))
    )
    if not project:
        raise HTTPException(status_code=404)
    if confirm_name != project.name:
        raise HTTPException(status_code=400, detail="프로젝트명이 일치하지 않습니다.")
    storage = get_storage()
    try:
        delete_project_with_compensation(
            db,
            project,
            user.id,
            storage,
            lambda: add_audit(db, user.id, "PROJECT_DELETE", project.name, f"slug={project.slug}"),
        )
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=f"프로젝트를 Trash로 이동하지 못했습니다: {exc}") from exc
    except ProjectLifecycleError as exc:
        logger.exception("Project delete failed: %s", project.slug)
        raise HTTPException(status_code=500, detail="프로젝트 삭제를 완료하지 못했습니다.") from exc
    return RedirectResponse("/projects?notice=project-deleted", status_code=303)


@app.post("/projects/{project_id}/source")
def update_project_source(request: Request, project_id: int, source_url: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    project = get_active_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404)
    try:
        project.source_url = normalize_source_url(source_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project.updated_at = datetime.now(timezone.utc)
    add_audit(db, user.id, "UPDATE_PROJECT_SOURCE", project.source_url or "")
    db.commit()
    return RedirectResponse(f"/projects/{project.id}?tab=settings&notice=saved", status_code=303)


@app.post("/projects/{project_id}/settings")
def update_project_settings(
    request: Request,
    project_id: int,
    name: str = Form(...),
    description: str = Form(""),
    project_type: str = Form(...),
    platforms: list[str] = Form([]),
    website_url: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    project = get_active_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404)
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="프로젝트명을 입력하세요.")
    duplicate = db.scalar(select(Project).where(func.lower(Project.name) == clean_name.lower(), Project.id != project.id))
    if duplicate:
        raise HTTPException(status_code=409, detail="동일한 프로젝트명이 이미 존재합니다.")
    try:
        clean_project_type = normalize_project_type(project_type)
        clean_platforms = normalize_platforms(platforms)
        clean_website_url = normalize_website_url(website_url, clean_project_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project.name = clean_name
    project.description = description.strip() or None
    project.project_type = clean_project_type
    project.platforms = clean_platforms
    project.website_url = clean_website_url
    project.updated_at = datetime.now(timezone.utc)
    add_audit(db, user.id, "UPDATE_PROJECT_SETTINGS", project.name)
    db.commit()
    return RedirectResponse(f"/projects/{project.id}?tab=settings&notice=saved", status_code=303)


@app.post("/projects/{project_id}/output")
def update_project_output(
    request: Request,
    project_id: int,
    project_type: str = Form(...),
    platforms: list[str] = Form([]),
    website_url: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    project = get_active_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404)
    try:
        clean_project_type = normalize_project_type(project_type)
        clean_platforms = normalize_platforms(platforms)
        project.website_url = normalize_website_url(website_url, clean_project_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project.project_type = clean_project_type
    project.platforms = clean_platforms
    project.updated_at = datetime.now(timezone.utc)
    add_audit(db, user.id, "UPDATE_PROJECT_OUTPUT", f"{clean_project_type}: {project.website_url or ''}")
    db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@app.post("/api/smart-upload/analyze")
async def analyze_upload(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    payload = await request.json()
    filenames = payload.get("filenames") or []
    result = []
    for filename in filenames:
        info = analyze_filename(safe_filename(str(filename)))
        result.append({
            "filename": info.filename,
            "version": info.version,
            "file_type": info.file_type,
            "mime_type": info.mime_type,
            "needs_version": info.version is None,
        })
    groups: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for item in result:
        if item["version"]:
            groups.setdefault(item["version"], []).append(item["filename"])
        else:
            unresolved.append(item["filename"])
    return {"files": result, "groups": groups, "unresolved": unresolved}


@app.post("/projects/{project_id}/smart-upload")
def smart_upload(
    request: Request,
    project_id: int,
    files: list[UploadFile] = File(...),
    release_notes: str = Form(""),
    version_override: str = Form(""),
    overwrite: bool = Form(False),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    project = get_active_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404)
    storage = get_storage()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    uploaded: list[tuple[Release, ReleaseFile]] = []

    for item in files:
        filename = safe_filename(item.filename or "")
        analysis = analyze_filename(filename)
        version = analysis.version or version_override.strip()
        if not version:
            raise HTTPException(status_code=400, detail=f"{filename}: 버전을 자동으로 인식하지 못했습니다.")
        release = ensure_release(db, project, version, user.id, release_notes.strip() or None)
        existing = db.scalar(select(ReleaseFile).where(ReleaseFile.release_id == release.id, ReleaseFile.original_filename == filename))
        if existing and not overwrite:
            raise HTTPException(status_code=409, detail=f"동일 파일이 이미 존재합니다: {filename}")

        target = project_release_path(project, version, filename)
        ensure_dirs(storage, str(PurePosixPath(target).parent))
        temp, size, sha256 = hash_and_spool(item.file, max_bytes)
        try:
            storage.write_stream(target, temp, item.content_type or analysis.mime_type)
        finally:
            temp.close()

        if existing:
            existing.storage_path = target
            existing.file_size = size
            existing.file_type = analysis.file_type
            existing.mime_type = item.content_type or analysis.mime_type
            existing.sha256 = sha256
            rf = existing
            add_audit(db, user.id, "REPLACE_RELEASE_FILE", target)
        else:
            rf = ReleaseFile(
                release_id=release.id,
                original_filename=filename,
                storage_path=target,
                file_size=size,
                file_type=analysis.file_type,
                mime_type=item.content_type or analysis.mime_type,
                sha256=sha256,
                is_primary_download=False,
            )
            db.add(rf)
            release.files.append(rf)
            add_audit(db, user.id, "SMART_UPLOAD", target, f"project={project.name}, version={version}, type={analysis.file_type}")
        uploaded.append((release, rf))

    db.flush()
    release_ids = {r.id for r, _ in uploaded}
    for release_id in release_ids:
        release = db.scalar(select(Release).where(Release.id == release_id).options(selectinload(Release.files)))
        if release:
            # If only auto-selected values exist, recompute a sensible primary.
            for f in release.files:
                f.is_primary_download = False
            refresh_primary_file(release)
    refresh_latest_flags(db, project.id)
    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(f"/projects/{project.id}?tab=releases&notice=release-uploaded", status_code=303)


@app.get("/releases/files/{file_id}/download")
def release_download(request: Request, file_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    rf = db.scalar(select(ReleaseFile).where(ReleaseFile.id == file_id).options(selectinload(ReleaseFile.release).selectinload(Release.project)))
    if not rf:
        raise HTTPException(status_code=404)
    try:
        data = get_storage().read_bytes(rf.storage_path)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    rf.download_count += 1
    rf.last_downloaded_at = datetime.now(timezone.utc)
    add_audit(db, user.id, "DOWNLOAD_RELEASE", rf.storage_path)
    db.commit()
    return Response(
        data,
        media_type=rf.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(rf.original_filename)}"},
    )


@app.get("/projects/{project_id}/latest/download")
def latest_download(request: Request, project_id: int, db: Session = Depends(get_db)):
    require_user(request, db)
    release = db.scalar(
        select(Release).where(Release.project_id == project_id, Release.is_latest.is_(True)).options(selectinload(Release.files))
    )
    if not release or not release.files:
        raise HTTPException(status_code=404, detail="다운로드할 최신 릴리스가 없습니다.")
    primary = next((f for f in release.files if f.is_primary_download), release.files[0])
    return RedirectResponse(f"/releases/files/{primary.id}/download", status_code=303)


@app.post("/releases/{release_id}/latest")
def set_latest(request: Request, release_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    release = db.get(Release, release_id)
    if not release:
        raise HTTPException(status_code=404)
    db.query(Release).filter(Release.project_id == release.project_id).update({Release.is_latest: False})
    release.is_latest = True
    add_audit(db, user.id, "SET_LATEST_RELEASE", str(release.id), release.version)
    db.commit()
    return RedirectResponse(f"/projects/{release.project_id}", status_code=303)


@app.post("/release-files/{file_id}/primary")
def set_primary(request: Request, file_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    rf = db.get(ReleaseFile, file_id)
    if not rf:
        raise HTTPException(status_code=404)
    db.query(ReleaseFile).filter(ReleaseFile.release_id == rf.release_id).update({ReleaseFile.is_primary_download: False})
    rf.is_primary_download = True
    add_audit(db, user.id, "SET_PRIMARY_DOWNLOAD", rf.storage_path)
    db.commit()
    return RedirectResponse(f"/projects/{rf.release.project_id}", status_code=303)


@app.post("/projects/{project_id}/readme")
def upload_readme(request: Request, project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    project = get_active_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404)
    filename = safe_filename(file.filename or "README.md")
    if not filename.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="README는 Markdown(.md) 파일만 지원합니다.")
    target = f"{project_storage_path(project)}/README.md"
    storage = get_storage()
    ensure_dirs(storage, str(PurePosixPath(target).parent))
    temp, _, _ = hash_and_spool(file.file, min(settings.max_upload_mb, 10) * 1024 * 1024)
    try:
        storage.write_stream(target, temp, "text/markdown")
    finally:
        temp.close()
    project.readme_path = target
    add_audit(db, user.id, "UPLOAD_README", target)
    db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


# ---------------- Shares ----------------
@app.get("/shares", response_class=HTMLResponse)
def shares_page(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    shares = list(db.scalars(select(ShareLink).order_by(desc(ShareLink.created_at))).all())
    return templates.TemplateResponse(request, "shares.html", template_context(request, shares=shares))


@app.post("/shares")
def create_share(request: Request, storage_path: str = Form(...), days: int = Form(7), db: Session = Depends(get_db)):
    user = require_user(request, db)
    rel = normalize_repo_path(storage_path)
    if not get_storage().exists(rel):
        raise HTTPException(status_code=404, detail="공유할 파일이 존재하지 않습니다.")
    share = ShareLink(
        token=secrets.token_urlsafe(32),
        storage_path=rel,
        created_by_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=max(1, min(days, 365))),
    )
    db.add(share)
    add_audit(db, user.id, "CREATE_SHARE", rel)
    db.commit()
    return RedirectResponse("/shares", status_code=303)


@app.get("/s/{token}")
def public_share(token: str, db: Session = Depends(get_db)):
    share = db.scalar(select(ShareLink).where(ShareLink.token == token))
    if not share:
        raise HTTPException(status_code=404)
    now = datetime.now(timezone.utc)
    if share.expires_at and share.expires_at < now:
        raise HTTPException(status_code=410, detail="공유 링크가 만료되었습니다.")
    try:
        data = get_storage().read_bytes(share.storage_path)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    filename = PurePosixPath(share.storage_path).name
    return Response(data, media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
    })


# ---------------- Users ----------------
@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    users = list(db.scalars(select(User).order_by(User.username)).all())
    return templates.TemplateResponse(request, "users.html", template_context(request, users=users))


@app.post("/users")
def create_user(request: Request, username: str = Form(...), password: str = Form(...), display_name: str = Form(""), is_admin: bool = Form(False), db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    clean = username.strip()
    if not clean or len(password) < 4:
        raise HTTPException(status_code=400, detail="사용자명과 4자 이상의 비밀번호를 입력하세요.")
    if db.scalar(select(User).where(User.username == clean)):
        raise HTTPException(status_code=409, detail="이미 존재하는 사용자입니다.")
    user = User(username=clean, password_hash=hash_password(password), display_name=display_name.strip() or clean, is_admin=is_admin, is_active=True)
    db.add(user)
    add_audit(db, admin.id, "CREATE_USER", clean)
    db.commit()
    return RedirectResponse("/users", status_code=303)


# ---------------- Logs ----------------
@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    logs = list(db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(300)).all())
    users = {u.id: u for u in db.scalars(select(User)).all()}
    return templates.TemplateResponse(request, "logs.html", template_context(request, logs=logs, users=users))
