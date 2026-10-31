"""Document workspace API; clients never supply executable or filesystem paths."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask

from image_studio.integrations import photocraft_workspace as workspace, photocraft_projects as projects
from image_studio.integrations.photocraft_area import MarkedArea
from image_studio.services import image_imports, library, workflows
from image_studio.services.jobs import BusyError, store

router = APIRouter(prefix='/api/photocraft')


class NewDocument(BaseModel):
    name: str = Field(default='Untitled', min_length=1, max_length=150)
    width: int = Field(default=1600, ge=1, le=8192)
    height: int = Field(default=1000, ge=1, le=8192)

    @model_validator(mode='after')
    def canvas_size(self):
        if self.width * self.height > 40_000_000:
            raise ValueError('Choose a canvas of at most 40 megapixels.')
        return self


class PromptRequest(BaseModel):
    revision: str = Field(pattern='^[a-f0-9]{32}$')
    prompt: str = Field(min_length=1, max_length=6000)
    area: MarkedArea | None = None


class Operation(BaseModel):
    revision: str = Field(pattern='^[a-f0-9]{32}$')
    action: Literal['apply', 'undo', 'redo', 'goto', 'desktop', 'sync', 'clear'] = 'apply'
    plan_id: str | None = Field(default=None, pattern='^[a-f0-9]{32}$')
    partial: bool = False
    index: int | None = Field(default=None, ge=0, le=100000)
    commands: list[dict] | None = Field(default=None, max_length=32)
    label: str = Field(default='Manual edit', max_length=200)


class EditsRequest(BaseModel):
    revision: str = Field(pattern='^[a-f0-9]{32}$')
    edits: list[dict] = Field(min_length=1, max_length=16)
    label: str = Field(default='Edit', min_length=1, max_length=200)


class ProjectName(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class PlacementRequest(BaseModel):
    revision: str = Field(pattern='^[a-f0-9]{32}$')
    fit: bool = False
    x: float | None = Field(default=None, ge=-8192, le=16384, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=-8192, le=16384, allow_inf_nan=False)
    as_canvas: bool = False


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


@router.get('/pipelines')
def pipeline_catalog():
    """Every pipeline the engine can run: procedures and professional workflows, with their slots."""
    from image_studio import pipelines

    return {'pipelines': pipelines.catalog(), 'categories': [{'id': key, 'title': title}
                                                             for key, title in pipelines.CATEGORIES]}


class ModelConnection(BaseModel):
    role: Literal['planner', 'grounder', 'checker']
    preset: str | None = Field(default=None, max_length=40)
    kind: Literal['local', 'openai', 'anthropic'] | None = None
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=200)
    api_key_env: str | None = Field(default=None, max_length=80, pattern='^[A-Z_][A-Z0-9_]*$')
    structured: Literal['grammar', 'json_schema', 'json_object', 'none'] | None = None
    boxes: Literal['xyxy_1000', 'yxyx_1000'] | None = None
    vision: bool | None = None


@router.get('/models')
def model_connections():
    """Which model answers each role (planner, grounder, checker), and the ready-made presets."""
    from image_studio.pipelines import models

    return {'roles': models.describe(), 'presets': {name: {k: v for k, v in spec.items() if k != 'api_key'}
                                                   for name, spec in models.PRESETS.items()}}


@router.put('/models')
def connect_model(request: ModelConnection):
    """Connect a role to a model and save it in the studio settings. API keys stay in environment
    variables (api_key_env names one); they are never sent to or stored by this endpoint."""
    from image_studio.pipelines import models

    spec = request.model_dump(exclude_none=True)
    role = spec.pop('role')
    guarded(lambda: models.connect(role, save=True, **spec))
    return model_connections()


@router.get('/fonts')
def fonts():
    return {'fonts': workspace.fonts()}


@router.get('/workspaces')
def workspaces():
    return {'workspaces': workspace.recent()}


@router.post('/projects/import', status_code=202)
async def import_project(file: Annotated[UploadFile, File()]):
    try:
        contents = await file.read(projects.MAX_PROJECT_BYTES + 1)
    finally:
        await file.close()
    if not contents or len(contents) > projects.MAX_PROJECT_BYTES:
        raise HTTPException(422, 'Choose an Image Studio project under 500 MB.')

    def run(progress, update):
        progress(0.1, desc='Opening your project, images and editing history…')
        update(workspace=projects.import_archive(contents), message='Project opened. Changes are saved automatically.')

    return submit(run)


@router.get('/workspaces/{workspace_id}/project')
def save_project(workspace_id: str, revision: Annotated[str, Query(pattern='^[a-f0-9]{32}$')]):
    path = guarded(lambda: projects.archive(workspace_id, revision))
    return FileResponse(path, filename='Image Studio project.istudio', media_type='application/zip',
                        background=BackgroundTask(path.unlink, missing_ok=True))


@router.post('/workspaces/{workspace_id}/rename')
def rename_project(workspace_id: str, request: ProjectName):
    return guarded(lambda: projects.rename(workspace_id, request.name))


@router.post('/workspaces/{workspace_id}/assets', status_code=202)
async def project_images(workspace_id: str, revision: Annotated[str, Query(pattern='^[a-f0-9]{32}$')],
                         files: Annotated[list[UploadFile], File()]):
    try:
        images = await image_imports.read_files(files)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    guarded(lambda: workspace.require_revision(workspace.load(workspace_id), revision))

    def run(progress, update):
        progress(0.1, desc='Saving images to your project…')
        result = projects.import_assets(workspace_id, revision, images, workflows.engine.cancelled)
        update(workspace=result, message='Images saved to the project. Choose Place when you want one on the canvas.')

    return submit(run)


@router.get('/workspaces/{workspace_id}/assets/{asset_id}/thumbnail')
def asset_thumbnail(workspace_id: str, asset_id: str):
    data = guarded(lambda: workspace.load(workspace_id))
    asset = guarded(lambda: projects.asset_for(data, asset_id))
    return FileResponse(workspace.folder_for(workspace_id) / 'assets' / f'{asset["id"]}-thumb.png', media_type='image/png')


@router.post('/workspaces/{workspace_id}/assets/{asset_id}/place', status_code=202)
def place_image(workspace_id: str, asset_id: str, request: PlacementRequest):
    data = guarded(lambda: workspace.load(workspace_id))
    guarded(lambda: workspace.require_revision(data, request.revision))
    guarded(lambda: projects.asset_for(data, asset_id))

    def run(progress, update):
        progress(0.1, desc='Placing your image…')
        if request.as_canvas:
            result = projects.clear_canvas(workspace_id, request.revision, workflows.engine.cancelled, asset_id)
        else:
            result = projects.place_asset(workspace_id, request.revision, asset_id, request.fit, request.x,
                                           request.y, workflows.engine.cancelled)
        update(workspace=result, message='Image placed. Drag it on the canvas to position it; drag a corner to resize.')

    return submit(run)


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
async def import_document(
    file: Annotated[UploadFile, File()], files: Annotated[list[UploadFile] | None, File()] = None,
):
    try:
        (filename, contents), *layers = await image_imports.read_files([file, *(files or [])])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    def run(progress, update):
        progress(0.1, desc='Opening the document and reading its layers…')
        result = workspace.create(contents, filename, cancelled=workflows.engine.cancelled, layers=layers)
        update(workspace=result, message='Document ready. Describe your edit.')

    return submit(run)


@router.post('/workspaces/{workspace_id}/layers', status_code=202)
async def import_layers(
    workspace_id: str, revision: Annotated[str, Query(pattern='^[a-f0-9]{32}$')],
    files: Annotated[list[UploadFile], File()],
):
    try:
        images = await image_imports.read_files(files)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    guarded(lambda: workspace.require_revision(workspace.load(workspace_id), revision))

    def run(progress, update):
        progress(0.1, desc='Adding images as layers…')
        result = workspace.add_layers(workspace_id, revision, images, workflows.engine.cancelled)
        update(workspace=result, message=f'Added {len(images)} image layer{"s" if len(images) != 1 else ""}.')

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


@router.post('/warm')
def warm():
    """Start loading the bundled planner model while the person looks at the photo and types:
    loading it took 37 s, paid by the first request otherwise (measured 2026-10-15). Only when the
    GPU is idle: no job running, no image model loaded and no other model kept, so a warm-up never
    pushes out something in use. A request that arrives meanwhile waits for the same load."""
    import threading

    from image_studio.pipelines import models
    from image_studio.services import assistant, brain
    from image_studio.services.runtime import render_session

    spec = models.settings().get('planner', {})
    if spec.get('kind', 'local') != 'local' or not brain.available():
        return {'warming': False, 'reason': 'the planner is not the bundled model'}
    if assistant.kept_kind() == 'brain':
        return {'warming': False, 'reason': 'already loaded'}
    if store.active or workflows.engine.model_key is not None or assistant.kept_kind() is not None:
        return {'warming': False, 'reason': 'the GPU is in use'}
    if not render_session.acquire(blocking=False):
        return {'warming': False, 'reason': 'the GPU is in use'}
    render_session.release()

    def load():
        try:
            with assistant.Resident('brain', brain._start, keep=True):
                pass
        except (RuntimeError, OSError):
            pass  # the first request starts it again and reports what went wrong

    threading.Thread(target=load, daemon=True).start()
    return {'warming': True}


@router.get('/workspaces/{workspace_id}')
def get_workspace(workspace_id: str):
    return guarded(lambda: workspace.public(workspace.load(workspace_id)))


@router.get('/workspaces/{workspace_id}/preview/{revision}')
def preview(workspace_id: str, revision: str):
    data = guarded(lambda: workspace.load(workspace_id))
    if revision not in {entry['id'] for entry in data['history']}:
        raise HTTPException(404, 'Preview not found.')
    return FileResponse(workspace.folder_for(workspace_id) / f'{revision}.png', media_type='image/png')


@router.get('/workspaces/{workspace_id}/layers/{layer_id}/preview/{revision}/{part}')
def layer_preview(workspace_id: str, layer_id: int, revision: str, part: str):
    path = guarded(lambda: workspace.layer_render(workspace_id, revision, layer_id, part))
    return FileResponse(path, media_type='image/png')


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


@router.post('/workspaces/{workspace_id}/assistant', status_code=202)
def assistant_edit(workspace_id: str, request: PromptRequest):
    guarded(lambda: workspace.require_revision(workspace.load(workspace_id), request.revision))
    if not request.prompt.strip():
        raise HTTPException(422, 'Describe what you want to change.')

    def run(progress, update):
        result = workspace.smart_plan(workspace_id, request.revision, request.prompt, progress,
            workflows.engine.cancelled, area=request.area.model_dump() if request.area else None)
        if result['unresolved'] or not result['steps']:
            update(plan=result, message='Some details need your choice. Review the questions below.')
            return
        edited = workspace.apply(workspace_id, request.revision, result['steps'], request.prompt, progress,
                                  workflows.engine.cancelled, result)
        update(workspace=edited, message='Edit applied and saved. You can compare it or undo.')

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
        elif request.action == 'clear':
            result = projects.clear_canvas(workspace_id, request.revision, workflows.engine.cancelled)
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
