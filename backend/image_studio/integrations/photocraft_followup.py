"""Follow-up requests revise the last edit instead of stacking a new one on top of it.

A retoucher asked “too much” turns the last adjustment down; asked “less warm” right after
“make it warmer”, they lower that warming, they do not add a cooling layer above it. The studio
does the same with the request that made the photo on screen:

- “too much”, “tone it down”, “subtler” rebuild it one strength step lower; “more”, “not
  enough”, “push it” one step higher (the phrases the Krita assistant already reads, memory.py);
- “without the vignette”, “drop the grain” rebuild it without that part;
- a new request whose amount edit (light, warmth, colour, punch, haze) is one the last request
  made, on the same target, changes that edit: the same way is a step stronger, the other way a
  step weaker, or gone when it was already subtle. Everything else in the new request is added.

The revised plan is built with the boxes the last request found (no model is asked to find them
again) and runs on the photo as it was before the last request, replacing its result, so the
history keeps one step per request and nothing is stacked.
"""

import json
import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.services.memory import STRONGER, WEAKER

WITHOUT = re.compile(
    r'^(?:(?:but|and|ok|okay|now)\s+)?(?:without|no more|lose|drop|skip|remove|take (?:out|off|away))\s+'
    r'(?:the\s+|that\s+)?(?P<what>[\w\s-]{2,40}?)(?:\s+please)?[.!]*$', re.IGNORECASE)
# Words for a part of the last request, beyond its pipeline's own name.
PART_WORDS = {
    'add_text': r'title|text|words|caption|heading',
    'vignette': r'vignette|dark(?:er)? (?:edges|corners)',
    'develop_vignette': r'vignette|dark(?:er)? (?:edges|corners)',
    'grain': r'grain|noise',
    'temperature': r'warm\w*|cool\w*|colou?r temperature',
    'graduated_filter': r'graduated|grad(?:ient)? filter|sky',
    'develop_sky': r'graduated|grad(?:ient)? filter|sky',
    'develop_sharpen': r'sharpen\w*',
    'sharpen': r'sharpen\w*',
    'blur_background': r'blur\w*|bokeh',
}


def last_request(data, folder):
    """(the plan that made the photo on screen, the revision it was applied to), or None when the
    photo on screen did not come from a plan (the original, an undo past it, a manual sync). A
    long request run stage by stage made several revisions; all of them are its result."""
    cursor = data['cursor']
    if cursor == 0:
        return None
    plan_id = data['history'][cursor].get('plan')
    if not plan_id or not re.fullmatch('[a-f0-9]{32}', plan_id):
        return None
    try:
        plan = json.loads((folder / f'plan-{plan_id}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not plan.get('edits') or base_index(data, plan.get('base') or plan.get('revision'), plan_id) is None:
        return None
    return plan, plan.get('base') or plan.get('revision')


def base_index(data, base, plan_id):
    """Where `base` sits in the history, when every revision after it up to the one on screen was
    made by the plan `plan_id`; else None."""
    ids = [revision['id'] for revision in data['history'][:data['cursor']]]
    if base not in ids:
        return None
    index = ids.index(base)
    made = data['history'][index + 1:data['cursor'] + 1]
    return index if made and all(revision.get('plan') == plan_id for revision in made) else None


def _step(strength, way):
    levels = lang.STRENGTHS
    index = levels.index(strength) if strength in levels else 1
    moved = index + way
    return levels[moved] if 0 <= moved < len(levels) else None


def _adjustable(edit):
    """An edit whose strength changes what it does: not a written number, a crop, a title or a
    removal. A measured develop step applies a share of its measured correction by strength."""
    from image_studio.pipelines import get

    return bool(get(edit['action'])) and edit['value'] is None and \
        edit['action'] not in ('add_text', 'crop_aspect', 'resize', 'rotate', 'flip', 'remove_object',
                               'remove_background', 'layer_delete', 'layer_rename', 'develop_level', 'straighten')


def _clean(edits):
    return [{key: value for key, value in edit.items() if key != 'explain'} for edit in edits]


def revise(prompt, plan):
    """(the last request's edits as a phrase on its own changes them, notes, whether anything
    changed), or None when the request is not such a phrase."""
    words = ' '.join(prompt.split())
    edits = _clean(plan['edits'])
    way = -1 if WEAKER.match(words) else 1 if STRONGER.match(words) else 0
    if way:
        changed, notes = [], []
        for edit in edits:
            if _adjustable(edit):
                moved = _step(edit['strength'], way)
                if moved:
                    changed.append(edit['quote'])
                    edit['strength'] = moved
        if not changed:
            limit = 'subtlest' if way < 0 else 'strongest'
            return edits, [f'Your last edit is already at its {limit} setting, so nothing changed. Undo takes it '
                           'back entirely.'], False
        notes.append(f'{"Turned down" if way < 0 else "Turned up"} your last edit one step: '
                     + '; '.join(f'“{quote}”' for quote in changed[:4]) + '.')
        return edits, notes, True
    found = WITHOUT.match(words)
    if found:
        what = found.group('what').strip().lower()
        kept = [edit for edit in edits if not _names(edit, what)]
        if not kept:
            return edits, ['That was all of your last edit, so Undo takes it back.'], False
        if len(kept) < len(edits):
            dropped = [edit['quote'] for edit in edits if _names(edit, what)]
            return kept, ['Took out of your last edit: ' + '; '.join(f'“{q}”' for q in dropped[:4]) + '.'], True
    return None


def _names(edit, what):
    pattern = PART_WORDS.get(edit['action'])
    if pattern and re.search(rf'\b(?:{pattern})\b', what):
        return True
    action = edit['action'].replace('_', ' ')
    return what in action or what in edit['quote'].lower()


def _amount(action):
    return any(action in actions for actions in lang.AXES.values())


def merge(new_edits, plan):
    """New edits joined to the last request: an amount edit the last request also made on the same
    target changes that edit; every other new edit is added. (edits, notes) or None when no new
    edit touched the last request."""
    edits = _clean(plan['edits'])
    notes, added, touched = [], [], False
    for new in new_edits:
        match = next((index for index, old in enumerate(edits)
                      if _amount(new['action']) and old['action'] == new['action'] and old['value'] is None
                      and new['value'] is None and old['target'] == new['target']
                      and old.get('object', '') == new.get('object', '')
                      and old['direction'] in ('increase', 'decrease') and new['direction'] in ('increase', 'decrease')),
                     None)
        if match is None:
            added.append(new)
            continue
        touched = True
        old = edits[match]
        way = 1 if new['direction'] == old['direction'] else -1
        moved = _step(old['strength'], way)
        if moved:
            notes.append(f'“{new["quote"]}” changed your last edit “{old["quote"]}” ({old["strength"]} → {moved}) '
                         'instead of adding another layer.')
            old['strength'] = moved
        elif way < 0:
            notes.append(f'“{new["quote"]}” took out your last edit “{old["quote"]}”, which was already subtle.')
            edits[match] = None
        else:
            notes.append(f'“{old["quote"]}” is already at its strongest.')
    if not touched:
        return None
    return [edit for edit in edits if edit is not None] + added, notes
