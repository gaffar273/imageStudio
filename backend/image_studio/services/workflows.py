"""Rendering and editor workflows shared by the API and Krita integration."""

from image_studio.services.progress import Progress
import json
import os
import secrets
import threading
from image_studio.services import agent
from image_studio.services import assistant
from image_studio.services import brain
from image_studio.integrations import bridge
from image_studio.services import checker
from image_studio.services import finish
from image_studio.services import grading
from image_studio.services import layout
from image_studio.services import memory
from image_studio.services import retoucher
from image_studio.services import search
from image_studio.services import segment
from image_studio.services import style
from image_studio.services import variety
from PIL import Image, ImageChops, ImageOps
from image_studio.core.engine import (
    Cancelled,
    ImageEngine,
    ROOT,
    WORK,
    DETAIL_DEFAULT,
    DETAIL_STRENGTH,
    soft_mask,
    EDIT_STEPS,
    EDIT_GUIDANCE,
    LAYOUT_STRENGTH,
    DEFAULT_STEPS,
    REPAIR_STRENGTH,
)
from image_studio.core.catalog import (
    MODELS,
    SIZES,
    DEFAULT_NEGATIVE,
    EDIT_QUALITY,
    REALISM_LORA,
    REALISM_DEFAULT,
    KRITA,
)


IMAGES = ROOT / 'images'


HISTORY_LIMIT = 30


engine = ImageEngine()


lock = threading.Lock()


def recent_images():
    IMAGES.mkdir(exist_ok=True)
    files = sorted(IMAGES.glob('*.png'), key=lambda path: path.stat().st_mtime, reverse=True)
    # Called whenever a new picture is saved: image search reads it now, not at the next search.
    search.index_new_images()
    return [str(path) for path in files[:HISTORY_LIMIT]]


def parse_seed(seed_text):
    try:
        return int(seed_text.strip()) if seed_text.strip() else None
    except ValueError:
        raise ValueError('Use a whole number for the seed, or leave it blank.')


def describe(details):
    """One status line; the full details are in the image's JSON file."""
    return (
        f'{details["width"]} × {details["height"]} · {details["total_seconds"]}s · Seed {details["seed"]} '
        f'· Saved'
    )


def smart_prompt(request, mode, enabled, image=None, progress=None):
    """The prompt to use and a note: the assistant's rewrite, or the request as typed."""
    if not enabled or not request.strip():
        return request, ''
    if not assistant.available():
        return (
            request,
            'Smart prompt needs the prompt assistant: run Download prompt assistant.bat. Used your words as typed.',
        )
    if progress:
        progress(0, desc='Understanding your request...')
    try:
        with lock:
            prompt = assistant.rewrite(request, mode, image, status=lambda text: print(text, flush=True))
    except Exception as exc:  # The image still gets made from the words as typed.
        print(f'Prompt assistant failed: {exc!r}', flush=True)
        return request, 'The prompt assistant failed, so your words were used as typed.'
    lost = assistant.lost_specifics(request, prompt) if mode == 'create' else []
    if lost:
        return request, (
            f'Smart prompt dropped details from your request ({", ".join(lost)}), '
            'so your exact words were used.'
        )
    return prompt, ''


def understood_text(request, prompt, note):
    if note:
        return note
    return prompt if prompt != request else 'Used your words as typed.'


def save_check(path, check):
    """Add the check results to the image's JSON settings file."""
    settings = path.with_suffix('.json')
    details = json.loads(settings.read_text(encoding='utf-8'))
    details['check'] = check
    settings.write_text(json.dumps(details, indent=2), encoding='utf-8')


def generate(
    prompt,
    seed_text,
    model,
    size,
    steps,
    guidance,
    negative_prompt,
    detail,
    detail_strength,
    count,
    smart,
    sketch,
    sketch_freedom,
    vary,
    check,
    attempts,
    repair_on=True,
    repair_strength=REPAIR_STRENGTH,
    photo_style=style.DEFAULT_STYLE,
    photo_finish=finish.DEFAULT_FINISH,
    combine=True,
    references=True,
    realism=REALISM_DEFAULT,
    progress=Progress(),
):
    seed = parse_seed(seed_text)
    sketch = layout.from_editor(sketch)
    if sketch is not None and model == 'turbo':
        raise ValueError(
            'Layout sketches work with Realistic and Accurate. Choose one of them, or clear the sketch.'
        )
    count = int(count)
    engine.cancelled.clear()
    request = prompt
    prompt, note = smart_prompt(request, 'create', smart, progress=progress)
    understood = understood_text(request, prompt, note)
    report = ''
    if check and not assistant.available():
        check, report = (
            False,
            'Check and retry needs the prompt assistant: run Download prompt assistant.bat.',
        )
    tries = int(attempts) if check else 1
    checks = None
    gallery, finished = [], 0
    # Finish with RealVisXL: Z-Image makes every picture first (checked as usual), then
    # RealVisXL adds texture and repairs faces, so each model loads only once per batch.
    combine = bool(combine) and model == 'accurate'
    chosen = []
    first_stage = (
        dict(detail='Off', repair=False, finish='Off')
        if combine
        else dict(detail=detail, repair=bool(repair_on), finish=photo_finish)
    )
    for index in range(count):
        label = f'Image {index + 1} of {count}: ' if count > 1 else ''
        # A fixed seed gives repeatable variations: seed, seed + 1, seed + 2, ...
        base_seed = secrets.randbelow(2**31) if seed is None else (seed + index) % 2**32
        current, current_sketch, best = prompt, sketch, None
        for attempt in range(tries):
            step_label = label + (f'Attempt {attempt + 1} of {tries}: ' if tries > 1 else '')
            this_seed = base_seed if attempt == 0 else (base_seed + attempt * 7919) % 2**32
            # Features picked from the seed: a new seed gives a new face, the same seed the same one.
            this_prompt, people = (
                variety.vary(current, this_seed, short=model == 'realistic') if vary else (current, [])
            )
            try:
                with lock:
                    progress(0, desc=step_label + 'Loading model and preparing your image...')
                    path, details = engine.generate(
                        this_prompt,
                        this_seed,
                        int(steps) if model != 'turbo' else 4,
                        status=lambda text: print(text, flush=True),
                        model=model,
                        size=size,
                        guidance=float(guidance),
                        negative_prompt=negative_prompt,
                        detail_strength=float(detail_strength),
                        request=request,
                        layout=current_sketch,
                        layout_strength=float(sketch_freedom),
                        repair_strength=float(repair_strength),
                        style=photo_style,
                        people=people,
                        scene=current,
                        references=bool(references),
                        realism=float(realism),
                        **first_stage,
                        on_step=lambda step, total: progress(
                            step / total, desc=f'{step_label}Rendering {step} of {total}'
                        ),
                    )
            except Cancelled:
                break
            except (ValueError, RuntimeError) as exc:
                raise ValueError(str(exc)) from exc
            if not check:
                gallery.append((str(path), f'{label}Before RealVisXL' if combine else None))
                chosen.append(
                    dict(
                        path=path,
                        prompt=this_prompt,
                        people=people,
                        scene=current,
                        seed=this_seed,
                        label=label,
                    )
                )
                finished += 1
                prefix = f'{finished} of {count} images done. Latest: ' if count > 1 else ''
                yield (
                    dict(value=gallery, selected_index=len(gallery) - 1),
                    prefix + describe(details),
                    recent_images(),
                    understood,
                    report,
                )
                break
            progress(1, desc=step_label + 'Checking the picture against your request...')
            last = attempt + 1 == tries
            with lock, assistant.Session() as session:
                if checks is None:
                    checks = checker.plan(request, session)
                score, results = checker.inspect(Image.open(path), checks, session)
                passed = all(result['ok'] for result in results)
                next_prompt, next_sketch = current, current_sketch
                if not passed and not last and not engine.cancelled.is_set():
                    progress(1, desc=step_label + 'Rewriting the prompt to fix what was missed...')
                    next_prompt = checker.revise(current, request, results, session)
                    # Words alone keep missing counts or positions: draw them for the remaining attempts.
                    if (
                        current_sketch is None
                        and model != 'turbo'
                        and attempt + 1 >= tries // 2
                        and checker.needs_layout(results)
                    ):
                        try:
                            plan = assistant.plan_layout(request, session=session)
                            width, height = SIZES[size]
                            next_sketch = layout.draw(plan, width, height)
                        except ValueError:
                            pass
            save_check(
                path,
                dict(
                    score=round(score, 3),
                    passed=passed,
                    attempt=attempt + 1,
                    sketch=current_sketch is not None,
                    results=results,
                ),
            )
            gallery.append(
                (str(path), f'{label}Attempt {attempt + 1} · match {score:.0%}' + (' ✓' if passed else ''))
            )
            if best is None or score > best['score']:
                best = dict(
                    score=score,
                    index=len(gallery) - 1,
                    details=details,
                    attempt=attempt + 1,
                    prompt=this_prompt,
                    people=people,
                    scene=current,
                    path=path,
                    report=checker.report(results, score),
                )
            if passed:
                outcome = f'Attempt {attempt + 1} matches every check.'
            elif last or engine.cancelled.is_set():
                outcome = (
                    f'No attempt matched every check; showing the best, attempt {best["attempt"]} '
                    f'({best["score"]:.0%}).'
                )
            else:
                missed = '; '.join(r['question'] for r in results if not r['ok'])
                outcome = (
                    f'Attempt {attempt + 1}: match {score:.0%}. Missed: {missed}. Trying again with a '
                    'revised prompt'
                    + (' and a layout sketch' if next_sketch is not current_sketch else '')
                    + '...'
                )
            report = (
                f'{label}{best["report"]}\n\nBest so far: attempt {best["attempt"]}. Prompt used:\n'
                f'{best["prompt"]}'
            )
            yield (
                dict(value=gallery, selected_index=best['index']),
                f'{label}{outcome}\n' + describe(best['details']),
                recent_images(),
                understood,
                report,
            )
            if passed or last or engine.cancelled.is_set():
                chosen.append(
                    dict(
                        path=best['path'],
                        prompt=best['prompt'],
                        people=best['people'],
                        scene=best['scene'],
                        seed=best['details']['seed'],
                        label=label,
                    )
                )
                break
            current, current_sketch = next_prompt, next_sketch
        if engine.cancelled.is_set():
            break
    for item in chosen if combine else []:
        if engine.cancelled.is_set():
            break
        label = item['label']
        try:
            with lock:
                progress(0, desc=label + 'Adding real-photo texture with RealVisXL...')
                # The scene without the list of people: their heritages early in RealVisXL's 77-token
                # prompt pull every face toward them.
                path, details = engine.generate(
                    item['scene'],
                    item['seed'],
                    DEFAULT_STEPS['realistic'],
                    status=lambda text: print(text, flush=True),
                    model='realistic',
                    size=size,
                    guidance=float(guidance),
                    negative_prompt=negative_prompt,
                    detail=detail,
                    detail_strength=float(detail_strength),
                    request=request,
                    repair=bool(repair_on),
                    repair_strength=float(repair_strength),
                    style=photo_style,
                    finish=photo_finish,
                    people=item['people'],
                    scene=item['scene'],
                    references=bool(references),
                    source=item['path'],
                    realism=float(realism),
                    on_step=lambda step, total: progress(
                        step / total, desc=f'{label}Texture {step} of {total}'
                    ),
                )
        except Cancelled:
            break
        except (ValueError, RuntimeError) as exc:
            raise ValueError(str(exc)) from exc
        gallery.append((str(path), f'{label}Final · RealVisXL texture'))
        yield (
            dict(value=gallery, selected_index=len(gallery) - 1),
            f'{label}Finished with RealVisXL.\n' + describe(details),
            recent_images(),
            understood,
            report,
        )
    if engine.cancelled.is_set():
        yield (
            dict(value=gallery, selected_index=len(gallery) - 1 if gallery else None),
            'Stopped. Finished images are saved.' if gallery else 'Stopped.',
            recent_images(),
            understood,
            report,
        )


def sketch_layout(prompt, size, progress=Progress()):
    """Plan the objects in the description with the assistant and draw them as a sketch."""
    if not prompt.strip():
        raise ValueError('Describe the image first, including where each object goes.')
    if not assistant.available():
        raise ValueError(
            'Sketching from a description needs the prompt assistant: run Download prompt '
            'assistant.bat, or draw the shapes yourself.'
        )
    progress(0, desc='Planning the layout...')
    try:
        with lock:
            plan = assistant.plan_layout(prompt, status=lambda text: print(text, flush=True))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    width, height = SIZES[size]
    objects = [obj for obj in plan['objects'] if isinstance(obj, dict)]
    names = ', '.join(
        str(obj.get('name') or f'{obj.get("color", "")} {obj.get("shape", "")}').strip() for obj in objects
    )
    return (
        editor_value(layout.draw(plan, width, height)),
        f'Sketched {len(objects)} objects: {names}. Check the sketch, fix it with the brush if '
        'needed, then click Generate image.',
    )


def editor_parts(value):
    """The uploaded photo and a mask of everything painted on it."""
    if not value or value.get('background') is None:
        return None, None
    mask = None
    for layer in value.get('layers') or []:
        if layer is None:
            continue
        alpha = layer.getchannel('A') if layer.mode == 'RGBA' else layer.convert('L')
        mask = alpha if mask is None else ImageChops.lighter(mask, alpha)
    return value['background'], mask


def editor_value(image):
    return {'background': image, 'layers': [], 'composite': image}


def edit_photo(editor, instruction, seed_text, steps, guidance, quality, smart, progress=Progress()):
    image, mask = editor_parts(editor)
    if image is None:
        raise ValueError('Add a photo first: drag it into the photo box, paste it, or use the webcam.')
    seed = parse_seed(seed_text)
    engine.cancelled.clear()
    request = instruction
    instruction, note = smart_prompt(request, 'edit', smart, image=image, progress=progress)
    understood = understood_text(request, instruction, note)
    try:
        with lock:
            progress(0, desc='Loading the editing model (the first edit takes a minute or two)...')
            path, details = engine.edit(
                image,
                instruction,
                seed,
                int(steps),
                float(guidance),
                mask=mask,
                quality=quality,
                status=lambda text: print(text, flush=True),
                request=request,
                on_step=lambda step, total: progress(step / total, desc=f'Editing {step} of {total}'),
            )
    except Cancelled:
        return dict(), dict(), 'Stopped.', recent_images(), dict(), understood
    except (ValueError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc
    result = Image.open(path)
    area = ' · Painted area only' if details['painted_area'] else ''
    status = (
        f'{details["width"]} × {details["height"]} · {details["total_seconds"]}s · Seed {details["seed"]}'
        f'{area} · Saved'
    )
    return str(path), (image.convert('RGB'), result), status, recent_images(), str(path), understood


def stop():
    engine.cancelled.set()
    return 'Stopping after the current step...'


def lora_ready():
    return (REALISM_LORA / 'pytorch_lora_weights.safetensors').exists()


def closest_size(width, height):
    """The image format whose shape is nearest the requested area's."""
    import math

    return min(SIZES, key=lambda name: abs(math.log((SIZES[name][0] / SIZES[name][1]) / (width / height))))


def with_alpha(image, mask):
    """RGBA: opaque inside the (softened) selection, transparent outside it."""
    image = image.convert('RGBA')
    if mask is not None:
        image.putalpha(soft_mask(mask.resize(image.size)))
    return image


def editor_create(request, progress):
    """Bridge job: a new picture for the editor's selection (or whole canvas)."""
    width, height = int(request['width']), int(request['height'])
    mask = bridge.decode_png(request.get('mask'))
    model = request.get('model', 'accurate')
    if model not in MODELS:
        raise ValueError('Unknown model.')
    out = None
    for out in generate(
        request['prompt'],
        str(request.get('seed') or ''),
        model,
        closest_size(width, height),
        DEFAULT_STEPS[model],
        5,
        DEFAULT_NEGATIVE,
        'Off' if model == 'accurate' else DETAIL_DEFAULT,
        DETAIL_STRENGTH,
        1,
        request.get('smart', True),
        None,
        LAYOUT_STRENGTH,
        request.get('vary', True),
        request.get('check', True),
        int(request.get('attempts', 4)),
        request.get('repair', True),
        REPAIR_STRENGTH,
        request.get('style', style.DEFAULT_STYLE),
        request.get('finish', finish.DEFAULT_FINISH),
        request.get('combine', True),
        request.get('references', True),
        request.get('realism', REALISM_DEFAULT),
        progress=progress,
    ):
        pass
    gallery = out[0].get('value') if out else None
    if not gallery:
        raise RuntimeError('Stopped.' if engine.cancelled.is_set() else 'No image was made.')
    path = gallery[out[0].get('selected_index') or 0][0]
    picture = ImageOps.fit(Image.open(path).convert('RGB'), (width, height), Image.LANCZOS)
    return with_alpha(picture, mask), out[1].splitlines()[0]


def editor_edit(request, progress):
    """Bridge job: change the editor's picture by instruction, only inside the selection if there is one."""
    image = bridge.decode_png(request['image']).convert('RGB')
    mask = bridge.decode_png(request.get('mask'))
    editor = {'background': image, 'layers': [mask.convert('L')] if mask else [], 'composite': image}
    out = edit_photo(
        editor,
        request['prompt'],
        str(request.get('seed') or ''),
        EDIT_STEPS,
        EDIT_GUIDANCE,
        next(iter(EDIT_QUALITY)),
        request.get('smart', True),
        progress=progress,
    )
    if not isinstance(out[0], str):
        raise RuntimeError('Stopped.')
    result = Image.open(out[0]).convert('RGB').resize(image.size, Image.LANCZOS)
    return with_alpha(result, mask), out[2]


def editor_plan(request, progress):
    """Bridge job: the steps for a prompt typed in Krita or in the Krita tab (see agent.py)."""
    text = (request.get('prompt') or '').strip()
    if not text:
        raise ValueError('Type what you want first.')
    state = request.get('state')
    # What the person taught (memory.py): their words, corrections, "too much" / "more".
    intent = memory.understand(text, state)
    text = intent.text
    steps = agent.quick_plan(text) if intent.result is None else intent.result['steps']
    how = 'rules'
    notes = []
    preview = bridge.decode_png(request.get('image'))
    preview = preview.convert('RGB') if preview else None
    # Light and color grades are planned by the editing brain when it is installed: it places
    # the look on the photo (where the sun and horizon are) and checks the result.
    if (
        intent.result is None
        and steps
        and any(step['op'] == 'grade' for step in steps)
        and preview is not None
        and brain.available()
    ):
        steps = None
    if not steps:
        progress(0, desc='Understanding your request...')

        def status(desc):
            progress(0, desc=desc)

        with lock:
            if preview is not None and brain.available() and not agent.is_question(text):
                # Parts the rules understand exactly ("make the buildings pastel pink") are planned
                # by them; the brain plans the rest. (Measured: given the whole request, the brain
                # sometimes dropped the recolor while planning the grade.)
                known, rest = agent.partial_plan(text)
                if rest:
                    steps, notes = retoucher.plan(rest, preview, state, status=status, known=known, whole=text)
                else:
                    steps = known
                how = 'brain'
            if not steps:
                steps, how = agent.plan(text, state, preview, status=status)
    steps, how, notes = memory.finish(intent, steps, how, notes)
    return dict(
        steps=steps,
        how=how,
        notes=notes,
        labels=[agent.summary(step) for step in steps],
        message=f'{len(steps)} step' + ('s' if len(steps) != 1 else ''),
    )


def editor_grade(request, progress):
    """Bridge job: grade layers rendered on the full picture, for Krita to add as a group of
    layers with masks (see grading.py and retoucher.py)."""
    image = flat(bridge.decode_png(request['image']))
    layers = request.get('layers') or []
    masks = {}

    def find(target):
        key = target.lower().strip()
        if key not in masks:
            progress(0.3, desc=f'Finding {target}...')
            masks[key] = segment.select(image, target, status=lambda desc: progress(0.3, desc=desc))[0]
        return masks[key]

    progress(0.1, desc='Grading...')
    with lock:
        rendered, _ = grading.render_layers(image, layers, find)
    return dict(
        layers=[dict(name=name, image=bridge.encode_png(picture),
                     mask=bridge.encode_png(mask) if mask is not None else None, opacity=opacity)
                for name, picture, mask, opacity in rendered],
        message=f'{len(rendered)} grade layer' + ('s' if len(rendered) != 1 else ''),
    )


def editor_segment(request, progress):
    """Bridge job: a selection mask for something described in words."""
    image = bridge.decode_png(request['image']).convert('RGB')
    target = (request.get('target') or '').strip()
    if not target:
        raise ValueError('Say what to select.')
    if not assistant.available():
        raise ValueError(
            'Selecting by description needs the prompt assistant: run Download prompt assistant.bat.'
        )
    with lock:
        mask, note = segment.select(image, target, status=lambda desc: progress(0.5, desc=desc))
    return dict(mask=mask, message=note)


def flat(image):
    """RGB on white: Krita's picture may have transparent areas."""
    if image.mode in ('RGBA', 'LA', 'P'):
        image = image.convert('RGBA')
        back = Image.new('RGB', image.size, 'white')
        back.paste(image, mask=image.getchannel('A'))
        return back
    return image.convert('RGB')


def caption(image):
    """One line describing the picture, for redraws that need a prompt."""
    if not assistant.available():
        return 'a photograph'
    with assistant.Session() as session:
        return (
            assistant.clean_create(
                session.ask(
                    None,
                    [],
                    'Describe this photo for an image generator in one line of comma-separated phrases: '
                    'the subject, the setting and the light. At most 40 words.',
                    image=image,
                    max_new_tokens=90,
                    image_size=768,
                    prefix='',
                )
            )
            or 'a photograph'
        )


def editor_enhance(request, progress):
    """Bridge job: real-photo detail and repaired faces and hands (RealVisXL redraws the
    picture lightly, like Finish with RealVisXL), optionally enlarged 1.5x or 2x."""
    image = flat(bridge.decode_png(request['image']))
    scale = float(request.get('scale') or 1.0)
    detail = '2× size' if scale >= 1.75 else '1.5× size' if scale >= 1.25 else 'Off'
    engine.cancelled.clear()
    source = WORK / 'studio-cache' / 'enhance-source.png'
    source.parent.mkdir(parents=True, exist_ok=True)
    image.save(source)
    with lock:
        progress(0, desc='Describing the picture...')
        prompt = (request.get('prompt') or '').strip() or caption(image)
        progress(0, desc='Loading RealVisXL...')
        try:
            path, details = engine.generate(
                prompt,
                None,
                DEFAULT_STEPS['realistic'],
                status=lambda text: print(text, flush=True),
                model='realistic',
                detail=detail,
                detail_strength=0.3,
                repair=True,
                references=False,
                style=style.DEFAULT_STYLE,
                finish='Off',
                source=str(source),
                realism=REALISM_DEFAULT,
                request=f'Enhance: {prompt}',
                on_step=lambda step, total: progress(step / total, desc=f'Adding detail {step} of {total}'),
            )
        except Cancelled:
            raise RuntimeError('Stopped.')
    result = Image.open(path).convert('RGB')
    return dict(
        image=result,
        width=result.width,
        height=result.height,
        message=f'Enhanced at {result.width} × {result.height} in {details["total_seconds"]}s.',
    )


def editor_faces(request, progress):
    """Bridge job: redraw each face and hand enlarged (no reference faces, so people keep
    who they are)."""
    image = flat(bridge.decode_png(request['image']))
    engine.cancelled.clear()
    with lock:
        progress(0, desc='Describing the picture...')
        scene = caption(image)
        progress(0.1, desc='Loading RealVisXL...')
        try:
            engine.load('realistic', status=lambda text: print(text, flush=True))
            engine.set_realism(REALISM_DEFAULT)
            result, note = engine.repair_pass(
                image,
                scene,
                'realistic',
                secrets.randbelow(2**31),
                DEFAULT_STEPS['realistic'],
                5.0,
                DEFAULT_NEGATIVE,
                REPAIR_STRENGTH,
                lambda text: progress(0.5, desc=text),
                references=False,
            )
        except Cancelled:
            raise RuntimeError('Stopped.')
    items = note.get('items', []) if isinstance(note, dict) else []
    return dict(
        image=result,
        message=f'Repaired {len(items)} faces and hands.' if items else 'No faces or hands found.',
    )


def save_from_editor(image, info):
    """Save a picture sent from Krita into the Library, with what was done to it."""
    from image_studio.core.engine import new_output, save

    history = [str(item) for item in info.get('history') or []][-30:]
    name = str(info.get('name') or 'Krita picture')
    output = new_output(0)
    prompt = ' · '.join(history) if history else name
    details = dict(
        prompt=prompt,
        request=prompt,
        mode='krita',
        name=name,
        history=history,
        seed=0,
        steps=0,
        width=image.width,
        height=image.height,
        base_width=image.width,
        base_height=image.height,
        model='Krita',
        guidance=0,
        negative_prompt='',
        detail_pass=None,
        total_seconds=0,
    )
    save(image if image.getextrema()[3][0] < 255 else image.convert('RGB'), output, details, 'Krita')
    search.index_new_images()
    return output


def krita_running():
    import psutil

    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() == 'krita.exe':
            return True
    return False


def launch_krita(path=None):
    """Start Krita with the AI panel installed (and open `path`)."""
    import subprocess
    from image_studio.integrations import install_krita_plugin

    if not KRITA.exists():
        raise ValueError('Krita is not installed in the work folder.')
    # Krita rewrites its settings when it exits, so the panel is installed while it is closed.
    install_krita_plugin.main()
    subprocess.Popen(
        [str(KRITA)] + ([str(path)] if path else []),
        cwd=str(KRITA.parent),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def open_in_krita(path):
    if not path:
        raise ValueError('Choose a picture first.')
    path = str(path)
    if bridge.link.connected:
        bridge.link.send('open', path=path)
        return f'Opening {os.path.basename(path)} in Krita.'
    if krita_running():
        raise ValueError(
            'Krita is open but its AI panel is not connected. Close Krita and click Open in Krita again.'
        )
    launch_krita(path)
    return f'Starting Krita with {os.path.basename(path)}. It takes about 20 seconds.'


def start_krita():
    if bridge.link.connected:
        bridge.link.send('raise')
        return 'Krita is open.'
    if krita_running():
        raise ValueError(
            'Krita is open but its AI panel is not connected. Close Krita and click Open Krita again.'
        )
    launch_krita()
    return 'Starting Krita. It takes about 20 seconds.'


def run_in_krita(text):
    text = (text or '').strip()
    if not text:
        raise ValueError('Describe the edit first.')
    if not bridge.link.connected:
        raise ValueError('Krita is not connected. Click Open Krita.')
    bridge.link.send('prompt', text=text)
    return 'Sent to Krita.'


def krita_command(kind, done):
    def send():
        if not bridge.link.connected:
            raise ValueError('Krita is not connected. Click Open Krita.')
        if kind == 'stop':
            engine.cancelled.set()
        bridge.link.send(kind)
        return done

    return send


LAYER_ICONS = {
    'paintlayer': 'brush',
    'filterlayer': 'adjust',
    'vectorlayer': 'type',
    'grouplayer': 'folder',
    'filllayer': 'drop',
    'transparencymask': 'mask',
    'filtermask': 'adjust',
    'selectionmask': 'mask',
}
