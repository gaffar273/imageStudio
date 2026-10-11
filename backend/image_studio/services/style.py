"""Photo style: steer the models away from the polished "AI look".

Image models are tuned on pictures people rated as beautiful, so by default they make
airbrushed skin, studio light, blurred backgrounds and rich colours. Natural photo asks
for what ordinary cameras record instead, and lists the glossy look as something to avoid.
"""

STYLES = ['Natural photo', 'Polished']
DEFAULT_STYLE = 'Natural photo'

# SDXL reads only the first 77 tokens, so for it the important words go first and stay short.
SDXL_PREFIX = 'candid unretouched photo, '
SDXL_SUFFIX = ', natural skin texture with pores, true-to-life colors, background in focus'
# Z-Image reads long prompts with a language model, so it gets full sentences.
ZIMAGE_SUFFIX = (
    ' Candid, unretouched photo taken with an ordinary camera: natural uneven light, real skin '
    'texture with pores and small blemishes, slightly imperfect framing, the background in focus '
    'and true-to-life colors. Not airbrushed, not a glamour or studio shot.'
)
NEGATIVE = (
    'airbrushed, retouched, beauty filter, glamour, oversaturated, HDR, '
    'heavy bokeh, perfect symmetry, studio lighting'
)


def apply(prompt, model, style):
    """The prompt the model is given for `style`."""
    if style != 'Natural photo':
        return prompt
    if model == 'accurate':
        return prompt.rstrip() + ZIMAGE_SUFFIX
    return SDXL_PREFIX + prompt.strip() + SDXL_SUFFIX


def negative(negative_prompt, style):
    """The things-to-avoid text for `style` (used by the SDXL models only)."""
    if style != 'Natural photo' or 'airbrushed' in negative_prompt:
        return negative_prompt
    return f'{NEGATIVE}, {negative_prompt}' if negative_prompt.strip() else NEGATIVE
