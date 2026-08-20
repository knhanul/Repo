from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_schema_compatibility() -> None:
    inspector = inspect(engine)
    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    project_additions = {
        "storage_root": "VARCHAR(1000)",
        "project_type": "VARCHAR(40)",
        "platforms": "JSON",
        "website_url": "VARCHAR(1000)",
        "source_url": "VARCHAR(1000)",
        "is_deleted": "BOOLEAN",
        "deleted_at": "TIMESTAMP",
        "deleted_by_id": "INTEGER",
        "trash_path": "VARCHAR(1000)",
    }
    resource_columns = {column["name"] for column in inspector.get_columns("project_resources")}
    resource_additions = {
        "is_deleted": "BOOLEAN",
        "deleted_at": "TIMESTAMP",
        "deleted_by_id": "INTEGER",
        "trash_path": "VARCHAR(1000)",
    }
    missing_projects = [(name, definition) for name, definition in project_additions.items() if name not in project_columns]
    missing_resources = [(name, definition) for name, definition in resource_additions.items() if name not in resource_columns]
    if not missing_projects and not missing_resources:
        return
    with engine.begin() as connection:
        for name, definition in missing_projects:
            connection.execute(text(f"ALTER TABLE projects ADD COLUMN {name} {definition}"))
        for name, definition in missing_resources:
            connection.execute(text(f"ALTER TABLE project_resources ADD COLUMN {name} {definition}"))
        missing_project_names = {name for name, _ in missing_projects}
        if "project_type" in missing_project_names and "output_type" in project_columns:
            connection.execute(text("""
                UPDATE projects
                SET project_type = CASE output_type
                    WHEN 'windows_app' THEN 'WINDOWS_APP'
                    WHEN 'smartphone_app' THEN 'MOBILE_APP'
                    WHEN 'website' THEN 'WEB_APP'
                    ELSE 'OTHER'
                END
                WHERE project_type IS NULL
            """))
        if "platforms" in missing_project_names:
            connection.execute(text("UPDATE projects SET platforms = '[]' WHERE platforms IS NULL"))
        if "is_deleted" in missing_project_names:
            connection.execute(text("UPDATE projects SET is_deleted = FALSE WHERE is_deleted IS NULL"))
        if "is_deleted" in {name for name, _ in missing_resources}:
            connection.execute(text("UPDATE project_resources SET is_deleted = FALSE WHERE is_deleted IS NULL"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
