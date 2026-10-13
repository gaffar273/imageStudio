"""Professional editing requests run through the real planner, scored by what it would do.

Each case is a request a working photo editor gets, on a photo it makes sense for, with the
actions a correct plan must contain. A case passes when every expected action is planned, the
plan has engine steps, and nothing is left unresolved. Nothing is applied to any document.

    python scripts/planner_bench.py [--only word] [--fresh] [--jobs-file results.json]

The brain's answers are cached by their exact input (WORK/planner-bench/cache), so a rerun
after a code change only asks again for prompts the change affected.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from image_studio.core.catalog import WORK
from image_studio.integrations import photocraft_planner as planner
from image_studio.integrations import photocraft_workspace as ws
from image_studio.services import brain
from PIL import Image

PHOTOS = {
    'man': '5931ca85daad47869f91e7349a77a91b',  # portrait, busy background
    'woman': '576cd5e8213e434a857984ab4bd4d781',  # portrait by a window
    'group': '8b46e3a7d28e4eaaa252560103198beb',  # five people on a beach
    'mugs': '3ba5157c93c749d8b18a1b2b1d13cef4',  # product row on a shelf
    'puppy': '8bc7bb71b0f54917b622d090f35b5288',  # pet on white
    'town': '2ddf47bab770470497f4658787de1eaa',  # coastal landscape
    'room': '14d1ed192d054c74a23e59e179d1cd68',  # interior with cat and dog
    'neon': '209cf19c7a434327a7096b59c460a6ff',  # neon sign
    'street': ROOT / 'images' / '20261007-072612-22-128400.png',  # café in front of a Roman building
}

# (category, photo, request, expected actions; "a|b" accepts either; "ask" means the right answer is a
# question back, e.g. when there is no room to move something)
CASES = [
    # Print and ID formats
    ('format', 'man', 'make a passport size photo', ['passport_photo']),
    ('format', 'man', 'US visa photo 2x2 inch with white background', ['passport_photo']),
    ('format', 'woman', 'ID card photo 35x45 mm', ['passport_photo']),
    ('format', 'man', 'stamp size photo', ['passport_photo']),
    ('format', 'town', 'prepare this for a 4x6 inch print at 300 dpi', ['resize']),
    ('format', 'town', 'make it A4 size for printing', ['resize']),
    ('format', 'room', 'set the resolution to 300 dpi without changing the pixels', ['resize']),
    ('format', 'town', 'convert to CMYK for the print shop', ['convert_mode']),
    ('format', 'woman', 'convert the image to grayscale mode', ['convert_mode|black_and_white']),
    # Social and web formats
    ('social', 'town', 'make it an instagram post', ['crop_aspect|resize']),
    ('social', 'town', 'crop for an instagram story', ['crop_aspect|resize']),
    ('social', 'room', 'youtube thumbnail size 1280x720', ['resize']),
    ('social', 'town', 'linkedin banner', ['crop_aspect|resize']),
    ('social', 'woman', 'facebook cover photo', ['crop_aspect|resize']),
    ('social', 'puppy', 'fit the whole photo in a square with white bars, do not cut anything', ['fit_canvas']),
    ('social', 'town', 'make it 1080 pixels wide', ['resize']),
    ('social', 'town', 'reduce the size to half', ['resize']),
    ('social', 'room', 'make it 2x bigger', ['resize']),
    ('social', 'mugs', 'square 2000x2000 for amazon listing', ['resize']),
    # Portrait retouching
    ('portrait', 'woman', 'smooth her skin a little', ['texture|retouch_portrait']),
    ('portrait', 'man', 'remove pimples and blemishes from his face', ['retouch_portrait']),
    ('portrait', 'group', 'whiten their teeth', ['retouch_portrait']),
    ('portrait', 'woman', 'brighten her eyes', ['retouch_portrait|brightness|exposure']),
    ('portrait', 'woman', 'remove the dark circles under her eyes', ['retouch_portrait']),
    ('portrait', 'man', 'reduce the shine on his forehead', ['retouch_portrait']),
    ('portrait', 'man', 'remove the reflection on his glasses', ['remove_object|generate|retouch_portrait']),
    ('portrait', 'woman', 'fix red eyes', ['retouch_portrait']),
    ('portrait', 'woman', 'even out her skin tone', ['retouch_portrait|texture']),
    ('portrait', 'man', 'make his beard darker', ['brightness|exposure|shadows|blacks']),
    ('portrait', 'woman', 'make her hair red', ['recolor']),
    ('portrait', 'man', 'change his shirt to black', ['recolor']),
    ('portrait', 'woman', 'change her eye color to green', ['recolor']),
    ('portrait', 'man', 'make him smile', ['generate']),
    ('portrait', 'woman', 'add soft studio lighting on her face', ['relight']),
    ('portrait', 'man', 'professional headshot for linkedin', ['headshot']),
    ('portrait', 'woman', 'dodge and burn to add dimension to her face', ['retouch_portrait|contrast|clarity']),
    ('portrait', 'woman', 'remove the wrinkles', ['retouch_portrait|texture']),
    ('portrait', 'man', 'sharpen his eyes', ['sharpen|high_pass_sharpen|retouch_portrait']),
    ('portrait', 'woman', 'warm up her skin tone slightly', ['temperature']),
    ('portrait', 'woman', 'fix the orange skin tone', ['temperature|hue_shift|saturation|auto_fix']),
    # Backgrounds
    ('background', 'man', 'remove the background', ['remove_background']),
    ('background', 'man', 'make the background transparent', ['remove_background']),
    ('background', 'woman', 'change the background to light grey', ['remove_background']),
    ('background', 'man', 'put him on a blue gradient background', ['remove_background']),
    ('background', 'woman', 'blur the background like a portrait lens', ['blur_background']),
    ('background', 'man', 'make the background black and white and keep him in color', ['black_and_white']),
    ('background', 'man', 'darken the background so he stands out', ['brightness|exposure']),
    ('background', 'woman', 'replace the background with a beach at sunset', ['generate']),
    ('background', 'puppy', 'make the background pure white', ['remove_background']),
    ('background', 'man', 'clean up the messy background', ['blur_background|remove_object|generate']),
    # Color and tone
    ('color', 'room', 'fix the white balance', ['auto_fix|temperature']),
    ('color', 'room', 'auto enhance', ['auto_fix|look']),
    ('color', 'room', 'the photo is too dark, brighten it', ['brightness|exposure|exposure_fix']),
    ('color', 'town', 'recover the blown out sky', ['highlights']),
    ('color', 'town', 'make it pop', ['vibrance|saturation|clarity|contrast|look']),
    ('color', 'town', 'teal and orange color grade', ['look|color_grade|split_tone']),
    ('color', 'town', 'golden hour look', ['look|color_filter|temperature']),
    ('color', 'woman', 'film look like kodak portra', ['look']),
    ('color', 'mugs', 'keep only the red mug in color and make everything else black and white',
     ['black_and_white|keep_one_color|color_splash']),
    ('color', 'town', 'make the sky bluer', ['saturation|recolor|color_grade']),
    ('color', 'town', 'make the water more turquoise', ['recolor|hue_shift|color_grade']),
    ('color', 'room', 'remove the yellow color cast', ['auto_fix|temperature|color_filter']),
    ('color', 'room', 'lower the contrast and lift the blacks for a matte look', ['look|contrast|blacks']),
    ('color', 'town', 'make it look like night', ['look']),
    ('color', 'woman', 'split tone with blue shadows and warm highlights', ['color_grade|split_tone']),
    ('color', 'town', 'HDR effect', ['look']),
    ('color', 'group', 'make the colors more natural', ['saturation|vibrance']),
    ('color', 'room', 'levels auto contrast', ['auto_fix|contrast']),
    # Restoration and technical
    ('repair', 'room', 'reduce the noise', ['noise_reduction']),
    ('repair', 'woman', 'remove dust and scratches', ['restore|noise_reduction|dust_cleanup']),
    ('repair', 'man', 'the photo is blurry, make it sharper', ['sharpen']),
    ('repair', 'town', 'straighten the horizon', ['straighten']),
    ('repair', 'street', 'fix the perspective so the walls are vertical', ['perspective']),
    ('repair', 'town', 'correct lens distortion', ['lens_correction']),
    ('repair', 'town', 'remove the vignette', ['vignette']),
    ('repair', 'room', 'remove chromatic aberration', ['lens_correction']),
    ('repair', 'woman', 'restore this old photo', ['restore']),
    ('repair', 'woman', 'colorize this black and white photo', ['generate']),
    ('repair', 'room', 'fix jpeg artifacts', ['noise_reduction|restore']),
    ('repair', 'group', 'upscale to 4k', ['resize']),
    ('repair', 'town', 'rotate 90 degrees clockwise', ['rotate']),
    ('repair', 'woman', 'flip it horizontally', ['flip']),
    # Objects
    ('object', 'room', 'remove the dog', ['remove_object']),
    ('object', 'room', 'remove the lamp', ['remove_object']),
    ('object', 'group', 'remove the man on the right', ['remove_object']),
    ('object', 'town', 'remove the boats', ['remove_object']),
    ('object', 'room', 'add a plant next to the chair', ['generate']),
    ('object', 'mugs', 'make the blue mug orange', ['recolor']),
    ('object', 'room', 'replace the red suitcase with a wooden box', ['generate']),
    ('object', 'group', 'blur their faces for privacy', ['blur|artistic']),
    ('object', 'room', 'pixelate the cat', ['artistic|blur']),
    ('object', 'room', 'make the cat bigger', ['transform_object']),
    # Four mugs stand in a tight row: there is no free space, so it must ask, not stack them.
    ('object', 'mugs', 'move the yellow mug to the left', ['transform_object', 'ask']),
    ('object', 'mugs', 'move the yellow mug to the left, in front of the blue one', ['transform_object']),
    ('object', 'room', 'remove the cat and the dog', ['remove_object', 'remove_object']),
    # Product and e-commerce
    ('product', 'puppy', 'add a soft shadow under him', ['drop_shadow']),
    ('product', 'mugs', 'white background for e-commerce', ['remove_background']),
    ('product', 'mugs', 'add a reflection under the mugs', ['reflection|generate']),
    ('product', 'puppy', 'center him with even margins', ['center_subject|crop_to_object']),
    ('product', 'mugs', 'crop tightly to the mugs', ['crop_to_object']),
    ('product', 'mugs', 'make the colors more vibrant', ['vibrance|saturation']),
    # Real estate and landscape
    ('landscape', 'town', 'replace the sky with a dramatic sunset', ['generate']),
    ('landscape', 'town', 'make the sky dramatic', ['look']),
    ('landscape', 'room', 'brighten the room and make it look airy', ['look|brightness|exposure']),
    ('landscape', 'town', 'make the greens greener', ['saturation|recolor']),
    ('landscape', 'town', 'add fog', ['dehaze|generate']),
    ('landscape', 'town', 'remove the haze', ['dehaze']),
    ('landscape', 'town', 'tilt shift miniature effect', ['tilt_shift']),
    ('landscape', 'town', 'add a sun flare from the top left', ['lens_flare']),
    ('landscape', 'town', 'add god rays coming through', ['relight|generate']),
    # Creative
    ('creative', 'woman', 'high contrast black and white', ['black_and_white']),
    ('creative', 'woman', 'sepia', ['sepia']),
    ('creative', 'room', 'vintage', ['look']),
    ('creative', 'woman', 'turn it into a pencil sketch', ['artistic']),
    ('creative', 'town', 'oil painting', ['artistic']),
    ('creative', 'woman', 'pop art', ['look|artistic|duotone|posterize']),
    ('creative', 'room', 'make it look like a cartoon', ['artistic|generate']),
    ('creative', 'neon', 'add a glow to the sign', ['glow']),
    ('creative', 'group', 'motion blur', ['motion_blur']),
    ('creative', 'town', 'zoom blur from the center', ['radial_blur']),
    ('creative', 'woman', 'mirror the left half onto the right', ['mirror']),
    ('creative', 'woman', 'add film grain', ['grain']),
    ('creative', 'woman', 'add a vignette', ['vignette']),
    ('creative', 'town', 'add rain', ['weather']),
    ('creative', 'room', 'add snow falling', ['weather|generate']),
    ('creative', 'woman', 'glitch effect', ['artistic|other']),
    ('creative', 'neon', 'duotone purple and orange', ['duotone']),
    # Text and graphics
    ('graphics', 'town', 'add the text "Visit Italy" at the top in bold white', ['add_text']),
    ('graphics', 'man', 'add a watermark "© Abdul" in the bottom right corner, semi transparent', ['add_text']),
    ('graphics', 'room', 'add a thin white border', ['canvas_border|frame']),
    ('graphics', 'woman', 'add a polaroid frame', ['canvas_border|picture_frame|frame|polaroid']),
    ('graphics', 'town', 'add a dark gradient at the bottom so text is readable', ['gradient_overlay']),
    ('graphics', 'puppy', 'add a caption "Max, 3 months" at the bottom', ['add_text']),
    ('graphics', 'mugs', 'put a 20% OFF sale badge in the top right', ['add_text|badge']),
    ('graphics', 'woman', 'round the corners', ['round_corners']),
    # Combined real requests
    ('combined', 'man', 'remove the background, make it white, and crop to a 4:5 headshot', [
        'remove_background', 'crop_aspect|crop_to_object|headshot']),
    ('combined', 'woman', 'warm, soft and bright with a little skin smoothing', [
        'temperature|look', 'texture|retouch_portrait']),
    ('combined', 'town', 'straighten, crop to 16:9 and add "SUMMER 2026" at the bottom', [
        'straighten', 'crop_aspect', 'add_text']),
    # Whole jobs: one professional workflow each (a plan made of the same procedures also passes)
    ('workflow', 'mugs', 'get this product photo ready for Amazon', ['product_marketplace']),
    ('workflow', 'mugs', 'cut out the mugs on a transparent background for my website',
     ['product_transparent|remove_background']),
    ('workflow', 'mugs', 'make the mugs look premium and crisp for the shop', ['product_polish|clarity|sharpen']),
    ('workflow', 'woman', 'retouch this portrait professionally, magazine ready', ['portrait_finish|retouch_portrait']),
    ('workflow', 'man', 'make a corporate headshot with a grey studio background', ['headshot_studio|headshot']),
    ('workflow', 'room', 'edit this room for a real estate listing', ['real_estate_interior']),
    ('workflow', 'street', 'edit this building photo for a property listing',
     ['real_estate_exterior|real_estate_interior|perspective']),
    ('workflow', 'town', 'enhance this landscape', ['landscape_enhance']),
    ('workflow', 'town', 'make the sunset colors more vivid', ['sunset_enhance|saturation|vibrance']),
    ('workflow', 'room', 'fix this photo', ['photo_correction']),
    ('workflow', 'woman', 'give it a light and airy wedding edit', ['wedding_airy|look']),
    ('workflow', 'street', 'turn it into a dramatic fine art black and white', ['fine_art_bw|black_and_white']),
    ('workflow', 'man', 'make a youtube thumbnail with the title "I QUIT"', ['youtube_thumbnail|resize']),
    ('workflow', 'town', 'get this ready to post on instagram', ['social_post|resize|crop_aspect']),
    ('workflow', 'town', 'export it for my website', ['web_export|resize']),
    ('workflow', 'town', 'prepare it for printing as an 8x10', ['print_prep|resize']),
    ('workflow', 'woman', 'make her stand out from the background', ['subject_pop|blur_background|exposure']),
    ('workflow', 'woman', 'keep only her in color and make the rest black and white', ['color_splash|black_and_white']),
    ('workflow', 'street', 'make it look like a still from a movie', ['cinematic_film|look']),
    ('workflow', 'puppy', 'make it look like an old polaroid', ['instant_photo|polaroid']),
    ('workflow', 'town', 'make the town look like a miniature toy model', ['miniature_world|tilt_shift']),
    ('workflow', 'puppy', 'make a nice pet portrait of the puppy', ['pet_portrait|blur_background']),
    ('workflow', 'woman', 'clean up this old scanned print', ['scan_restore|restore']),
    # Measured and technique pipelines
    ('technique', 'room', 'this photo is too dark', ['exposure_fix|exposure|brightness']),
    ('technique', 'town', 'add a graduated filter to darken the sky at the top', ['graduated_filter']),
    ('technique', 'room', 'the window is blown out, bring back the view outside', ['window_pull|highlights']),
    ('technique', 'group', 'the people are too dark against the bright sky', ['backlit_fix|shadows|exposure']),
    ('technique', 'town', 'split tone with teal shadows and orange highlights', ['split_tone|color_grade']),
    ('technique', 'mugs', 'make everything black and white except the red', ['keep_one_color']),
    ('technique', 'town', 'add an S curve for more punch', ['tone_curve|contrast']),
    ('technique', 'town', 'make the trees look autumnal', ['season|hue_shift']),
    ('technique', 'room', 'crop it using the rule of thirds around the cat', ['compose']),
    ('technique', 'mugs', 'use high pass sharpening on the mugs', ['high_pass_sharpen|sharpen']),
    ('technique', 'town', 'add a warm light leak in the top right corner', ['light_leak']),
    ('technique', 'street', 'add cinematic black bars at the top and bottom', ['letterbox']),
    ('technique', 'puppy', 'give it a white polaroid frame', ['polaroid']),
    ('technique', 'town', 'clean the dust spots off this scan', ['dust_cleanup|restore']),
]


# Held out (written 2026-10-13, after every fix above): requests none of the guards, fit rules or
# prompt wording were tuned on. Run it to measure, never to tune: a fix made because of a case
# here moves that case into CASES and a fresh request takes its place.
HOLDOUT = [
    ('format', 'woman', 'I need this as a 2 by 2 inch passport picture', ['passport_photo']),
    ('format', 'town', 'shrink it to 1600 pixels on the long side for email', ['resize|web_export']),
    ('social', 'street', 'crop it for a pinterest pin', ['crop_aspect|resize']),
    ('social', 'puppy', 'turn this into a square profile picture', ['crop_aspect|resize']),
    ('portrait', 'woman', 'soften her skin but keep it looking natural', ['retouch_portrait']),
    ('portrait', 'man', 'whiten his teeth slightly', ['retouch_portrait']),
    ('portrait', 'woman', 'get rid of the shine on her forehead', ['retouch_portrait']),
    ('portrait', 'man', 'make the background behind him a soft blur', ['blur_background']),
    ('background', 'puppy', 'swap the background for plain light blue', ['remove_background']),
    ('background', 'mugs', 'put a soft shadow under the mugs', ['drop_shadow']),
    ('color', 'town', 'make the sea a deeper blue', ['saturation|hue_shift|color_grade']),
    ('color', 'room', 'the whites look yellow, fix the colour cast', ['auto_fix|temperature']),
    ('color', 'woman', 'give it a cooler, bluish tone', ['temperature|color_grade|color_filter|look']),
    ('color', 'street', 'mute the colours a bit', ['saturation|vibrance']),
    ('light', 'room', 'open up the shadows a little', ['shadows']),
    ('light', 'town', 'tone down the bright sky', ['highlights|graduated_filter|exposure']),
    ('light', 'group', 'the photo looks flat, add some contrast', ['contrast|tone_curve']),
    ('light', 'street', 'make it a touch brighter overall', ['brightness|exposure|exposure_fix']),
    ('repair', 'woman', 'reduce the grain, it is too noisy', ['noise_reduction']),
    ('repair', 'town', 'the horizon is tilted, level it', ['straighten']),
    ('repair', 'street', 'fix the leaning walls of the building', ['perspective']),
    ('repair', 'room', 'sharpen it a bit, it looks soft', ['sharpen|high_pass_sharpen']),
    ('object', 'room', 'erase the dog from the picture', ['remove_object']),
    ('object', 'mugs', 'change the colour of the blue mug to red', ['recolor']),
    ('object', 'room', 'make the cat a bit bigger', ['transform_object']),
    ('product', 'mugs', 'clean product shot on a white background for my store',
     ['product_marketplace|product_transparent|remove_background']),
    ('landscape', 'town', 'bring out more detail in the clouds', ['highlights|clarity|dehaze|landscape_enhance']),
    ('landscape', 'town', 'make it look like a misty morning', ['dehaze|look|weather']),
    ('creative', 'street', 'give it a vintage film look', ['look|cinematic_film|grain']),
    ('creative', 'neon', 'make the neon glow stronger', ['glow']),
    ('creative', 'town', 'add a dark vignette around the edges', ['vignette']),
    ('creative', 'puppy', 'pencil sketch effect', ['artistic']),
    ('graphics', 'town', 'write "Amalfi" in big white letters at the bottom', ['add_text']),
    ('graphics', 'puppy', 'put a black frame around it', ['canvas_border|frame|picture_frame']),
    ('combined', 'woman', 'warm it up a little, crop to 4:5 and smooth her skin',
     ['temperature', 'crop_aspect', 'retouch_portrait']),
    ('combined', 'town', 'straighten it, then make the colours richer', ['straighten', 'saturation|vibrance']),
    ('workflow', 'room', 'make this living room look bright and inviting for Airbnb', ['real_estate_interior']),
    ('workflow', 'mugs', 'prepare these mugs for an online shop listing', ['product_marketplace|product_polish']),
    ('workflow', 'woman', 'make this into a professional LinkedIn headshot', ['headshot|headshot_studio']),
    ('workflow', 'street', 'make it moody and cinematic', ['cinematic_film|look|color_grade']),
]

# Which way the edit goes, not only which pipeline: "a>increase" passes when a planned edit of
# pipeline a goes up. Each phrasing once flipped a correct answer in the guards (2026-10-13).
DIRECTIONS = [
    ('direction', 'room', 'make it less dark', ['brightness|exposure|exposure_fix>increase']),
    ('direction', 'woman', 'make it less cold', ['temperature>increase']),
    ('direction', 'room', 'brighten the darker areas', ['brightness|exposure|shadows>increase']),
    ('direction', 'group', 'make it a lot less washed out', ['contrast|saturation|vibrance|tone_curve>increase']),
    ('direction', 'town', 'the sky is too bright', ['highlights|exposure|brightness|graduated_filter>decrease']),
    ('direction', 'street', 'reduce the warmth a bit', ['temperature>decrease']),
    ('direction', 'town', 'less saturated please', ['saturation|vibrance>decrease']),
    ('direction', 'woman', 'not so contrasty', ['contrast>decrease']),
    ('direction', 'town', 'the colours are dull, make them richer', ['saturation|vibrance>increase']),
    ('direction', 'room', 'lower the exposure slightly', ['exposure|brightness>decrease']),
    ('direction', 'street', 'make the lower half brighter', ['brightness|exposure>increase']),
    ('direction', 'town', 'clear up the haze over the town', ['dehaze>increase']),
    ('direction', 'town', 'add some mist', ['dehaze>decrease']),
    ('direction', 'man', 'not bright enough', ['brightness|exposure|exposure_fix>increase']),
    ('direction', 'woman', 'cool it down a touch', ['temperature>decrease']),
    ('direction', 'group', 'deepen the shadows', ['shadows|blacks>decrease']),
    ('direction', 'room', 'lift the shadows', ['shadows>increase']),
    ('direction', 'town', 'recover the blown out highlights', ['highlights>decrease']),
]
SETS = {'main': CASES, 'holdout': HOLDOUT, 'direction': DIRECTIONS}
# Pipelines whose direction the scoring reads (the rest have no amount to go up or down).
AMOUNT = {'brightness', 'exposure', 'exposure_fix', 'whites', 'blacks', 'shadows', 'highlights', 'vignette',
          'temperature', 'saturation', 'vibrance', 'contrast', 'clarity', 'texture', 'sharpen', 'dehaze'}


def cached_adapters(folder):
    """Hosted and OpenAI-compatible answers cached by their exact request, like the local model's,
    so a rerun after a code change pays only for prompts the change affected."""
    from image_studio.pipelines.models import adapters

    for kind in (adapters.OpenAICompatible, adapters.Anthropic):
        original = kind.complete

        def complete(self, system, content, schema=None, max_tokens=2500, temperature=0.0, _original=original):
            spec = {k: v for k, v in self.spec.items() if k not in ('api_key',)}
            key = hashlib.sha256(json.dumps([spec, system, content, schema, max_tokens, temperature],
                                            sort_keys=True).encode('utf-8')).hexdigest()
            path = folder / f'{key}.json'
            if path.exists():
                return json.loads(path.read_text(encoding='utf-8'))
            answer = _original(self, system, content, schema, max_tokens, temperature)
            path.write_text(json.dumps(answer), encoding='utf-8')
            return answer

        kind.complete = complete


def connect_planner(text):
    """--planner preset[:model]: the planner and checker use it; the grounder too when the model is
    known to give boxes on the grid, else it stays on the bundled model (as the app does)."""
    from image_studio.pipelines import models

    preset, _, model = text.partition(':')
    spec = {'preset': preset, **({'model': model} if model else {})}
    models.connect('planner', **spec)
    models.connect('checker', **spec)
    if models.can_ground(spec):
        models.connect('grounder', **spec)
    return models.describe()


def cached_chat(folder):
    """brain.chat with a disk cache keyed by the exact request."""
    original = brain.chat

    def chat(system, content, schema=None, max_tokens=2500, temperature=0.2, thinking=False):
        key = hashlib.sha256(json.dumps([system, content, schema, max_tokens, temperature, thinking],
                                        sort_keys=True).encode('utf-8')).hexdigest()
        path = folder / f'{key}.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        answer = original(system, content, schema, max_tokens, temperature, thinking)
        path.write_text(json.dumps(answer), encoding='utf-8')
        return answer

    return chat


def original_photo(workspace):
    if isinstance(workspace, Path):
        # A library image: opened as a throwaway workspace, so the studio's own list stays as it is.
        with tempfile.TemporaryDirectory() as temp, patch.object(ws, 'ROOT', Path(temp)):
            created = ws.create(workspace.read_bytes(), workspace.name)
            return original_photo(created['id'])
    data = ws.load(workspace)
    data['cursor'] = 0
    revision = data['history'][0]
    with Image.open(ws.folder_for(workspace) / f'{revision["id"]}.png') as image:
        return data, revision['state'], image.convert('RGB')


def run_case(category, photo, prompt, expected, photos):
    data, state, preview = photos[photo]
    started = time.time()
    try:
        edits, preserve, questions, notes = planner.understand(prompt, preview, state)
        plan = ws.compile_plan(data, prompt, edits, preserve, questions, notes, preview, 'bench')
    except Exception as exc:  # noqa: BLE001 - a crash is a failure to report, not a reason to stop
        return {'category': category, 'photo': photo, 'prompt': prompt, 'expected': expected, 'passed': False,
                'error': f'{type(exc).__name__}: {exc}', 'seconds': round(time.time() - started, 1)}
    # A workflow counts by its own name too (its parts are the procedures it expanded into).
    edits = plan['edits']
    actions = [edit['action'] for edit in edits] + sorted({edit['workflow'] for edit in edits if edit.get('workflow')})
    remaining = [(edit['action'], edit) for edit in edits] + [
        (name, None) for name in sorted({edit['workflow'] for edit in edits if edit.get('workflow')})]
    missing, wrong_direction = [], []
    asks = 'ask' in expected
    for want in [want for want in expected if want != 'ask']:
        names, _, direction = want.partition('>')
        names = names.split('|')
        hit = next((item for item in remaining if item[0] in names and (
            not direction or item[1] is not None and item[1]['direction'] == direction)), None)
        if hit:
            remaining.remove(hit)
            # A workflow's own part stands in for a named one; remove the parts it covered too.
            if hit[1] is None:
                remaining = [item for item in remaining if not (item[1] and item[1].get('workflow') == hit[0])]
        else:
            missing.append(want)
            wrong = [item[1]['direction'] for item in remaining if item[0] in names and item[1] is not None]
            if direction and wrong:
                wrong_direction.append(f'{want} planned as {wrong[0]}')
    # Edits nobody asked for (rule 3: only what was asked): an unmatched edit whose words are not in
    # the request, or that repeats another edit's words. Parts a workflow or a pipeline adds on
    # purpose (a passport photo's backdrop) are not extra; a clause that rightly needs two edits is
    # not either.
    said = re.sub(r'\W+', ' ', prompt.lower())
    quotes = [edit['quote'].lower() for edit in edits]
    extra = [name for name, edit in remaining if edit is not None and not edit.get('workflow')
             and not edit.get('part_of') and name != 'keep'
             and (re.sub(r'\W+', ' ', edit['quote'].lower()).strip() not in said
                  or quotes.count(edit['quote'].lower()) > 1)] if not asks else []
    # Measuring that nothing needs doing (“the horizon is already level”) is a correct answer.
    settled = any('already' in note for note in plan['notes'])
    problems = list(plan['unresolved']) + ([] if plan['steps'] or settled else ['no engine steps'])
    if asks:
        problems = [] if plan['unresolved'] or plan['questions'] else ['planned without asking']
    return {
        'category': category, 'photo': photo, 'prompt': prompt, 'expected': expected, 'actions': actions,
        'missing': missing, 'problems': problems, 'questions': plan['questions'], 'notes': plan['notes'],
        'steps': [step['command'] for step in plan['steps']], 'edits': plan['edits'],
        'wrong_direction': wrong_direction, 'extra': extra,
        'other': sum(1 for edit in edits if edit['action'] == 'other'),
        'passed': not missing and not problems, 'strict': not missing and not problems and not extra,
        'seconds': round(time.time() - started, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', default='', help='run cases whose category or request contains this')
    parser.add_argument('--fresh', action='store_true', help='ignore cached brain answers')
    parser.add_argument('--out', default='')
    parser.add_argument('--set', default='main', choices=[*SETS, 'all'],
                        help='main: the tuned cases; holdout: never tuned on; direction: up or down')
    parser.add_argument('--planner', default='',
                        help='preset[:model] for the planner and checker, e.g. anthropic:claude-opus-5-5, '
                             'ollama:qwen3-vl:8b, openai:<model> (default: the bundled model)')
    parser.add_argument('--menu', default='', choices=['', 'full', 'categories'],
                        help='the planner menu: every pipeline at once, or categories first')
    parser.add_argument('--photos', default='', help='a folder with the bench photos as <name>.png/.jpg '
                                                     '(see --export-photos), instead of this PC’s workspaces')
    parser.add_argument('--export-photos', default='', help='write the bench photos to this folder and stop')
    args = parser.parse_args()
    if args.export_photos:
        folder = Path(args.export_photos)
        folder.mkdir(parents=True, exist_ok=True)
        for name, workspace in PHOTOS.items():
            original_photo(workspace)[2].save(folder / f'{name}.png')
        print(f'Wrote {len(PHOTOS)} photos to {folder}')
        return
    if args.menu:
        os.environ['IMAGE_STUDIO_PLANNER_MENU'] = args.menu
    label = (args.planner.split(':')[0] if args.planner else 'local') + (f'-{args.menu}' if args.menu else '')
    out = Path(args.out or WORK / 'planner-bench' / f'results-{args.set}-{label}.json')
    cache = out.parent / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    if not args.fresh:
        brain.chat = cached_chat(cache)
        cached_adapters(cache)
    if args.planner:
        print('Models:', json.dumps(connect_planner(args.planner), ensure_ascii=False))
    pool = [case for name, cases in SETS.items() if args.set in (name, 'all') for case in cases]
    cases = [case for case in pool if args.only.lower() in (case[0] + ' ' + case[2]).lower()]
    sources = dict(PHOTOS)
    if args.photos:
        folder = Path(args.photos)
        sources = {name: next(iter(sorted(folder.glob(f'{name}.*'))), None) for name in PHOTOS}
        lost = [name for name, path in sources.items() if path is None and any(c[1] == name for c in cases)]
        if lost:
            raise SystemExit(f'Missing photos in {folder}: {", ".join(lost)}')
    photos = {name: original_photo(workspace) for name, workspace in sources.items()
              if any(case[1] == name for case in cases)}
    results = []
    for number, case in enumerate(cases, 1):
        result = run_case(*case, photos)
        results.append(result)
        mark = 'PASS' if result['passed'] else 'FAIL'
        detail = result.get('error') or (f'{result["actions"]} missing={result["missing"]} '
                                         f'problems={result["problems"][:2]}')
        if result.get('extra'):
            detail += f' extra={result["extra"]}'
        if result.get('wrong_direction'):
            detail += f' direction={result["wrong_direction"]}'
        print(f'{number:3}/{len(cases)} {mark} [{case[0]}] {case[2]} -> {detail}', flush=True)
        out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding='utf-8')
    passed = sum(result['passed'] for result in results)
    strict = sum(result.get('strict', False) for result in results)
    print(f'\n{passed}/{len(results)} passed; {strict}/{len(results)} with no unrequested edit')
    print(f'  wrong direction: {sum(bool(r.get("wrong_direction")) for r in results)}; '
          f'"other" (no pipeline, tools at default settings): {sum(r.get("other", 0) for r in results)}')
    by_category = {}
    for result in results:
        by_category.setdefault(result['category'], []).append(result['passed'])
    for category, marks in by_category.items():
        print(f'  {category:11} {sum(marks)}/{len(marks)}')


if __name__ == '__main__':
    main()
