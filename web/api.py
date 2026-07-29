"""FastPPM public reads and storage-backed token-gated writes."""

from pathlib import Path

from fastapi import Depends
from pydantic import BaseModel, Field

from storage import get_store

from .api_core import (
    Resource,
    SQLiteBackend,
    create_sqlite_api,
    require_write_token,
)

store = get_store()
store.init_db()
db_url = getattr(store, "db_url", "sqlite:///fastppm.db")
if not db_url.startswith("sqlite:///"):
    raise RuntimeError("The vendored FastPPM API adapter currently requires DATA_STORAGE=sqlite")

RESOURCES = (
    Resource("projects", "initiatives", "Projects", "Portfolio initiatives, programmes, and workstreams.", search_fields=("ref", "name", "description", "type", "owner", "status")),
    Resource("milestones", "milestones", "Milestones", "Initiative milestones, progress, and dependencies.", search_fields=("title", "status", "owner")),
    Resource("risks", "risks", "Risks", "Portfolio risks, mitigations, probability, and impact.", search_fields=("description", "status", "mitigation", "owner")),
    Resource("documents", "documents", "Documents", "Portfolio source documents and extraction state.", search_fields=("file_name", "file_type", "status", "summary")),
)

backend = SQLiteBackend(Path(db_url.removeprefix("sqlite:///")), RESOURCES)
api = create_sqlite_api(
    product="FastPPM", version="1.0.0",
    description="Open integration access to FastPPM projects, milestones, risks, and documents.",
    base_url="https://ppm.fastsme.com", backend=backend, resources=RESOURCES,
)


class ProjectCreate(BaseModel):
    ref: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=250)
    description: str = ""
    type: str = "workstream"
    owner: str = ""
    status: str = "not_started"
    value_target: float = 0


@api.post(
    "/v1/projects",
    status_code=201,
    dependencies=[Depends(require_write_token)],
    tags=["Projects"],
)
def create_project(payload: ProjectCreate):
    """Create or update a project through FastPPM's storage contract."""

    item_id = store.upsert_initiative(payload.model_dump())
    return store.get_initiative(item_id)
