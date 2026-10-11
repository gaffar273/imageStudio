"""JSON API consumed by the React studio."""

import base64
import io
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from image_studio.api.schemas import (
    GenerateRequest,
    EditRequest,
    SketchRequest,
    KritaRequest,
    FavoriteRequest,
    MemoryRequest,
    PersonalLoraRequest,
)
from image_studio.core.catalog import MODELS, SIZES, DEFAULT_NEGATIVE, KONTEXT, EDIT_QUALITY
from image_studio.core.paths import CACHE
from image_studio.services import workflows, library, assistant, search, repair, faces, memory, personal
from image_studio.services.jobs import store, BusyError
from image_studio.integrations import bridge, photocraft

router = APIRouter(prefix='/api')


def decode_image(value):
    try:
        if value.startswith('/images/'):
            image = Image.open(library.image_path(value.removeprefix('/images/')))
        else:
            if len(value) > 40_000_000:
                raise ValueError('Image is too large. Use a file under 30 MB.')
            image = Image.open(io.BytesIO(base64.b64decode(value.split(',')[-1], validate=True)))
        if image.width * image.height > 25_000_000:
            raise ValueError('Please use an image below 25 megapixels.')
        image.load()
        return image
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, str(exc) or 'Unable to read the image.') from exc


def require_image(name):
    try:
        return library.image_path(name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc


def submit(run):
    try:
        return store.submit(run)
    except BusyError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/health')
def health():
    return dict(ok=True, title='Local Image Studio', version='2.0.0')


@router.get('/config')
def config():
    return dict(
        models=[
            dict(id=key, label=value['label'], ready=(value['folder'] / 'model_index.json').exists())
            for key, value in MODELS.items()
        ],
        sizes=[dict(id=name, width=size[0], height=size[1]) for name, size in SIZES.items()],
        negative_prompt=DEFAULT_NEGATIVE,
        assistant=assistant.available(),
        search=search.available(),
        repair=repair.available(),
        references=faces.available(),
        lora=workflows.lora_ready(),
        personal_lora=personal.ready(),
        editing=(KONTEXT['folder'] / 'model_index.json').exists(),
        photocraft=photocraft.available(),
        active_job=store.active,
    )


@router.get('/library')
def images(q: str = ''):
    items = library.list_images(q)
    return dict(images=items, total=len(items))


@router.get('/library/search')
def semantic_search(q: str = '', similar: str = ''):
    if not search.available():
        raise HTTPException(409, 'Install the image search model from scripts/windows first.')
    try:
        reply = search.similar(require_image(similar).name, 24) if similar else search.search(q, 24)
        return dict(
            images=[library.item(require_image(name)) for name, _ in reply['results']], total=reply['total']
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get('/library/{name}/thumbnail')
def thumbnail(name: str):
    path = require_image(name)
    target = CACHE / 'thumbnails' / (path.stem + '.jpg')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_mtime < path.stat().st_mtime:
        with Image.open(path) as image:
            image.thumbnail((600, 600))
            image.convert('RGB').save(target, 'JPEG', quality=85)
    return FileResponse(target, media_type='image/jpeg')


@router.get('/library/{name}/download')
def download(name: str):
    return FileResponse(require_image(name), filename=name, media_type='image/png')


@router.post('/generate', status_code=202)
def generate(request: GenerateRequest):
    if request.size not in SIZES or not request.prompt.strip():
        raise HTTPException(422, 'Choose a valid size and describe your image.')
    sketch = workflows.editor_value(decode_image(request.sketch)) if request.sketch else None

    def run(progress, update):
        # The personal style applies to this request only (RealVisXL images and finishes).
        workflows.engine.personal = request.personal
        try:
            for result in workflows.generate(
                request.prompt,
                '' if request.seed is None else str(request.seed),
                request.model,
                request.size,
                request.steps,
                request.guidance,
                request.negative_prompt,
                request.detail,
                request.detail_strength,
                request.count,
                request.smart,
                sketch,
                request.sketch_freedom,
                request.vary,
                request.check,
                request.attempts,
                request.repair,
                request.repair_strength,
                request.photo_style,
                request.photo_finish,
                request.combine,
                request.references,
                request.realism,
                progress=progress,
            ):
                gallery = result[0].get('value')
                values = dict(message=result[1], understood=result[3], report=result[4])
                if gallery:
                    values['images'] = [
                        library.item(Path(item[0] if isinstance(item, (tuple, list)) else item))
                        for item in gallery
                    ]
                update(**values)
        finally:
            workflows.engine.personal = 0.0

    return submit(run)


@router.post('/edit', status_code=202)
def edit(request: EditRequest):
    image = decode_image(request.image).convert('RGBA' if request.engine == 'photocraft' else 'RGB')
    mask = decode_image(request.mask).convert('L') if request.mask else None
    if mask and mask.size != image.size:
        raise HTTPException(422, 'The mask must have the same dimensions as the image.')
    prompt, _ = memory.rewrite(request.prompt)  # words the person has taught

    if request.engine == 'photocraft':
        if mask is not None:
            raise HTTPException(
                422, 'PhotoCraft text edits currently apply to the whole photo. Clear the mask first.'
            )
        if not photocraft.available():
            raise HTTPException(409, 'PhotoCraft CLI was not found.')
        try:
            commands = photocraft.plan(prompt)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        source_document = None
        if request.image.startswith('/images/photocraft_'):
            candidate = require_image(request.image.removeprefix('/images/')).with_suffix('.psd')
            if candidate.is_file():
                source_document = candidate

        def run_photocraft(progress, update):
            result = photocraft.edit(
                image, prompt, commands, progress, workflows.engine.cancelled,
                source_document=source_document,
            )
            if result:
                update(
                    message='PhotoCraft edit ready. Download the PSD to adjust its layers.',
                    understood='; '.join(label for _, _, label in commands),
                    images=[library.item(result)],
                )

        return submit(run_photocraft)

    def run(progress, update):
        result = workflows.edit_photo(
            dict(background=image, layers=[mask] if mask else [], composite=image),
            prompt,
            '' if request.seed is None else str(request.seed),
            request.steps,
            request.guidance,
            next(iter(EDIT_QUALITY)),
            request.smart,
            progress=progress,
        )
        update(
            message=result[2],
            understood=result[5],
            images=[library.item(Path(result[0]))] if isinstance(result[0], str) else [],
        )

    return submit(run)


def require_photocraft_document(name):
    image = require_image(name)
    document = image.with_suffix('.psd')
    if not image.name.startswith('photocraft_') or not document.is_file():
        raise HTTPException(404, 'No PhotoCraft document exists for this image.')
    return document


@router.get('/photocraft/{name}/download')
def photocraft_download(name: str):
    document = require_photocraft_document(name)
    return FileResponse(document, filename=document.name, media_type='image/vnd.adobe.photoshop')


@router.post('/photocraft/{name}/open')
def photocraft_open(name: str):
    document = require_photocraft_document(name)
    try:
        photocraft.open_document(document)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return dict(message='Opened the layered edit in PhotoCraft.')


@router.post('/sketch', status_code=202)
def sketch(request: SketchRequest):
    if request.size not in SIZES:
        raise HTTPException(422, 'Unknown image size.')

    def run(progress, update):
        result, note = workflows.sketch_layout(request.prompt, request.size, progress=progress)
        update(sketch='data:image/png;base64,' + bridge.encode_png(result['background']), message=note)

    return submit(run)


@router.get('/jobs/{job_id}')
def job(job_id: str):
    try:
        return store.get(job_id)
    except KeyError:
        raise HTTPException(404, 'Job not found. The server may have restarted.')


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str):
    try:
        return store.cancel(job_id)
    except KeyError:
        raise HTTPException(404, 'Job not found.')


@router.get('/favorites')
def favorites():
    return dict(names=memory.favorites())


@router.post('/favorites')
def set_favorite(request: FavoriteRequest):
    require_image(request.name)
    return dict(names=memory.set_favorite(request.name, request.favorite))


@router.get('/memory')
def what_was_learned():
    return dict(**memory.snapshot(), personal=personal.status())


@router.post('/memory')
def change_memory(request: MemoryRequest):
    if request.action == 'forget':
        memory.forget(request.phrase)
    elif request.action == 'forget_all':
        memory.forget()
    elif request.action == 'reset_strength':
        data = memory.load()
        data['strength'] = {}
        memory.save(data)
    elif memory.teach(request.phrase, request.means) is None:
        raise HTTPException(422, 'Give a phrase of at least 3 letters and what it should mean.')
    return what_was_learned()


@router.post('/personal-lora')
def personal_lora(request: PersonalLoraRequest):
    if request.action == 'nightly':
        personal.set_nightly(request.enabled)
        return personal.status()
    try:
        return personal.start('manual', only_if_needed=request.if_needed)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/krita')
def krita():
    bridge.link.watching()
    return dict(
        connected=bridge.link.connected,
        state=bridge.link.state,
        events=list(bridge.link.events)[-30:],
        preview_version=bridge.link.preview_version,
        preview=bool(bridge.link.preview),
    )


@router.get('/krita/preview')
def krita_preview():
    bridge.link.watching()
    if not bridge.link.preview:
        raise HTTPException(404, 'No canvas preview yet.')
    return Response(bridge.link.preview, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})


@router.post('/krita')
def krita_command(request: KritaRequest):
    try:
        if request.action == 'launch':
            message = workflows.start_krita()
        elif request.action == 'open':
            message = workflows.open_in_krita(require_image(request.image or ''))
        elif request.action == 'import':
            if not request.image:
                raise HTTPException(422, 'Choose an image to import.')
            image = ImageOps.exif_transpose(decode_image(request.image)).convert('RGBA')
            folder = CACHE / 'krita-imports'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'import-{uuid.uuid4().hex}.png'
            image.save(path)
            try:
                message = workflows.open_in_krita(path)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        elif request.action == 'prompt':
            message = workflows.run_in_krita(request.text)
        else:
            message = workflows.krita_command(request.action, 'Command sent to Krita.')()
        return dict(message=message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
