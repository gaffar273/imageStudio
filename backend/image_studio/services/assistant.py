"""Prompt assistant: turns casual requests into clear prompts, like a chat assistant
does before calling an image model. Uses Qwen3-VL-2B, which also looks at the photo
when editing. It is loaded onto the GPU only for the few seconds it runs."""

import gc
import re
import threading
import time
from image_studio.core.catalog import ASSISTANT

EDIT_SYSTEM = """You help people edit photos with an AI image editor (FLUX Kontext). You see the photo and the person's request, which may be casual, vague or misspelled. Work out what they want and write ONE clear editing instruction in English.
Rules:
- Say exactly what changes, concretely: which person or object, and the new clothing, colors, materials, setting, style or expression.
- Then say what must stay the same, naming the important things you see: the person's face and identity, hairstyle, pose, background, lighting and camera angle. Leave out anything the request wants changed.
- Refer to people by what you see ("the woman with curly dark hair"), not only by pronoun.
- For requests about appearance or body shape, describe a natural, realistic, tasteful result. If loose clothing hides the shape, ask for a better-fitting version of the same kind of garment instead of keeping the clothing unchanged. People stay fully clothed; never make the image sexual or explicit.
- Under 70 words. Output only the instruction, with no preamble or quotes."""

CREATE_SYSTEM = """You turn short or misspelled ideas into prompts for a photorealistic image generator. Keep the person's intent and add concrete visual detail: the subject (for people, a realistic age, build and well-fitting clothing), what is happening, the setting and the light, the way an ordinary photo would show them. Prefer everyday, true-to-life details over glamorous ones, and do not add words like cinematic, stunning, perfect, flawless, professional, 8k or masterpiece unless the request uses them. Keep people clothed. Never drop or change what the request specifies: keep every count ("exactly three"), every color and material of each object, every position (left, center, right, front, behind) and the lighting direction. Give each object its own phrase with its color and position. Answer with one line of comma-separated phrases, at most 60 words."""

# Small models follow examples more reliably than lists of rules.
EDIT_EXAMPLES = [
    (
        'make him look more musculer',
        'Make the man with short black hair look more muscular, with broader shoulders and defined arms, and change '
        'his loose grey hoodie to a fitted grey t-shirt that shows his build. Keep his face, hairstyle, pose, '
        'background and lighting the same.',
    ),
    (
        'chnge bg to snow',
        'Change the background to a snowy mountain landscape with soft overcast daylight. Keep the person, their '
        'face, hairstyle, clothing and pose exactly the same.',
    ),
]
CREATE_EXAMPLES = [
    (
        'woman reading in park',
        'a 30-year-old woman with shoulder-length brown hair reading a paperback on a park bench, fitted green '
        'cardigan and jeans, dappled afternoon sunlight through oak trees, people walking on the path behind her, '
        'natural skin texture, candid moment',
    ),
    (
        'red sports car at nite',
        'a red sports car parked on a wet city street at night, shop signs reflected on the asphalt, light rain, '
        'street lamps, other parked cars, photo taken from the pavement',
    ),
    (
        'excatly 2 green apples on the left and a white mug on the rigth, side light',
        'exactly two green apples on the left side, one white ceramic mug on the right side, two apples and one mug '
        'on a wooden table, soft side lighting, plain beige wall, everyday photo',
    ),
]

# Words that pin down counts, positions and light direction. If the request has one
# and the rewrite lost it, the rewrite changed the picture, not just the wording.
SPECIFIC_WORDS = [
    ('exactly',),
    ('two', '2'),
    ('three', '3'),
    ('four', '4'),
    ('five', '5'),
    ('six', '6'),
    ('left',),
    ('right',),
    ('center', 'centre', 'middle'),
    ('top',),
    ('bottom',),
    ('behind',),
    ('front',),
    ('above',),
    ('below', 'under'),
    ('side lighting', 'side light'),
]


def available():
    return (ASSISTANT['folder'] / 'download-complete.json').exists()


def lost_specifics(request, prompt):
    """Counts, positions or light directions in the request that the prompt left out."""

    def has(text, word):
        return re.search(rf'\b{re.escape(word)}\b', text.lower()) is not None

    return [
        group[0]
        for group in SPECIFIC_WORDS
        if any(has(request, word) for word in group) and not any(has(prompt, word) for word in group)
    ]


def clean_create(text):
    """One line of distinct phrases, without negatives such as "no text" (the
    generator would draw them), trimmed to the length SDXL actually reads."""
    phrases, seen = [], set()
    for phrase in clean(text).split(','):
        phrase = phrase.strip()
        key = phrase.lower()
        if not phrase or key in seen or re.match(r'(no|non|not|without)\b', key):
            continue
        seen.add(key)
        phrases.append(phrase)
    words = ', '.join(phrases).split()
    return ' '.join(words[:60]).rstrip(',')


def clean(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.S)
    text = re.sub(
        r'^\s*(instruction|prompt|edited prompt|rewritten prompt)\s*:\s*', '', text.strip(), flags=re.I
    )
    return ' '.join(text.split()).strip('"“”\' ')[:1000]


# Language models kept on the GPU between editor commands (keep=True), so a run of
# prompt edits loads them once. One at a time (the vision assistant here, or the editing
# planner in agent.py): holding a different kind frees the kept one first. Freed by
# release(): before any image model loads, by any use without keep, and after
# IDLE_SECONDS unused.
_kept = None
_kept_lock = threading.RLock()
IDLE_SECONDS = 180
# Called before a language model loads; app.py frees the editing model here, whose 10 GB
# in RAM and GPU leftovers otherwise push the 16 GB laptop into paging.
before_load = []


def release():
    """Free the kept model's GPU memory (no-op when none is kept)."""
    global _kept
    with _kept_lock:
        if _kept is None:
            return
        close = _kept.get('close')
        _kept = None
        if close is not None:  # a model in another process (the editing brain, brain.py)
            close()
        import torch

        gc.collect()
        torch.cuda.empty_cache()


def kept_kind():
    """The kind of model kept on the GPU ('brain', 'vision', 'planner') or None."""
    with _kept_lock:
        return _kept['kind'] if _kept is not None else None


def _release_when_idle():
    while True:
        time.sleep(15)
        with _kept_lock:
            if _kept is not None and time.monotonic() - _kept['used'] > IDLE_SECONDS:
                release()


threading.Thread(target=_release_when_idle, daemon=True).start()


class Resident:
    """Context manager giving the parts of a model of `kind`, made by `loader()` (a dict)
    unless that kind is already kept."""

    def __init__(self, kind, loader, keep=False):
        self.kind, self.loader, self.keep = kind, loader, keep

    def __enter__(self):
        global _kept
        _kept_lock.acquire()
        try:
            if _kept is not None and _kept['kind'] != self.kind:
                release()
            if _kept is None:
                for hook in before_load:
                    hook()
                _kept = dict(self.loader(), kind=self.kind, used=time.monotonic())
        except BaseException:
            _kept_lock.release()
            raise
        return _kept

    def __exit__(self, *exc):
        try:
            if self.keep and _kept is not None:
                _kept['used'] = time.monotonic()
            else:
                release()
        finally:
            _kept_lock.release()


def _load_vision():
    import torch
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    folder = ASSISTANT['folder']
    return dict(
        processor=AutoProcessor.from_pretrained(folder),
        model=Qwen3VLForConditionalGeneration.from_pretrained(
            folder, dtype=torch.bfloat16, device_map='cuda'
        ),
    )


class Session:
    """The assistant loaded onto the GPU once for several questions; freed on exit
    unless `keep`, in which case the next Session reuses it."""

    def __init__(self, keep=False):
        self.resident = Resident('vision', _load_vision, keep)

    def __enter__(self):
        parts = self.resident.__enter__()
        self.processor, self.model = parts['processor'], parts['model']
        return self

    def __exit__(self, *exc):
        del self.model
        self.resident.__exit__(*exc)

    def inputs(self, system, examples, request, image=None, image_size=768, prefix='Request: '):
        content = []
        if image is not None:
            preview = image.convert('RGB')
            preview.thumbnail((image_size, image_size))
            content.append({'type': 'image', 'image': preview})
        content.append({'type': 'text', 'text': f'{prefix}{request}'})

        def text(value):
            return [{'type': 'text', 'text': value}]

        messages = [{'role': 'system', 'content': text(system)}] if system else []
        for idea, answer in examples:
            messages += [
                {'role': 'user', 'content': text(f'{prefix}{idea}')},
                {'role': 'assistant', 'content': text(answer)},
            ]
        messages.append({'role': 'user', 'content': content})
        return self.processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors='pt'
        ).to('cuda')

    def ask(
        self,
        system,
        examples,
        request,
        image=None,
        max_new_tokens=160,
        repetition_penalty=1.15,
        image_size=768,
        prefix='Request: ',
    ):
        """One answer, given a system prompt and example exchanges."""
        import torch

        inputs = self.inputs(system, examples, request, image, image_size, prefix)
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                repetition_penalty=repetition_penalty,
                temperature=None,
                top_p=None,
                top_k=None,
            )
        return self.processor.batch_decode(
            output[:, inputs['input_ids'].shape[1] :], skip_special_tokens=True
        )[0]

    def yes_probability(self, question, image, image_size=1024):
        """How sure the model is that the answer is yes (0 to 1), read from its first-token
        scores rather than its text, so an unsure "yes" counts for less than a clear one."""
        import torch

        inputs = self.inputs(None, [], f'{question} Answer yes or no.', image, image_size, prefix='')
        tokenizer = self.processor.tokenizer
        yes = [tokenizer.encode(word, add_special_tokens=False)[0] for word in ('Yes', 'yes')]
        no = [tokenizer.encode(word, add_special_tokens=False)[0] for word in ('No', 'no')]
        with torch.inference_mode():
            logits = self.model(**inputs).logits[0, -1].float()
        scores = torch.stack([torch.logsumexp(logits[yes], 0), torch.logsumexp(logits[no], 0)])
        return torch.softmax(scores, 0)[0].item()


def ask(system, examples, request, image=None, max_new_tokens=160, repetition_penalty=1.15):
    """One answer from the assistant, loaded just for this question."""
    with Session() as session:
        return session.ask(system, examples, request, image, max_new_tokens, repetition_penalty)


def rewrite(request, mode, image=None, status=print):
    """Return a clear prompt for `mode` ('edit' or 'create')."""
    status('Understanding your request...')
    if mode == 'edit':
        return clean(ask(EDIT_SYSTEM, EDIT_EXAMPLES, request, image)) or request
    return clean_create(ask(CREATE_SYSTEM, CREATE_EXAMPLES, request)) or request


LAYOUT_SYSTEM = """You plan where objects go in a picture. List every separate object the request mentions, once per copy (three apples = three entries). For each give its name, shape (one of: cube, box, sphere, pyramid, cone, cylinder, bottle, person, other), a simple color name, and its box in percent of the picture: x and y are the top-left corner, w and h the size, all 0 to 100. Put objects exactly where the request says; "left to right" means increasing x. Leave equal gaps unless told otherwise, and stand objects on a shared ground line when they sit on a surface. Also give the background color. Do not list the background, floor or table as objects. Answer only with JSON."""

LAYOUT_EXAMPLES = [
    (
        'two green apples left of a white mug on a wooden table',
        '{"background": "beige", "objects": ['
        '{"name": "green apple", "shape": "sphere", "color": "green", "x": 8, "y": 52, "w": 20, "h": 20}, '
        '{"name": "green apple", "shape": "sphere", "color": "green", "x": 32, "y": 52, "w": 20, "h": 20}, '
        '{"name": "white mug", "shape": "cylinder", "color": "white", "x": 62, "y": 40, "w": 26, "h": 32}]}',
    ),
]


def plan_layout(request, status=print, session=None):
    """Objects with shapes, colors and boxes for a layout sketch, read from the request."""
    import json

    status('Planning the layout...')
    if session is None:
        answer = ask(LAYOUT_SYSTEM, LAYOUT_EXAMPLES, request, max_new_tokens=600, repetition_penalty=1.0)
    else:
        answer = session.ask(
            LAYOUT_SYSTEM, LAYOUT_EXAMPLES, request, max_new_tokens=600, repetition_penalty=1.0
        )
    answer = clean(answer)
    match = re.search(r'\{.*\}', answer, flags=re.S)
    try:
        plan = json.loads(match.group(0)) if match else None
    except ValueError:
        plan = None
    if not isinstance(plan, dict) or not isinstance(plan.get('objects'), list) or not plan['objects']:
        raise ValueError(
            'The assistant could not plan this layout. Draw the shapes yourself, or reword the request.'
        )
    return plan
