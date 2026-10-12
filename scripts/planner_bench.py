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
    ('portrait', 'man', 'sharpen his eyes', ['sharpen']),
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
    ('color', 'room', 'the photo is too dark, brighten it', ['brightness|exposure']),
    ('color', 'town', 'recover the blown out sky', ['highlights']),
    ('color', 'town', 'make it pop', ['vibrance|saturation|clarity|contrast|look']),
    ('color', 'town', 'teal and orange color grade', ['look|color_grade']),
    ('color', 'town', 'golden hour look', ['look|color_filter|temperature']),
    ('color', 'woman', 'film look like kodak portra', ['look']),
    ('color', 'mugs', 'keep only the red mug in color and make everything else black and white',
     ['black_and_white']),
    ('color', 'town', 'make the sky bluer', ['saturation|recolor|color_grade']),
    ('color', 'town', 'make the water more turquoise', ['recolor|hue_shift|color_grade']),
    ('color', 'room', 'remove the yellow color cast', ['auto_fix|temperature|color_filter']),
    ('color', 'room', 'lower the contrast and lift the blacks for a matte look', ['look|contrast|blacks']),
    ('color', 'town', 'make it look like night', ['look']),
    ('color', 'woman', 'split tone with blue shadows and warm highlights', ['color_grade']),
    ('color', 'town', 'HDR effect', ['look']),
    ('color', 'group', 'make the colors more natural', ['saturation|vibrance']),
    ('color', 'room', 'levels auto contrast', ['auto_fix|contrast']),
    # Restoration and technical
    ('repair', 'room', 'reduce the noise', ['noise_reduction']),
    ('repair', 'woman', 'remove dust and scratches', ['restore|noise_reduction']),
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
    ('graphics', 'woman', 'add a polaroid frame', ['canvas_border|picture_frame|frame']),
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
]


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
    actions = [edit['action'] for edit in plan['edits']]
    remaining = list(actions)
    missing = []
    asks = 'ask' in expected
    for want in [want for want in expected if want != 'ask']:
        hit = next((a for a in remaining if a in want.split('|')), None)
        if hit:
            remaining.remove(hit)
        else:
            missing.append(want)
    # Measuring that nothing needs doing (“the horizon is already level”) is a correct answer.
    settled = any('already' in note for note in plan['notes'])
    problems = list(plan['unresolved']) + ([] if plan['steps'] or settled else ['no engine steps'])
    if asks:
        problems = [] if plan['unresolved'] or plan['questions'] else ['planned without asking']
    return {
        'category': category, 'photo': photo, 'prompt': prompt, 'expected': expected, 'actions': actions,
        'missing': missing, 'problems': problems, 'questions': plan['questions'], 'notes': plan['notes'],
        'steps': [step['command'] for step in plan['steps']], 'edits': plan['edits'],
        'passed': not missing and not problems, 'seconds': round(time.time() - started, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', default='', help='run cases whose category or request contains this')
    parser.add_argument('--fresh', action='store_true', help='ignore cached brain answers')
    parser.add_argument('--out', default=str(WORK / 'planner-bench' / 'results.json'))
    args = parser.parse_args()
    out = Path(args.out)
    cache = out.parent / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    if not args.fresh:
        brain.chat = cached_chat(cache)
    cases = [case for case in CASES if args.only.lower() in (case[0] + ' ' + case[2]).lower()]
    photos = {name: original_photo(workspace) for name, workspace in PHOTOS.items()
              if any(case[1] == name for case in cases)}
    results = []
    for number, case in enumerate(cases, 1):
        result = run_case(*case, photos)
        results.append(result)
        mark = 'PASS' if result['passed'] else 'FAIL'
        detail = result.get('error') or (f'{result["actions"]} missing={result["missing"]} '
                                         f'problems={result["problems"][:2]}')
        print(f'{number:3}/{len(cases)} {mark} [{case[0]}] {case[2]} -> {detail}', flush=True)
        out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding='utf-8')
    passed = sum(result['passed'] for result in results)
    print(f'\n{passed}/{len(results)} passed')
    by_category = {}
    for result in results:
        by_category.setdefault(result['category'], []).append(result['passed'])
    for category, marks in by_category.items():
        print(f'  {category:11} {sum(marks)}/{len(marks)}')


if __name__ == '__main__':
    main()
