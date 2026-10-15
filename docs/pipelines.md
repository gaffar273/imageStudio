# Pipeline catalog

Generated from the registry by `scripts/pipeline_catalog.py`: 123 pipelines, 24 professional workflows and 99 procedures. See `docs/pipeline-engine.md` for how they are chosen, built and checked.

A **procedure** builds PhotoCraft commands itself. A **workflow** is a professional job made of procedures; it expands into them, they are ordered by stage with everything else in the request, and each one is checked on its own. The planner (any connected model) only chooses the pipeline id and fills slots from closed menus; every setting below is computed by the pipeline.

Stages run in this order: layer housekeeping → pixel retouching → raw development → AI layers → adjustment layers → effects → cut-outs → geometry → text and graphics → output.

## Professional workflows

### `product_marketplace` — Marketplace product photo

*workflow*

E-commerce listing photo (Amazon, Shopify, eBay, Etsy, “product photo for my store”): the product cut out onto pure white (or color), a soft contact shadow, centred filling the frame, square, exported at the marketplace size (object = the product; choice = amazon, shopify, ebay or etsy).

Procedures: `remove_background` → `drop_shadow` → `product_frame` → `resize`
Choice menu: amazon, shopify, ebay, etsy, generic
Answers: “get this product photo ready for Amazon”; “make it a clean white-background product shot”

### `product_transparent` — Product cut-out (transparent)

*workflow*

The product alone on a transparent background, cropped close, for a website or a design (object = the product).

Procedures: `remove_background` → `crop_to_object`
Answers: “cut out the product with a transparent background for my website”

### `product_polish` — Product detail polish

*workflow*

Make a product look premium and crisp: dust cleared, neutral color, crisp detail and clarity on the product (object = the product).

Procedures: `auto_fix` → `dust_cleanup` → `clarity` → `high_pass_sharpen`
Answers: “make the watch look premium and crisp”

### `portrait_finish` — Full portrait retouch

*workflow*

A complete professional portrait retouch (“retouch this portrait”, “make it magazine ready”, “beauty retouch”): blemishes, skin smoothing that keeps texture, dark circles, brighter eyes, a warm polish and a gentle vignette.

Procedures: `retouch_portrait` → `look` → `vignette`
Answers: “retouch this portrait professionally”; “make her portrait magazine ready”

### `headshot_studio` — Studio headshot

*workflow*

A corporate or LinkedIn headshot on a clean studio backdrop: grey (or color) gradient backdrop, head-and-shoulders framing, light skin smoothing and polish.

Procedures: `remove_background` → `headshot`
Answers: “make a corporate headshot with a grey studio background”

### `real_estate_interior` — Real estate interior

*workflow*

A listing photo of a room (real estate, Airbnb, interior): upright walls, lens distortion fixed, measured exposure, window views recovered, neutral white balance, a little clarity and color.

Procedures: `perspective` → `lens_correction` → `exposure_fix` → `window_pull` → `auto_fix` → `clarity` → `vibrance`
Answers: “edit this room for a real estate listing”; “make this Airbnb photo bright and inviting”

### `real_estate_exterior` — Real estate exterior

*workflow*

A listing photo of a house or building from outside: upright walls, measured exposure, a deeper blue sky, greener lawn and crisp detail.

Procedures: `perspective` → `exposure_fix` → `look` → `saturation` → `clarity`
Answers: “edit the front of the house for the listing”

### `landscape_enhance` — Landscape enhancement

*workflow*

Make a landscape or travel photo look its best: measured exposure, less haze, a graduated filter for a deeper sky, livelier color and definition.

Procedures: `exposure_fix` → `dehaze` → `graduated_filter` → `vibrance` → `clarity`
Answers: “enhance this landscape”; “make my travel photo pop”

### `sunset_enhance` — Sunset enhancement

*workflow*

Make a sunset or sunrise glow: warmer light, richer oranges and reds, held-back highlights and a darker graduated sky.

Procedures: `temperature` → `saturation` → `highlights` → `graduated_filter`
Answers: “make the sunset more vivid”

### `food_enhance` — Food photo

*workflow*

Make food look appetising: neutral then slightly warm color, livelier color, texture and crisp detail, highlights held back.

Procedures: `auto_fix` → `temperature` → `vibrance` → `clarity` → `highlights` → `high_pass_sharpen`
Answers: “make this food photo look delicious”

### `wedding_airy` — Bright and airy wedding edit

*workflow*

The light, soft wedding and lifestyle style: bright and airy tones, gently smoothed skin.

Procedures: `look` → `retouch_portrait`
Answers: “give it a light and airy wedding edit”

### `fine_art_bw` — Fine-art black and white

*workflow*

A fine-art black and white print: a high-contrast mix, an S-curve, fine grain and a gentle vignette.

Procedures: `black_and_white` → `tone_curve` → `grain` → `vignette`
Answers: “make it a dramatic fine art black and white”

### `photo_correction` — Professional photo develop

*workflow*

Develop or fix a photo the way a retoucher does a camera file (“fix this photo”, “make it look better”, “enhance it”, “develop this raw”, “edit my DSLR photo professionally”, “refine this shot”): white balance, black and white points, midtones, contrast, colour, noise, sharpening, sky, horizon and a subtle vignette, each measured from the photo and skipped when it is not needed.

Procedures: `develop_white_balance` → `develop_tone` → `develop_color` → `develop_noise` → `develop_sharpen` → `develop_sky` → `develop_level` → `develop_vignette`
Answers: “fix this photo”; “make this picture look better”; “develop this raw photo like a pro”; “edit this DSLR shot professionally”

### `scan_restore` — Scanned photo restoration

*workflow*

A scanned or old print: straightened, damage repaired, the yellowed color neutralised.

Procedures: `straighten` → `restore` → `auto_fix`
Answers: “clean up this old scanned print”

### `youtube_thumbnail` — YouTube thumbnail

*workflow*

A YouTube thumbnail: 1280×720 around the subject, punchy contrast and color, and the title (text = exact words) large and bold with an outline.

Procedures: `resize` → `contrast` → `vibrance` → `add_text`
Answers: “make a youtube thumbnail with the title "I QUIT"”

### `social_post` — Instagram-ready post

*workflow*

Ready to post on Instagram: the 4:5 portrait post shape around the subject at 1080×1350, a gentle polish and screen sharpening.

Procedures: `resize` → `look` → `sharpen`
Answers: “get this ready for instagram”

### `web_export` — Export for the web

*workflow*

Export for a website or email: 2048 px on the long side, RGB, sharpened for screens.

Procedures: `resize` → `sharpen`
Answers: “export it for my website”

### `print_prep` — Prepare for print

*workflow*

Prepare for printing: 300 ppi at the asked print size, output sharpening, CMYK only when asked.

Procedures: `resize` → `high_pass_sharpen` → `convert_mode`
Answers: “prepare it for printing as an 8x10”

### `subject_pop` — Make the subject stand out

*workflow*

Make the subject stand out from its surroundings: a darker, quieter background and a brighter, crisper subject (object = the subject).

Procedures: `exposure` → `saturation` → `clarity`
Answers: “make the person stand out from the background”

### `color_splash` — Color splash

*workflow*

The subject stays in color while everything else turns black and white (object = what stays in color).

Procedures: `black_and_white`
Answers: “keep only the girl in color”

### `cinematic_film` — Cinematic film still

*workflow*

Look like a frame from a film: a cinematic grade, widescreen bars and fine grain.

Procedures: `look` → `letterbox` → `grain`
Answers: “make it look like a movie still”

### `instant_photo` — Instant photo

*workflow*

Look like an instant (polaroid) print: a faded vintage color and the white instant-film frame.

Procedures: `look` → `polaroid`
Answers: “make it look like an old polaroid”

### `miniature_world` — Miniature (toy town)

*workflow*

Make a scene look like a miniature toy model: a tilt-shift band of focus and bright, saturated color.

Procedures: `tilt_shift` → `saturation` → `contrast`
Answers: “make the city look like a miniature”

### `pet_portrait` — Pet portrait

*workflow*

A pet portrait: a softly blurred background, crisp fur and eyes, a little warmth (object = the pet).

Procedures: `blur_background` → `clarity` → `temperature`
Answers: “make a nice portrait of my dog”

## Correction

### `auto_fix` — Automatic correction (measured)

*procedure · stage: adjustment layers*

Automatic correction measured from the photo: choice = tone (auto levels), contrast, or color (white balance, color cast).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.levels`, `layer.renameLayer`
Choice menu: tone, contrast, color
Measures first: levels
Answers: “auto levels”; “remove the yellow color cast”

### `texture` — Texture

*procedure · stage: raw development*

Fine detail and skin texture (decrease to smooth skin).

Engine commands: `studio.develop`

### `sharpen` — Sharpen

*procedure · stage: raw development*

Sharpen details.

Engine commands: `studio.develop`

### `noise_reduction` — Noise reduction

*procedure · stage: raw development*

Reduce noise or grain.

Engine commands: `studio.develop`
Measures first: noise

### `exposure_fix` — Fix the exposure (measured)

*procedure · stage: raw development*

Fix a photo that is too dark, too bright, underexposed, overexposed or flat: the correction is measured from its histogram (choice = normal, or bright for interiors and high-key).

Engine commands: `studio.develop`
Choice menu: normal, bright
Measures first: exposure
Answers: “this photo is too dark”; “fix the overexposed photo”

### `backlit_fix` — Fix a backlit subject

*procedure · stage: raw development*

A subject in shadow against a bright background (backlit, against the light, silhouette that should not be): lift the subject, hold the background.

Engine commands: `studio.select_outline`, `studio.require_selection`, `studio.local_filter`, `select.deselect`, `select.inverse`
Answers: “the person is too dark against the bright sky”

### `high_pass_sharpen` — High-pass sharpening

*procedure · stage: effects*

Crisp local-contrast sharpening the retoucher’s way (a high-pass copy in Overlay), on the whole picture or the target only (“sharpen the subject”, “make the details crisp”).

Engine commands: `studio.select_insert`, `layer.stampVisible`, `filter.other.highPass`, `image.adjustments.desaturate`, `layer.setProps`
Answers: “make the details on the product crisp”

### `lens_correction` — Lens correction

*procedure · stage: geometry*

Fix lens faults: barrel or fisheye distortion, chromatic aberration (color fringes), dark lens corners (choice = distortion, fringes, vignette or all).

Engine commands: `studio.select_photo`, `filter.lensCorrection`
Choice menu: distortion, fringes, vignette, all
Answers: “remove the purple fringes”

## Light and tone

### `brightness` — Brightness

*procedure · stage: adjustment layers*

Overall brightness.

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.brightnessContrast`, `layer.renameLayer`

### `contrast` — Contrast

*procedure · stage: adjustment layers*

Contrast.

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.brightnessContrast`, `layer.renameLayer`

### `tone_curve` — Tone curve

*procedure · stage: adjustment layers*

A tone curve (choice = s-curve for punch, strong s-curve, faded/matte blacks, brighter midtones, darker midtones, inverted s-curve for a flat log look).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.curves`, `layer.renameLayer`
Choice menu: s-curve, strong s-curve, faded, brighter midtones, darker midtones, inverted s-curve
Answers: “add an S curve”; “fade the blacks”

### `exposure` — Exposure

*procedure · stage: raw development*

Exposure in stops (value in EV).

Engine commands: `studio.develop`

### `highlights` — Highlights

*procedure · stage: raw development*

Recover (decrease) or boost bright areas.

Engine commands: `studio.develop`

### `shadows` — Shadows

*procedure · stage: raw development*

Lift (increase) or deepen shadow areas.

Engine commands: `studio.develop`

### `whites` — Whites

*procedure · stage: raw development*

White point.

Engine commands: `studio.develop`

### `blacks` — Blacks

*procedure · stage: raw development*

Black point.

Engine commands: `studio.develop`

### `clarity` — Clarity

*procedure · stage: raw development*

Midtone local contrast, punch.

Engine commands: `studio.develop`

### `dehaze` — Dehaze

*procedure · stage: raw development*

Cut (increase) or add haze/fog.

Engine commands: `studio.develop`

### `graduated_filter` — Graduated filter

*procedure · stage: adjustment layers*

A graduated (ND) filter: darken and deepen one edge of the frame, usually the sky at the top (position = the edge; strength).

Engine commands: `studio.select_insert`, `select.rect`, `studio.require_selection`, `layer.newAdjustmentLayer.exposure`, `layer.renameLayer`, `select.deselect`
Answers: “add a graduated filter to darken the sky”

### `window_pull` — Recover bright windows and highlights

*procedure · stage: adjustment layers*

Bring back detail in the brightest parts: blown windows, a white sky, lamps (real estate “window pull”).

Engine commands: `studio.select_insert`, `select.colorRange`, `studio.require_selection`, `layer.newAdjustmentLayer.curves`, `layer.renameLayer`, `select.deselect`
Answers: “the windows are blown out, bring back the view”

### `relight` — Relight

*procedure · stage: effects*

Add directional light coming from position (color = light color).

Engine commands: `studio.select_photo`, `filter.render.relight`

## Color

### `saturation` — Saturation

*procedure · stage: adjustment layers*

Color saturation.

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.hueSaturation`, `layer.renameLayer`

### `vibrance` — Vibrance

*procedure · stage: adjustment layers*

Vibrance, gentle saturation that protects skin.

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.vibrance`, `layer.renameLayer`

### `hue_shift` — Hue shift

*procedure · stage: adjustment layers*

Rotate hues by degrees (value).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.hueSaturation`, `layer.renameLayer`

### `recolor` — Recolor

*procedure · stage: adjustment layers*

Change the color of the target to color (e.g. make the car red).

Engine commands: `studio.select_insert`, `studio.select_outline`, `studio.require_selection`, `layer.newAdjustmentLayer.hueSaturation`, `layer.renameLayer`, `select.deselect`
Answers: “make the red mug green”; “change his shirt to black”

### `color_grade` — Tint a tonal range

*procedure · stage: adjustment layers*

Tint shadows/midtones/highlights toward color (target = tone).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.colorBalance`, `layer.renameLayer`
Answers: “give the shadows a blue tint”

### `split_tone` — Split toning

*procedure · stage: adjustment layers*

Split toning: one color in the shadows and another in the highlights (color = “shadow color and highlight color”, e.g. “teal and orange”; cool shadows and warm highlights when none are named).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.colorBalance`, `layer.renameLayer`
Answers: “split tone with teal shadows and orange highlights”

### `keep_one_color` — Keep one color (color splash)

*procedure · stage: adjustment layers*

Black and white everywhere except one color, which stays (color = the color that stays, e.g. “keep only the red”).

Engine commands: `studio.select_insert`, `select.colorRange`, `studio.require_selection`, `select.modify.feather`, `select.inverse`, `layer.newAdjustmentLayer.blackWhite`, `layer.renameLayer`, `select.deselect`
Measures first: palette
Answers: “make everything black and white except the red”

### `color_filter` — Photo filter

*procedure · stage: adjustment layers*

Photo filter: warm, cool, sepia or a colored filter (color or choice).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.photoFilter`, `layer.renameLayer`
Choice menu: warm, warming, orange, cool, cooling, sepia, red, yellow, green, cyan, blue, violet, purple, magenta, underwater
Answers: “add a warming filter”

### `season` — Change the season’s colors

*procedure · stage: adjustment layers*

Shift the foliage and sky colors toward a season (choice = autumn, spring, summer or winter).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.hueSaturation`, `layer.renameLayer`
Choice menu: autumn, spring, summer, winter
Answers: “make the trees look autumnal”

### `temperature` — Temperature

*procedure · stage: raw development*

White balance warmer (increase) or cooler (decrease).

Engine commands: `studio.develop`

### `tint` — Tint

*procedure · stage: raw development*

White balance toward magenta (increase) or green (decrease).

Engine commands: `studio.develop`

## Looks and film

### `black_and_white` — Black and white

*procedure · stage: adjustment layers*

Black and white (choice: neutral, high contrast, infrared, red filter; color = tint).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.blackWhite`, `layer.renameLayer`
Choice menu: neutral, high contrast, infrared, red filter
Answers: “make it black and white”

### `sepia` — Sepia

*procedure · stage: adjustment layers*

Sepia toned black and white.

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.blackWhite`, `layer.renameLayer`

### `duotone` — Duotone

*procedure · stage: adjustment layers*

Two-color gradient map (color = "dark color and light color").

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.gradientMap`, `layer.renameLayer`

### `look` — Apply a look

*procedure · stage: adjustment layers*

A named look: choice = bleach bypass, bright and airy, cinematic, cyberpunk, dramatic, dramatic sky, enhance, golden hour, hdr, high key, kodak portra, low key, matte, moody, orton, pop art, professional polish, retro, vintage, warm portrait, warm, cool, tealOrange, bleachBypass, fadedFilm, dayForNight, monoContrast, crossProcess.

Engine commands: `studio.develop`
Choice menu: bleach bypass, bright and airy, cinematic, cyberpunk, dramatic, dramatic sky, enhance, golden hour, hdr, high key, kodak portra, low key, matte, moody, orton, pop art, professional polish, retro, vintage, warm portrait, warm, cool, tealOrange, bleachBypass, fadedFilm, dayForNight, monoContrast, crossProcess
Answers: “give it a cinematic look”; “vintage film look”

## Portrait retouching

### `headshot` — Professional headshot

*procedure · stage: geometry*

Professional headshot: head-and-shoulders crop with a gentle polish (aspect if named, square for profile pictures).

Engine commands: `studio.select_outline`, `studio.require_selection`, `select.colorRange`, `studio.local_filter`, `select.deselect`, `studio.develop`, `image.crop`
Answers: “turn this into a LinkedIn headshot”

### `retouch_portrait` — Portrait retouch

*procedure · stage: pixel retouching*

Portrait retouching of faces: choice = smooth skin, blemishes (pimples, acne, spots), wrinkles, even skin tone, dark circles, shine, whiten teeth, brighten eyes, red eye, sculpt (dodge and burn).

Engine commands: `studio.select_insert`, `studio.select_outline`, `studio.require_selection`, `select.colorRange`, `select.modify.feather`, `layer.newAdjustmentLayer.hueSaturation`, `layer.renameLayer`, `select.deselect`, `select.rect`, `studio.local_filter`
Choice menu: red eye, dark circles, teeth, eyes, blemishes, wrinkles, even tone, shine, sculpt, smooth
Measures first: skin_colors, teeth, teeth_colors
Answers: “smooth her skin a little”; “whiten their teeth”; “remove the dark circles under her eyes”

## Retouching and objects

### `remove_object` — Remove an object

*procedure · stage: pixel retouching*

Erase an object, person or thing and fill the area (object = what).

Engine commands: `studio.ai_layer`
Answers: “remove the trash can on the left”; “remove the second mug from the right”

### `transform_object` — Move, resize or duplicate an object

*procedure · stage: pixel retouching*

Move, resize or duplicate one object (object = what; choice = move, bigger, smaller or duplicate; position = where it goes).

Engine commands: `studio.transform_object`
Choice menu: move, bigger, smaller, duplicate
Answers: “move the yellow mug to the left”; “make the cat bigger”

### `restore` — Restore an old photo

*procedure · stage: pixel retouching*

Restore an old or damaged photo: scratches, dust, stains, creases, fading.

Engine commands: `studio.ai_layer`, `studio.develop`
Answers: “restore this old damaged photo”

### `dust_cleanup` — Clean dust and specks

*procedure · stage: pixel retouching*

Clear dust, sensor spots and fine specks (scanned film, a dusty product, sensor dust in a sky).

Engine commands: `studio.select_photo`, `filter.noise.dustAndScratches`
Answers: “clean the dust spots off the scan”

## Cut-outs and backgrounds

### `blur_background` — Blur the background

*procedure · stage: cut-outs*

Blur behind the main subject (portrait/bokeh look).

Engine commands: `studio.select_outline`, `studio.require_selection`, `select.inverse`, `select.modify.feather`, `studio.local_filter`, `select.deselect`
Answers: “blur the background”

### `remove_background` — Cut out the subject

*procedure · stage: cut-outs*

Cut out the main subject; color = new backdrop color or transparent.

Engine commands: `studio.select_outline`, `studio.require_selection`, `studio.select_photo`, `layer.layerMask.revealSelection`, `select.deselect`
Answers: “remove the background”; “put the puppy on a pastel pink background”

### `drop_shadow` — Contact shadow

*procedure · stage: effects*

Soft contact shadow under the main subject or objects, as if standing on a surface.

Engine commands: `studio.select_insert`, `layer.new.layer`, `select.rect`, `edit.fill`, `select.deselect`, `filter.blur.gaussianBlur`, `layer.setProps`, `studio.select_outline`, `layer.layerMask.hideSelection`

### `reflection` — Mirror reflection

*procedure · stage: effects*

A mirror reflection of the subject or objects on the surface below them.

Engine commands: `studio.reflection`

## Effects

### `posterize` — Posterize

*procedure · stage: adjustment layers*

Posterize into a number of levels (value).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.posterize`, `layer.renameLayer`

### `threshold` — Threshold

*procedure · stage: adjustment layers*

Pure black and white threshold (value 1..255).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.threshold`, `layer.renameLayer`

### `invert` — Invert

*procedure · stage: adjustment layers*

Invert colors (negative).

Engine commands: `studio.select_insert`, `layer.newAdjustmentLayer.invert`, `layer.renameLayer`

### `grain` — Grain

*procedure · stage: raw development*

Add film grain.

Engine commands: `studio.develop`

### `vignette` — Vignette

*procedure · stage: raw development*

Darken (decrease) or lighten (increase) the edges.

Engine commands: `studio.develop`

### `blur` — Blur

*procedure · stage: effects*

Soften/blur the target.

Engine commands: `studio.select_photo`, `filter.blur.gaussianBlur`

### `motion_blur` — Motion blur

*procedure · stage: effects*

Motion blur (value = distance).

Engine commands: `studio.select_photo`, `filter.blur.motionBlur`

### `radial_blur` — Zoom or spin blur

*procedure · stage: effects*

Zoom blur or spin blur from a point (choice = zoom or spin, position = center).

Engine commands: `studio.select_photo`, `filter.blur.radialBlur`
Choice menu: zoom, spin

### `tilt_shift` — Tilt-shift miniature

*procedure · stage: effects*

Miniature tilt-shift blur, sharp band at position.

Engine commands: `studio.select_photo`, `filter.blurGallery.tiltShift`

### `lens_flare` — Lens flare

*procedure · stage: effects*

Lens flare at position.

Engine commands: `studio.select_photo`, `filter.render.lensFlare`

### `artistic` — Artistic filter

*procedure · stage: effects*

Artistic filter, choice = oil paint, watercolor, pencil, cutout, dry brush, poster edges, ink outlines, sponge, emboss, find edges, solarize, pixelate, halftone, glitch….

Engine commands: `studio.select_photo`, `filter.stylize.oilPaint`
Choice menu: oil paint, oil painting, watercolor, pencil, colored pencil, cutout, dry brush, poster edges, ink outlines, sponge, paint daubs, pastel, sumi-e, plastic wrap, emboss, find edges, solarize, diffuse, pixelate, pixel, mosaic, halftone, crystallize, pointill, cartoon, comic, charcoal, chalk, sketch, fresco, neon, glass, stained glass, mezzotint, twirl, ripple, spherize, fisheye, wind, extrude, tiles, trace, glitch

### `glow` — Glow (Orton)

*procedure · stage: effects*

Soft glow or bloom (Orton effect, glowing lights or neon); target = what glows.

Engine commands: `studio.select_insert`, `layer.stampVisible`, `filter.blur.gaussianBlur`, `layer.setProps`

### `light_leak` — Light leak

*procedure · stage: effects*

A film light leak: a warm glow bleeding in from one edge or corner (position; color, orange by default).

Engine commands: `studio.select_insert`, `select.rect`, `layer.newFillLayer.solidColor`, `layer.setProps`, `select.deselect`
Answers: “add a light leak in the top right”

### `weather` — Rain or snow

*procedure · stage: effects*

Add falling rain or snow (choice = rain or snow).

Engine commands: `studio.select_insert`, `layer.new.layer`, `edit.fill`, `filter.noise.addNoise`, `image.adjustments.levels`, `filter.blur.motionBlur`, `layer.setProps`
Choice menu: rain, snow

### `mirror` — Mirror a half

*procedure · stage: effects*

Mirror one half of the picture onto the other (choice = left, right, top or bottom = the half that is kept).

Engine commands: `studio.mirror`
Choice menu: left, right, top, bottom

## Framing and geometry

### `crop_aspect` — Crop to a shape

*procedure · stage: geometry*

Crop to an aspect ratio (aspect like 1:1, 4:5, 16:9; position or main subject/object target says what to keep).

Engine commands: `image.crop`
Answers: “crop to a centered square”; “crop to 4:5 keeping the cat in frame”

### `crop_to_object` — Crop to an object

*procedure · stage: geometry*

Crop tightly around a named object or the main subject.

Engine commands: `image.crop`
Answers: “crop tightly around the dog”

### `compose` — Recompose by a composition rule

*procedure · stage: geometry*

Improve the composition by cropping so the main subject (or object) sits on a rule-of-thirds or golden ratio point (choice = rule of thirds or golden ratio; aspect if named).

Engine commands: `image.crop`
Choice menu: rule of thirds, golden ratio
Answers: “crop it using the rule of thirds”; “improve the composition”

### `product_frame` — Frame a product

*procedure · stage: geometry*

Frame the product (or main subject) centred so it fills a set share of the frame (value = % of the frame, 85 by default; aspect, square by default; color = backdrop for any added margin).

Engine commands: `image.crop`
Answers: “center the product so it fills 85% of a square frame”

### `rotate` — Rotate

*procedure · stage: geometry*

Rotate by degrees (value; choice clockwise/counterclockwise).

Engine commands: `image.imageRotation.90cw`
Answers: “rotate 90 degrees clockwise”

### `straighten` — Straighten the horizon

*procedure · stage: geometry*

Level a tilted horizon by a small number of degrees (value).

Engine commands: `image.crop`
Measures first: tilt
Answers: “straighten the horizon”

### `flip` — Flip

*procedure · stage: geometry*

Mirror the picture (choice horizontal/vertical).

Engine commands: `image.imageRotation.flipCanvasHorizontal`
Answers: “flip it horizontally”

### `center_subject` — Center the subject

*procedure · stage: geometry*

Crop so the main subject or object sits exactly in the middle with even margins.

Engine commands: `image.crop`
Answers: “center the product with even margins”

### `perspective` — Upright perspective

*procedure · stage: geometry*

Make leaning walls, buildings or doors vertical (upright, keystone, perspective).

Engine commands: `studio.select_photo`, `filter.adaptiveWideAngle`, `studio.crop_empty`
Measures first: verticals
Answers: “fix the leaning walls”

### `fit_canvas` — Fit into a shape

*procedure · stage: geometry*

Fit the whole picture into a new shape (aspect) WITHOUT cutting anything, filling the empty sides with color (letterbox, white bars, padding to square).

Engine commands: `image.canvasSize`, `layer.newFillLayer.solidColor`, `layer.renameLayer`, `layer.arrange.sendToBack`
Answers: “fit the whole photo in a square with white bars, do not cut anything”

## Size, print and export

### `passport_photo` — Passport or ID photo

*procedure · stage: geometry*

Passport, ID or visa photo: head-and-shoulders crop on a plain backdrop at the printed size in the quote (e.g. 35x45 mm, 2x2 inch); color = backdrop color.

Engine commands: `studio.select_outline`, `studio.require_selection`, `studio.select_photo`, `layer.layerMask.revealSelection`, `select.deselect`, `layer.newFillLayer.solidColor`, `layer.renameLayer`, `layer.arrange.sendToBack`, `image.crop`, `image.imageSize`
Answers: “make a passport size photo”; “US visa photo 2x2 inch with white background”

### `resize` — Resize or set print size

*procedure · stage: geometry*

Output size, print size or resolution: pixels (1080x1350, 2000 px wide, 50%, 2x bigger, half), print (4x6 inch, A4, 300 dpi), formats (instagram post or story, youtube thumbnail, linkedin or facebook cover, 4k, wallpaper).

Engine commands: `image.crop`, `image.imageSize`
Answers: “make it an instagram post”; “prepare this for a 4x6 inch print at 300 dpi”

### `convert_mode` — Color mode

*procedure · stage: output*

Convert the document color mode (choice = cmyk, grayscale, rgb, 16-bit, 8-bit).

Engine commands: `image.mode.cmyk`
Choice menu: cmyk, grayscale, rgb, 16-bit, 8-bit
Answers: “convert to CMYK for the print shop”

## Text and graphics

### `canvas_border` — Border

*procedure · stage: geometry*

Add an outer border/padding around the picture (value = px, color).

Engine commands: `image.canvasSize`, `layer.newFillLayer.solidColor`, `layer.renameLayer`, `layer.arrange.sendToBack`
Answers: “add a white border”

### `polaroid` — Instant-film border

*procedure · stage: geometry*

An instant photo (polaroid) frame: even white sides and top, a deep bottom edge (color = frame color).

Engine commands: `image.canvasSize`, `layer.newFillLayer.solidColor`, `layer.renameLayer`, `layer.arrange.sendToBack`
Answers: “make it look like a polaroid”

### `add_text` — Add text

*procedure · stage: text and graphics*

Add text: text = EXACT words, position, color, size or value in pt, choice = font or style (bold, italic, serif, script, shadow, outline, glow).

Engine commands: `studio.text`
Answers: “add the title SUMMER at the top in white”; “add a watermark”

### `edit_text` — Change existing text

*procedure · stage: text and graphics*

Change the words of an existing text layer (object = current text, text = new).

Engine commands: `type.edit`

### `frame` — Frame line

*procedure · stage: text and graphics*

Draw a frame line inside the edges (value = px, color).

Engine commands: `studio.select_top`, `layer.new.layer`, `select.rect`, `edit.stroke`, `select.deselect`

### `gradient_overlay` — Gradient overlay

*procedure · stage: text and graphics*

A gradient that darkens (or tints with color) from one edge, e.g. behind text (position = the darkest edge).

Engine commands: `studio.select_insert`, `layer.newFillLayer.gradient`, `layer.setProps`

### `round_corners` — Round the corners

*procedure · stage: text and graphics*

Round the corners of the picture (color = what shows in the corners).

Engine commands: `studio.select_top`, `layer.new.layer`, `select.rect`, `select.modify.smooth`, `select.inverse`, `edit.fill`, `select.deselect`

### `picture_frame` — Decorative frame

*procedure · stage: text and graphics*

Decorative frame, choice = roses, ivy, bamboo, waves, dots, stars, hearts….

Engine commands: `studio.select_top`, `filter.render.pictureFrame`
Choice menu: vineWithFlowers, vineWithLeaves, ivy, roses, daisies, berries, bamboo, waves, zigzag, dots, rope, scallops, doubleLine, snowflakes, stars, hearts

### `color_overlay` — Color overlay

*procedure · stage: text and graphics*

Semi-transparent color layer over the image (color, value = opacity %).

Engine commands: `studio.select_insert`, `layer.newFillLayer.solidColor`, `layer.setProps`

### `letterbox` — Cinema letterbox bars

*procedure · stage: text and graphics*

Black cinema bars at the top and bottom for a widescreen film frame (aspect, 2.39:1 by default).

Engine commands: `studio.select_top`, `layer.new.layer`, `select.rect`, `edit.fill`, `select.deselect`
Answers: “add cinematic black bars”

## Layers

### `layer_opacity` — Layer opacity

*procedure · stage: layer housekeeping*

Change an existing layer’s opacity (object = layer name, value = %).

Engine commands: `layer.setProps`

### `layer_visibility` — Layer visibility

*procedure · stage: layer housekeeping*

Hide (decrease) or show (increase) an existing layer (object = layer name).

Engine commands: `layer.setProps`

### `layer_delete` — Layer delete

*procedure · stage: layer housekeeping*

Delete an existing layer (object = layer name).

Engine commands: `layer.delete`

### `layer_rename` — Layer rename

*procedure · stage: layer housekeeping*

Rename an existing layer (object = old name, text = new name).

Engine commands: `layer.renameLayer`

### `layer_blend` — Layer blend

*procedure · stage: layer housekeeping*

Set an existing layer’s blend mode (object = layer name, choice = mode).

Engine commands: `layer.setProps`

## AI content

### `generate` — Paint new content with AI

*procedure · stage: AI layers*

New content painted by AI as its own layer: add an object or person, replace the sky with a new one, change clothing or materials (target says where).

Engine commands: `studio.ai_layer`
Needs the AI content model.
Answers: “add a small white sailboat”; “replace the sky with a sunset”

### `other` — Another PhotoCraft feature

*procedure · stage: last resort*

Any other PhotoCraft capability not listed (describe it in choice).

