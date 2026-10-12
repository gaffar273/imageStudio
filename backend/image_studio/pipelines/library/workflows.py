"""Professional workflows: a job a working editor is hired for, as a fixed sequence of procedures.

A workflow never builds engine steps itself. It expands into procedure edits, which the builder
then orders by stage with everything else in the request, and which are checked one by one. Parts
that do not apply to every photo (no verticals to straighten, no sky to deepen, already well
exposed) are optional: when they cannot be done they become a note, not a reason to stop.
"""

import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import workflow


def part(parent, action, what, optional=False, **fields):
    """One procedure of a workflow, labelled with the workflow's name."""
    from image_studio.pipelines.core import REGISTRY

    edit = lang.blank(action, quote=f'{REGISTRY[parent].title}: {what}', **fields)
    edit['workflow'] = parent
    if optional:
        edit['optional'] = True
    return edit


def subject(edit):
    return {'object': edit['object']} if edit['object'] else {}


def wants(words, pattern):
    return bool(re.search(pattern, words, re.IGNORECASE))


MARKETPLACES = {  # (square side in px, share of the frame the product fills)
    'amazon': (2000, 0.85), 'shopify': (2048, 0.8), 'ebay': (1600, 0.8), 'etsy': (2000, 0.75),
    'generic': (2000, 0.8),
}


@workflow('product_marketplace', 'Marketplace product photo', 'workflow',
          'e-commerce listing photo (Amazon, Shopify, eBay, Etsy, “product photo for my store”): the product cut out '
          'onto pure white (or color), a soft contact shadow, centred filling the frame, square, exported at the '
          'marketplace size (object = the product; choice = amazon, shopify, ebay or etsy)',
          steps=('remove_background', 'drop_shadow', 'product_frame', 'resize'), options=tuple(MARKETPLACES),
          examples=('get this product photo ready for Amazon', 'make it a clean white-background product shot'),
           requires=r'amazon|shopify|ebay|etsy|marketplace|listing|e-?commerce|store|shop|white (back|bg)|product')
def product_marketplace(edit, prompt):
    words = f'{edit["choice"]} {edit["quote"]} {prompt}'.lower()
    market = next((name for name in MARKETPLACES if name in words), 'generic')
    side, fill = MARKETPLACES[market]
    color = edit['color'] if lang.hex_color(edit['color']) else 'white'
    parts = [part('product_marketplace', 'remove_background', f'pure {color} backdrop', color=color,
                  target='main subject', **subject(edit))]
    if not wants(words, r'no (contact )?shadow|without (a )?shadow'):
        parts.append(part('product_marketplace', 'drop_shadow', 'soft contact shadow', strength='subtle',
                          **subject(edit)))
    parts.append(part('product_marketplace', 'product_frame', f'centred, filling {fill:.0%} of a square frame',
                      aspect='1:1', value=round(fill * 100), color=color, **subject(edit)))
    parts.append(part('product_marketplace', 'resize', f'export {side}x{side} px for {market}'))
    return parts


@workflow('product_transparent', 'Product cut-out (transparent)', 'workflow',
          'the product alone on a transparent background, cropped close, for a website or a design (object = the '
          'product)', steps=('remove_background', 'crop_to_object'),
          examples=('cut out the product with a transparent background for my website',),
           requires=r'transparent|cut ?out|png|no background|without (a |the )?background')
def product_transparent(edit, prompt):
    return [part('product_transparent', 'remove_background', 'transparent background', color='transparent',
                 target='main subject', **subject(edit)),
            part('product_transparent', 'crop_to_object', 'cropped close around the product', target='main subject',
                 **subject(edit))]


@workflow('product_polish', 'Product detail polish', 'workflow',
          'make a product look premium and crisp: dust cleared, neutral color, crisp detail and clarity on the product '
          '(object = the product)', steps=('auto_fix', 'dust_cleanup', 'clarity', 'high_pass_sharpen'),
          examples=('make the watch look premium and crisp',),
           requires=r'product|premium|crisp|catalog|shop|store|watch|jewel|sell')
def product_polish(edit, prompt):
    target = 'object' if edit['object'] else 'main subject'
    return [part('product_polish', 'auto_fix', 'neutral color', choice='color'),
            part('product_polish', 'dust_cleanup', 'dust and specks cleared', target=target, **subject(edit)),
            part('product_polish', 'clarity', 'more definition', direction='increase', strength='subtle',
                 target=target, **subject(edit)),
            part('product_polish', 'high_pass_sharpen', 'crisp detail', strength='moderate', target=target,
                 **subject(edit))]


@workflow('portrait_finish', 'Full portrait retouch', 'workflow',
          'a complete professional portrait retouch (“retouch this portrait”, “make it magazine ready”, “beauty '
          'retouch”): blemishes, skin smoothing that keeps texture, dark circles, brighter eyes, a warm polish and a '
          'gentle vignette', steps=('retouch_portrait', 'look', 'vignette'),
          examples=('retouch this portrait professionally', 'make her portrait magazine ready'),
           requires=r'retouch|portrait|magazine|beauty|glamou?r|professional')
def portrait_finish(edit, prompt):
    strength = edit['strength'] if edit['strength'] != 'strong' else 'moderate'
    return [part('portrait_finish', 'retouch_portrait', 'blemishes, smoother skin, dark circles, brighter eyes',
                 choice='blemishes, smooth, dark circles, eyes', strength=strength, target='main subject'),
            part('portrait_finish', 'look', 'warm portrait polish', choice='warm portrait', strength='subtle'),
            part('portrait_finish', 'vignette', 'gentle vignette', direction='decrease', strength='subtle')]


@workflow('headshot_studio', 'Studio headshot', 'workflow',
          'a corporate or LinkedIn headshot on a clean studio backdrop: grey (or color) gradient backdrop, head-and-'
          'shoulders framing, light skin smoothing and polish', steps=('remove_background', 'headshot'),
          examples=('make a corporate headshot with a grey studio background',),
           requires=r'headshot|linked ?in|corporate|profile|studio|business')
def headshot_studio(edit, prompt):
    color = edit['color'] if lang.hex_color(edit['color']) else 'grey'
    framing = edit['quote'] if re.search(r'linked\s*in|profile|avatar|square|\d\s*:\s*\d', edit['quote'], re.I) else \
        'headshot'
    return [part('headshot_studio', 'remove_background', f'{color} studio gradient backdrop', color=color,
                 target='main subject'),
            {**part('headshot_studio', 'headshot', 'head-and-shoulders framing', aspect=edit['aspect']),
             'quote': f'Studio headshot: {framing}'}]


@workflow('real_estate_interior', 'Real estate interior', 'workflow',
          'a listing photo of a room (real estate, Airbnb, interior): upright walls, lens distortion fixed, '
          'measured exposure, window views recovered, neutral white balance, a little clarity and color',
          steps=('perspective', 'lens_correction', 'exposure_fix', 'window_pull', 'auto_fix', 'clarity', 'vibrance'),
          examples=('edit this room for a real estate listing', 'make this Airbnb photo bright and inviting'),
           requires=r'real estate|listing|property|airbnb|rental|interior|room|apartment|house|home|hotel')
def real_estate_interior(edit, prompt):
    w = 'real_estate_interior'
    return [part(w, 'perspective', 'vertical walls', optional=True),
            part(w, 'lens_correction', 'lens distortion', choice='distortion'),
            part(w, 'exposure_fix', 'bright, even exposure', choice='bright', optional=True),
            part(w, 'window_pull', 'window views recovered', strength='subtle', optional=True),
            part(w, 'auto_fix', 'neutral white balance', choice='color'),
            part(w, 'clarity', 'crisper detail', direction='increase', strength='subtle'),
            part(w, 'vibrance', 'a little more color', direction='increase', strength='subtle')]


@workflow('real_estate_exterior', 'Real estate exterior', 'workflow',
          'a listing photo of a house or building from outside: upright walls, measured exposure, a deeper blue sky, '
          'greener lawn and crisp detail', steps=('perspective', 'exposure_fix', 'look', 'saturation', 'clarity'),
          examples=('edit the front of the house for the listing',),
           requires=r'real estate|listing|property|house|building|exterior|facade|home')
def real_estate_exterior(edit, prompt):
    w = 'real_estate_exterior'
    return [part(w, 'perspective', 'vertical walls', optional=True),
            part(w, 'exposure_fix', 'balanced exposure', optional=True),
            part(w, 'look', 'deeper sky', choice='dramatic sky', target='sky', strength='subtle', optional=True),
            part(w, 'saturation', 'greener lawn and trees', target='color', color='green', direction='increase',
                 strength='subtle'),
            part(w, 'clarity', 'crisper detail', direction='increase', strength='subtle')]


@workflow('landscape_enhance', 'Landscape enhancement', 'workflow',
          'make a landscape or travel photo look its best: measured exposure, less haze, a graduated filter for a '
          'deeper sky, livelier color and definition',
          steps=('exposure_fix', 'dehaze', 'graduated_filter', 'vibrance', 'clarity'),
          examples=('enhance this landscape', 'make my travel photo pop'),
           requires=r'landscape|scenery|travel|nature|vista|view|enhance|pop|scenic')
def landscape_enhance(edit, prompt):
    w = 'landscape_enhance'
    strength = edit['strength']
    return [part(w, 'exposure_fix', 'balanced exposure', optional=True),
            part(w, 'dehaze', 'less haze', direction='increase', strength='subtle'),
            # A graduated filter, not a sky selection: on a sea horizon the sky selection drew an arc
            # across the water (measured 2026-10-12).
            part(w, 'graduated_filter', 'deeper sky', position='top', strength='subtle'),
            part(w, 'vibrance', 'livelier color', direction='increase', strength=strength),
            part(w, 'clarity', 'more definition', direction='increase', strength='subtle')]


@workflow('sunset_enhance', 'Sunset enhancement', 'workflow',
          'make a sunset or sunrise glow: warmer light, richer oranges and reds, held-back highlights and a darker '
          'graduated sky', steps=('temperature', 'saturation', 'highlights', 'graduated_filter'),
          examples=('make the sunset more vivid',),
           requires=r'sunset|sunrise|golden|dusk|dawn')
def sunset_enhance(edit, prompt):
    w = 'sunset_enhance'
    return [part(w, 'temperature', 'warmer light', direction='increase', strength='subtle'),
            part(w, 'saturation', 'richer oranges', target='color', color='orange', direction='increase',
                 strength=edit['strength']),
            part(w, 'highlights', 'held-back highlights', direction='decrease', strength='subtle'),
            part(w, 'graduated_filter', 'deeper sky at the top', position='top', strength='subtle')]


@workflow('food_enhance', 'Food photo', 'workflow',
          'make food look appetising: neutral then slightly warm color, livelier color, texture and crisp detail, '
          'highlights held back', steps=('auto_fix', 'temperature', 'vibrance', 'clarity', 'highlights',
                                         'high_pass_sharpen'),
          examples=('make this food photo look delicious',),
           requires=r'food|dish|meal|plate|delicious|appeti|restaurant|menu|tasty')
def food_enhance(edit, prompt):
    w = 'food_enhance'
    return [part(w, 'auto_fix', 'neutral color', choice='color'),
            part(w, 'temperature', 'slightly warm', direction='increase', strength='subtle'),
            part(w, 'vibrance', 'livelier color', direction='increase'),
            part(w, 'clarity', 'texture', direction='increase', strength='subtle'),
            part(w, 'highlights', 'held-back highlights', direction='decrease', strength='subtle'),
            part(w, 'high_pass_sharpen', 'crisp detail', strength='subtle')]


@workflow('wedding_airy', 'Bright and airy wedding edit', 'workflow',
          'the light, soft wedding and lifestyle style: bright and airy tones, gently smoothed skin',
          steps=('look', 'retouch_portrait'), examples=('give it a light and airy wedding edit',),
           requires=r'wedding|airy|bride|lifestyle|light and (soft|bright)')
def wedding_airy(edit, prompt):
    return [part('wedding_airy', 'look', 'bright and airy tones', choice='bright and airy', strength=edit['strength']),
            part('wedding_airy', 'retouch_portrait', 'gently smoothed skin', choice='smooth', strength='subtle',
                 target='main subject', optional=True)]


@workflow('fine_art_bw', 'Fine-art black and white', 'workflow',
          'a fine-art black and white print: a high-contrast mix, an S-curve, fine grain and a gentle vignette',
          steps=('black_and_white', 'tone_curve', 'grain', 'vignette'),
          examples=('make it a dramatic fine art black and white',),
           requires=r'black (and|&) white|b&w|monochrome|fine art|noir')
def fine_art_bw(edit, prompt):
    w = 'fine_art_bw'
    words = f'{edit["choice"]} {edit["quote"]}'.lower()
    mix = 'red filter' if wants(words, r'sky|landscape|cloud|red filter') else 'high contrast'
    return [part(w, 'black_and_white', f'{mix} mix', choice=mix),
            part(w, 'tone_curve', 'S-curve', choice='s-curve', strength=edit['strength']),
            part(w, 'grain', 'fine grain', strength='subtle'),
            part(w, 'vignette', 'gentle vignette', direction='decrease', strength='subtle')]


@workflow('photo_correction', 'General photo correction', 'workflow',
          'a vague request to fix or improve a photo (“fix this photo”, “make it look better”, “enhance it”): '
          'measured exposure, neutral color, a little life and crispness',
          steps=('exposure_fix', 'auto_fix', 'vibrance', 'clarity', 'sharpen'),
          examples=('fix this photo', 'make this picture look better'),
           requires=r'fix|correct|improve|better|enhance|clean ?up|looks? (off|bad|dull)|edit (this|my|the) photo')
def photo_correction(edit, prompt):
    w = 'photo_correction'
    return [part(w, 'exposure_fix', 'balanced exposure', optional=True),
            part(w, 'auto_fix', 'neutral color', choice='color'),
            part(w, 'vibrance', 'a little more color', direction='increase', strength='subtle'),
            part(w, 'clarity', 'a little definition', direction='increase', strength='subtle'),
            part(w, 'sharpen', 'crisper', strength='subtle')]


@workflow('scan_restore', 'Scanned photo restoration', 'workflow',
          'a scanned or old print: straightened, damage repaired, the yellowed color neutralised',
          steps=('straighten', 'restore', 'auto_fix'), examples=('clean up this old scanned print',),
           requires=r'scan|old|print|restor|faded|vintage photo')
def scan_restore(edit, prompt):
    w = 'scan_restore'
    return [part(w, 'straighten', 'level the scan', optional=True),
            part(w, 'restore', 'repair scratches, dust and fading'),
            part(w, 'auto_fix', 'neutralise the yellowing', choice='color')]


@workflow('youtube_thumbnail', 'YouTube thumbnail', 'workflow',
          'a YouTube thumbnail: 1280×720 around the subject, punchy contrast and color, and the title (text = exact '
          'words) large and bold with an outline', steps=('resize', 'contrast', 'vibrance', 'add_text'),
          examples=('make a youtube thumbnail with the title "I QUIT"',),
           requires=r'youtube|thumbnail')
def youtube_thumbnail(edit, prompt):
    w = 'youtube_thumbnail'
    parts = [part(w, 'resize', 'youtube thumbnail 1280x720 px'),
             part(w, 'contrast', 'punchier contrast', direction='increase'),
             part(w, 'vibrance', 'bolder color', direction='increase', strength='strong')]
    if edit['text']:
        parts.append({**part(w, 'add_text', 'bold title', text=edit['text'], position=edit['position'] or 'left',
                             size='huge', color=edit['color'], choice='bold outline'),
                      'quote': f'YouTube thumbnail title “{edit["text"]}”'})
    return parts


@workflow('social_post', 'Instagram-ready post', 'workflow',
          'ready to post on Instagram: the 4:5 portrait post shape around the subject at 1080×1350, a gentle polish '
          'and screen sharpening', steps=('resize', 'look', 'sharpen'),
          examples=('get this ready for instagram',),
           requires=r'instagram|insta|social|post|feed')
def social_post(edit, prompt):
    w = 'social_post'
    words = f'{edit["quote"]} {prompt}'.lower()
    size = 'instagram post 1080x1080 px' if wants(words, r'square') else 'instagram portrait 1080x1350 px'
    return [part(w, 'resize', size),
            part(w, 'look', 'gentle polish', choice='professional polish', strength='subtle'),
            part(w, 'sharpen', 'screen sharpening', strength='subtle')]


@workflow('web_export', 'Export for the web', 'workflow',
          'export for a website or email: 2048 px on the long side, RGB, sharpened for screens',
          steps=('resize', 'sharpen'), examples=('export it for my website',),
           requires=r'web|website|online|e-?mail|blog|export')
def web_export(edit, prompt):
    w = 'web_export'
    return [part(w, 'resize', '2048 px long side'),
            part(w, 'sharpen', 'screen sharpening', strength='subtle')]


@workflow('print_prep', 'Prepare for print', 'workflow',
          'prepare for printing: 300 ppi at the asked print size, output sharpening, CMYK only when asked',
          steps=('resize', 'high_pass_sharpen', 'convert_mode'),
          examples=('prepare it for printing as an 8x10',),
           requires=r'print|paper|press')
def print_prep(edit, prompt):
    w = 'print_prep'
    size = lang.output_size(edit['quote'], 1000, 1000)
    parts = [{**part(w, 'resize', 'print size at 300 ppi'),
              'quote': edit['quote'] if size and size.get('ppi') else f'{edit["quote"]} at 300 dpi'},
             part(w, 'high_pass_sharpen', 'output sharpening for paper', strength='moderate')]
    if wants(f'{edit["quote"]} {prompt}', r'\bcmyk\b'):
        parts.append(part(w, 'convert_mode', 'CMYK for the press', choice='cmyk'))
    return parts


@workflow('subject_pop', 'Make the subject stand out', 'workflow',
          'make the subject stand out from its surroundings: a darker, quieter background and a brighter, crisper '
          'subject (object = the subject)', steps=('exposure', 'saturation', 'clarity'),
          examples=('make the person stand out from the background',),
           requires=r'stand out|pop|separate|focus|draw (the )?eye|attention')
def subject_pop(edit, prompt):
    w = 'subject_pop'
    named = subject(edit)
    key = edit['object'] or 'the main subject'
    target = 'object' if edit['object'] else 'main subject'
    return [part(w, 'exposure', 'darker background', target='background', object=key, direction='decrease',
                 strength='subtle'),
            part(w, 'saturation', 'quieter background color', target='background', object=key, direction='decrease',
                 strength='subtle'),
            part(w, 'clarity', 'crisper subject', target=target, direction='increase', strength='subtle', **named),
            part(w, 'exposure', 'brighter subject', target=target, direction='increase', strength='subtle', **named)]


@workflow('color_splash', 'Color splash', 'workflow',
          'the subject stays in color while everything else turns black and white (object = what stays in color)',
          steps=('black_and_white',), examples=('keep only the girl in color',),
           requires=r'black (and|&) white|b&w|gr[ae]y|monochrome|desaturat|in colou?r|colou?r splash|splash')
def color_splash(edit, prompt):
    return [part('color_splash', 'black_and_white', 'everything else in black and white', target='background',
                 object=edit['object'] or 'the main subject')]


@workflow('cinematic_film', 'Cinematic film still', 'workflow',
          'look like a frame from a film: a cinematic grade, widescreen bars and fine grain',
          steps=('look', 'letterbox', 'grain'), examples=('make it look like a movie still',),
           requires=r'movie|film|cinema|cinematic|hollywood|still')
def cinematic_film(edit, prompt):
    w = 'cinematic_film'
    return [part(w, 'look', 'cinematic grade', choice='cinematic', strength=edit['strength']),
            part(w, 'letterbox', 'widescreen bars', aspect=edit['aspect']),
            part(w, 'grain', 'fine film grain', strength='subtle')]


@workflow('instant_photo', 'Instant photo', 'workflow',
          'look like an instant (polaroid) print: a faded vintage color and the white instant-film frame',
          steps=('look', 'polaroid'), examples=('make it look like an old polaroid',),
           requires=r'polaroid|instant|instax')
def instant_photo(edit, prompt):
    return [part('instant_photo', 'look', 'faded vintage color', choice='vintage', strength='subtle'),
            part('instant_photo', 'polaroid', 'instant-film frame', color=edit['color'])]


@workflow('miniature_world', 'Miniature (toy town)', 'workflow',
          'make a scene look like a miniature toy model: a tilt-shift band of focus and bright, saturated color',
          steps=('tilt_shift', 'saturation', 'contrast'), examples=('make the city look like a miniature',),
           requires=r'miniature|toy|tilt.?shift|diorama|model')
def miniature_world(edit, prompt):
    w = 'miniature_world'
    return [part(w, 'tilt_shift', 'tilt-shift focus band', position=edit['position'] or 'center'),
            part(w, 'saturation', 'toy-like color', direction='increase', strength='strong'),
            part(w, 'contrast', 'crisp contrast', direction='increase')]


@workflow('pet_portrait', 'Pet portrait', 'workflow',
          'a pet portrait: a softly blurred background, crisp fur and eyes, a little warmth (object = the pet)',
          steps=('blur_background', 'clarity', 'temperature'), examples=('make a nice portrait of my dog',),
           requires=r'pet|dog|cat|puppy|kitten|animal')
def pet_portrait(edit, prompt):
    w = 'pet_portrait'
    target = 'object' if edit['object'] else 'main subject'
    return [part(w, 'blur_background', 'soft background', strength='subtle', **subject(edit)),
            part(w, 'clarity', 'crisp fur', target=target, direction='increase', strength='subtle', **subject(edit)),
            part(w, 'temperature', 'a little warmth', direction='increase', strength='subtle')]
