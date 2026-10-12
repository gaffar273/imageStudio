"""AI content (FLUX.1 Kontext): new content painted on its own masked layer, kept only where
it changed, and a last-resort pipeline for registry features the catalog does not name."""

import re

from image_studio.pipelines.core import procedure


@procedure('generate', 'Paint new content with AI', 'ai', 'ai',
           'new content painted by AI as its own layer: add an object or person, replace the sky with a new one, '
           'change clothing or materials (target says where)', ai=True, area_safe=True,
           examples=('add a small white sailboat', 'replace the sky with a sunset'))
def generate(b, index, edit):
    """New content painted by AI as its own layer, masked to the target."""
    if not b.ai:
        b.blocking.append(f'“{edit["quote"]}” needs new content painted by AI. Install AI content editing '
                          '(Download editing model.bat) for this part.')
        return
    params = {'instruction': edit['quote'][:400] + '. Keep everything else exactly the same.',
              'label': f'AI: {edit["quote"]}'[:80]}
    adding = re.search(r'\b(add|put|place|insert)\b', edit['quote'], re.IGNORECASE)
    if edit['target'] in ('object', 'main subject') and not (adding and not edit['object']):
        key, boxes = b.target_boxes(edit)
        if not boxes:
            b.blocking.append(f'Could not find {key or "where to paint"} in the picture.')
            return
        params['boxes'] = boxes
        b.regions.append({'requirement': index, 'label': key, 'boxes': b.normalized(boxes)})
        if adding:
            # New things go next to what was named; the box only says where to look.
            params.pop('boxes')
        elif not b.selection(index, edit):
            return
    elif edit['target'] not in ('whole image', 'layer', 'object', 'main subject'):
        if not b.selection(index, edit):
            return
    b.add(index, 'studio.ai_layer', params, f'Paint with AI: {edit["quote"][:60]}')


@procedure('other', 'Another PhotoCraft feature', 'ai', 'expert',
           'any other PhotoCraft capability not listed (describe it in choice)')
def other(b, index, edit):
    """The model picks one registry command for this edit; its settings are the command's own
    defaults, never numbers the model wrote (see photocraft_planner.expert)."""
    b.expert_requests.append(index)
