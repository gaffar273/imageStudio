"""Document workspace API; clients never supply executable or filesystem paths."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from image_studio.integrations import photocraft_workspace as workspace
from image_studio.integrations.photocraft_area import MarkedArea
from image_studio.services import library, workflows
from image_studio.services.jobs import BusyError, store

router = APIRouter(prefix='/api/photocraft')


class NewDocument(BaseModel):
    name: str = Field(default='Untitled', min_length=1, max_length=150)
    width: int = Field(default=1600, ge=1, le=8192)
    height: int = Field(default=1000, ge=1, le=8192)


class PromptRequest(BaseModel):
    revision: str = Field(pattern='^[a-f0-9]{32}$')
    prompt: str = Field(min_length=1, max_length=6000)
    area: MarkedArea | None = None


class Operation(BaseModel):
    revision: str = Field(pattern='^[a-f0-9]{32}$')
    action: Literal['apply', 'undo', 'redo', 'goto', 'desktop', 'sync'] = 'apply'
    plan_id: str | None = Field(default=None, pattern='^[a-f0-9]{32}$')
    partial: bool = False
    index: int | None = Field(default=None, ge=0, le=100000)
    commands: list[dict] | None = Field(default=None, max_length=32)
    label: str = Field(default='Manual edit', max_length=200)


class EditsRequest(BaseModel):
    revision: str = Field(pattern='^[a-f0-9]{32}$')
    edits: list[dict] = Field(min_length=1, max_length=16)
    label: str = Field(default='Edit', min_length=1, max_length=200)


def guarded(call):
    try:
        return call()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc)) from exc


def submit(run):
    def worker(progress, update):
        try:
            run(progress, update)
        except workspace.Cancelled as exc:
            update(message=str(exc))

    try:
        return store.submit(worker)
    except BusyError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/capabilities')
def capabilities():
    return guarded(workspace.capabilities)


@router.get('/fonts')
def fonts():
    return {'fonts': workspace.fonts()}


@router.get('/workspaces')
def workspaces():
    return {'workspaces': workspace.recent()}


@router.post('/workspaces', status_code=202)
def new_document(request: NewDocument):
    def run(progress, update):
        progress(0.1, desc='Creating your PhotoCraft document…')
        result = workspace.create(
            filename=request.name,
            width=request.width,
            height=request.height,
            cancelled=workflows.engine.cancelled,
        )
        update(workspace=result, message='Document ready.')

    return submit(run)


@router.post('/workspaces/import', status_code=202)
async def import_document(file: Annotated[UploadFile, File()]):
    contents = await file.read(100_000_001)
    await file.close()
    if not contents or len(contents) > 100_000_000:
        raise HTTPException(422, 'Choose a document between 1 byte and 100 MB.')
    filename = file.filename or 'image.png'

    def run(progress, update):
        progress(0.1, desc='Opening the document and reading its layers…')
        result = workspace.create(contents, filename, cancelled=workflows.engine.cancelled)
        update(workspace=result, message='Document ready. Describe your edit.')

    return submit(run)


class LibraryDocument(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post('/workspaces/from-library', status_code=202)
def library_document(request: LibraryDocument):
    """Open a library picture without a download and upload; a PhotoCraft edit opens with its layers."""
    image = guarded(lambda: library.image_path(request.name))
    layered = image.with_suffix('.psd')
    source = layered if image.name.startswith('photocraft_') and layered.is_file() else image

    def run(progress, update):
        progress(0.1, desc='Opening the picture and reading its layers…')
        result = workspace.create(source.read_bytes(), source.name, cancelled=workflows.engine.cancelled)
        update(workspace=result, message='Document ready. Describe your edit.')

    return submit(run)


@router.get('/workspaces/{workspace_id}')
def get_workspace(workspace_id: str):
    return guarded(lambda: workspace.public(workspace.load(workspace_id)))


@router.get('/workspaces/{workspace_id}/preview/{revision}')
def preview(workspace_id: str, revision: str):
    data = guarded(lambda: workspace.load(workspace_id))
    if revision not in {entry['id'] for entry in data['history']}:
        raise HTTPException(404, 'Preview not found.')
    return FileResponse(workspace.folder_for(workspace_id) / f'{revision}.png', media_type='image/png')


@router.post('/workspaces/{workspace_id}/plan', status_code=202)
def plan(workspace_id: str, request: PromptRequest):
    guarded(lambda: workspace.require_revision(workspace.load(workspace_id), request.revision))
    if not request.prompt.strip():
        raise HTTPException(422, 'Describe the edit first.')

    def run(progress, update):
        result = workspace.smart_plan(
            workspace_id, request.revision, request.prompt, progress, workflows.engine.cancelled,
            area=request.area.model_dump() if request.area else None,
        )
        update(
            plan=result,
            message='Review the unresolved details.' if result['unresolved'] else 'Your edit plan is ready.',
        )

    return submit(run)


@router.post('/workspaces/{workspace_id}/operation', status_code=202)
def operation(workspace_id: str, request: Operation):
    guarded(lambda: workspace.require_revision(workspace.load(workspace_id), request.revision))
    steps, label, plan = request.commands, request.label, None
    if request.action == 'apply':
        if request.plan_id:
            plan = guarded(lambda: workspace.load_plan(workspace_id, request.plan_id, request.partial))
            if plan['revision'] != request.revision:
                raise HTTPException(409, 'That plan belongs to another revision. Create a new plan.')
            steps, label = plan['steps'], plan['prompt']
        guarded(lambda: workspace.validate_steps(steps, workspace.folder_for(workspace_id)))
    if request.action == 'goto' and request.index is None:
        raise HTTPException(422, 'Choose a revision.')

    def run(progress, update):
        if request.action == 'apply':
            result = workspace.apply(
                workspace_id, request.revision, steps, label, progress, workflows.engine.cancelled, plan
            )
        elif request.action == 'goto':
            result = workspace.goto(workspace_id, request.revision, request.index)
        elif request.action in {'undo', 'redo'}:
            result = workspace.move_history(
                workspace_id, request.revision, -1 if request.action == 'undo' else 1
            )
        elif request.action == 'desktop':
            result = workspace.desktop(workspace_id, request.revision)
        else:
            result = workspace.sync_desktop(workspace_id, request.revision, workflows.engine.cancelled)
        update(
            workspace=result,
            message='Opened a copy in PhotoCraft. Save there, then sync here.'
            if request.action == 'desktop'
            else 'Document updated.',
        )

    return submit(run)


@router.post('/workspaces/{workspace_id}/edits', status_code=202)
def edits(workspace_id: str, request: EditsRequest):
    """Edits from the manual panels, planned and applied in one step."""
    guarded(lambda: workspace.require_revision(workspace.load(workspace_id), request.revision))

    def run(progress, update):
        progress(0.05, desc='Preparing your edit…')
        plan = workspace.manual_plan(workspace_id, request.revision, request.edits, request.label)
        if plan['unresolved'] or not plan['steps']:
            raise ValueError(' '.join(plan['unresolved']) or 'Nothing to apply.')
        result = workspace.apply(
            workspace_id, request.revision, plan['steps'], request.label, progress, workflows.engine.cancelled, plan
        )
        update(workspace=result, message=f'{request.label} applied.')

    return submit(run)


@router.get('/workspaces/{workspace_id}/export/{revision}/{format}')
def export(workspace_id: str, revision: str, format: str):
    path = guarded(lambda: workspace.export(workspace_id, revision, format))
    return FileResponse(path, filename=f'photocraft-{revision[:8]}.{format}')
