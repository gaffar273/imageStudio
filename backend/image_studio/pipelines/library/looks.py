"""Named looks: graded recipes of Camera Raw settings, lookup tables and curves.

Each recipe is fixed (photocraft_intents.RECIPES); strength scales it. On a part of the picture
(“make the sky dramatic”) the recipe develops a masked copy of that part only.
"""

import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import procedure


@procedure('look', 'Apply a look', 'look', 'adjust',
           'a named look: choice = ' + ', '.join(sorted(lang.RECIPES)) + ', ' + ', '.join(lang.LUTS),
           options=tuple(sorted(lang.RECIPES)) + tuple(lang.LUTS), area_safe=True,
           examples=('give it a cinematic look', 'vintage film look'))
def look(b, index, edit):
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    lut = next((name for name in lang.LUTS if name.lower() in words.replace(' ', '').replace('-', '')), None)
    recipe = next((lang.RECIPES[name] for name in sorted(lang.RECIPES, key=len, reverse=True)
                   if re.search(rf'\b{re.escape(name)}\b', words)), None)
    if edit['target'] == 'sky' and recipe in (lang.RECIPES['dramatic'], lang.RECIPES['moody'], lang.RECIPES['hdr'],
                                              None):
        recipe = lang.RECIPES['dramatic sky']
    if lut is None and recipe is None:
        lut_words = {'teal': 'tealOrange', 'film': 'fadedFilm', 'faded': 'fadedFilm', 'bleach': 'bleachBypass',
                     'night': 'dayForNight', 'cross': 'crossProcess', 'noir': 'monoContrast'}
        lut = next((value for key, value in lut_words.items() if key in words), None)
    if lut is None and recipe is None:
        recipe = lang.RECIPES['professional polish']
    scale = lang.LEVEL[edit['strength']]
    local = edit['target'] not in ('whole image', 'layer')
    if recipe and 'raw' in recipe:
        params = {key: round(value * min(scale, 1.6), 2) for key, value in recipe['raw'].items()}
        if local:
            # “Make the sky dramatic” develops only the sky, on a masked copy of the photo.
            params.pop('vignetteAmount', None)
            if not b.local_develop(index, edit, params, lang.short_label(edit),
                                   'Develop: ' + ', '.join(f'{k} {v:+g}' for k, v in params.items())
                                   + f' · {edit["target"]}'):
                return
        else:
            b.raw[index] = params
            b.flush_raw()
    lut = lut or (recipe or {}).get('lut')
    layers = []
    if lut:
        layers.append(('colorLookup', {'lut': lut}, f'Look: {lut}'))
    if recipe and 'curves' in recipe:
        layers.append(('curves', {'points': recipe['curves']}, 'Matte curve'))
    if recipe and 'posterize' in recipe:
        layers.append(('posterize', {'levels': recipe['posterize']}, 'Posterize'))
    if recipe and 'toning' in recipe:
        shadows, highlights = recipe['toning']
        from .adjust import balance
        layers.append(('colorBalance', {'shadows': balance(shadows, 18 * scale),
                                        'highlights': balance(highlights, 18 * scale)}, 'Film toning'))
    for command, params, name in layers:
        b.adjustment(index, edit, command, params, name)
        opacity = {'subtle': 0.5, 'moderate': 0.8, 'strong': 1.0}[edit['strength']]
        if command == 'colorLookup' and opacity < 1:
            b.add(index, 'layer.setProps', {'opacity': opacity}, f'Look strength {opacity:.0%}')
