"""Krita project lifecycle, native files, project images and canvas placement."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from image_studio.services import image_imports, krita_projects as projects, library

router = APIRouter(prefix='/api/krita/projects')


def guarded(call):
    try:
        return call()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc


class NewProject(BaseModel):
    name: str = Field(default='Untitled project', min_length=1, max_length=150)
    width: int = Field(default=1600, ge=1, le=8192)
    height: int = Field(default=1000, ge=1, le=8192)
    use_current: bool = False

    @model_validator(mode='after')
    def canvas_size(self):
        if not self.use_current and self.width * self.height > 40_000_000:
            raise ValueError('Choose a canvas of at most 40 megapixels.')
        return self


class ProjectAction(BaseModel):
    action: Literal['open', 'save', 'close', 'clear', 'restore']


class ProjectName(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class Placement(BaseModel):
    fit: bool = False
    x: float | None = Field(default=None, ge=-8192, le=16384, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=-8192, le=16384, allow_inf_nan=False)
    as_canvas: bool = False


class LayerAction(BaseModel):
    operation: Literal['select', 'transform', 'visibility', 'opacity', 'delete']
    dx: float = Field(default=0, ge=-16384, le=16384, allow_inf_nan=False)
    dy: float = Field(default=0, ge=-16384, le=16384, allow_inf_nan=False)
    scaleX: float = Field(default=100, ge=1, le=1000, allow_inf_nan=False)
    scaleY: float = Field(default=100, ge=1, le=1000, allow_inf_nan=False)
    visible: bool = True
    opacity: int = Field(default=100, ge=0, le=100)


@router.get('')
def list_projects():
    return {'projects': projects.recent()}


@router.post('')
def new_project(request: NewProject):
    data = guarded(
        lambda: projects.create(request.name, request.width, request.height, use_current=request.use_current)
    )
    return dict(project=data, message='Project created and saved. Import your source images below.')


@router.post('/import')
async def import_project(file: Annotated[UploadFile, File()]):
    try:
        contents = await file.read(500_000_001)
    finally:
        await file.close()
    if not contents or len(contents) > 500_000_000:
        raise HTTPException(422, 'Choose a project under 500 MB.')
    if (file.filename or '').lower().endswith('.istudio'):
        data = await run_in_threadpool(guarded, lambda: projects.import_archive(contents))
    else:
        name = (file.filename or 'Imported project').rsplit('.', 1)[0]
        data = await run_in_threadpool(
            guarded, lambda: projects.create(name, contents=contents, filename=file.filename)
        )
    return dict(project=data, message='Project opened and saved on this computer.')


@router.post('/from-library')
def library_project(request: ProjectName):
    source = guarded(lambda: library.image_path(request.name))
    data = guarded(lambda: projects.create(source.stem, contents=source.read_bytes(), filename=source.name))
    return dict(project=data, message='Library image opened as a saved project.')


@router.post('/{ident}/action')
def project_action(ident: str, request: ProjectAction):
    result = guarded(lambda: projects.action(ident, request.action))
    return dict(
        project=result,
        closed=request.action == 'close',
        message='Project closed and saved.' if request.action == 'close' else 'Project saved.',
    )


@router.post('/{ident}/rename')
def rename_project(ident: str, request: ProjectName):
    return dict(project=guarded(lambda: projects.rename(ident, request.name)), message='Project renamed.')


@router.get('/{ident}/file')
def save_project_file(ident: str):
    path = guarded(lambda: projects.archive(ident))
    return FileResponse(
        path,
        filename='Krita project.istudio',
        media_type='application/zip',
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.get('/{ident}/native')
def native_project(ident: str):
    guarded(lambda: projects.save_for_export(ident))
    return FileResponse(projects.folder_for(ident) / 'project.kra', filename='Krita project.kra')


@router.get('/{ident}/thumbnail')
def project_thumbnail(ident: str):
    return Response(guarded(lambda: projects.thumbnail(ident)), media_type='image/png')


@router.post('/{ident}/assets')
async def import_images(ident: str, files: Annotated[list[UploadFile], File()]):
    try:
        images = await image_imports.read_files(files)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    data = await run_in_threadpool(guarded, lambda: projects.import_assets(ident, images))
    return dict(project=data, message='Images saved to the project. Choose Place to add one to the canvas.')


@router.get('/{ident}/assets/{asset_id}/thumbnail')
def asset_thumbnail(ident: str, asset_id: str):
    data = guarded(lambda: projects.load(ident))
    asset = guarded(lambda: projects.sources.asset_for(data, asset_id))
    return FileResponse(
        projects.folder_for(ident) / 'assets' / f'{asset["id"]}-thumb.png', media_type='image/png'
    )


@router.post('/{ident}/assets/{asset_id}/place')
def place_image(ident: str, asset_id: str, request: Placement):
    data = guarded(
        lambda: projects.place_asset(ident, asset_id, request.fit, request.x, request.y, request.as_canvas)
    )
    return dict(project=data, message='Image placed and project saved.')


@router.post('/{ident}/layers/{layer_id}')
def layer_action(ident: str, layer_id: str, request: LayerAction):
    data = guarded(
        lambda: projects.layer_action(
            ident, layer_id, request.operation, request.model_dump(exclude={'operation'})
        )
    )
    return dict(project=data, message='Project saved.')


@router.get('/{ident}/layers/{layer_id}/preview/{version}/{part}')
def layer_preview(ident: str, layer_id: str, version: int, part: str):
    if not 0 <= version < 10**12:
        raise HTTPException(422, 'Invalid preview version.')
    path = guarded(lambda: projects.layer_preview(ident, layer_id, version, part))
    return FileResponse(path, media_type='image/png')
