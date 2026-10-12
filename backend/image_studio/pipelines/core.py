"""What a pipeline is, and the registry that holds every one of them.

A pipeline is a fixed, deterministic procedure for one kind of professional edit: what must be
found in the picture, what must be measured, which PhotoCraft commands run in which order with
which settings, and how the result is checked. The vision model never writes any of that. It
only reads the request and chooses pipelines by name from the registry, filling a few slots from
closed menus (target, direction, strength, position, a color name, the exact words of a title).

There are two kinds:

- **Procedures** build engine steps themselves (``build``). “Crop to 4:5 around the cat” is the
  ``crop_aspect`` procedure: the largest 4:5 rectangle, computed from the document size and the
  cat's measured box.
- **Workflows** are a professional job made of procedures (``expand``). “Get this product photo
  ready for Amazon” is the ``product_marketplace`` workflow: a cut-out onto pure white, a contact
  shadow, a square crop with even margins and a 2000 px export. Each part runs as its own
  procedure, in the retoucher's order, with its own checks.

Stages order every pipeline the way a retoucher works, whatever order the request lists them in:
layer housekeeping, pixel retouching, raw development, AI layers, adjustments, effects and
cut-outs while every object is still whole in the frame, then geometry, then text and graphics
on the final canvas, then output settings.
"""

from dataclasses import dataclass, field

STAGES = ['layer', 'retouch', 'develop', 'ai', 'adjust', 'effect', 'cutout', 'geometry', 'graphics', 'output',
          'expert']

CATEGORIES = [
    ('workflow', 'Professional workflows'),
    ('correct', 'Correction'),
    ('light', 'Light and tone'),
    ('color', 'Color'),
    ('look', 'Looks and film'),
    ('portrait', 'Portrait retouching'),
    ('retouch', 'Retouching and objects'),
    ('background', 'Cut-outs and backgrounds'),
    ('effect', 'Effects'),
    ('framing', 'Framing and geometry'),
    ('output', 'Size, print and export'),
    ('graphics', 'Text and graphics'),
    ('layers', 'Layers'),
    ('ai', 'AI content'),
]


@dataclass(frozen=True)
class Pipeline:
    """One registered pipeline. ``build(builder, index, edit)`` adds engine steps (procedures);
    ``expand(edit, prompt)`` returns the edits a workflow is made of (workflows)."""

    id: str
    title: str
    category: str
    stage: str
    summary: str  # what the planner reads when choosing; says which slots mean what
    build: object = None
    expand: object = None
    options: tuple = ()  # the menu for the `choice` slot, when the pipeline has one
    # True when target words say what to keep or cut around (a crop around the cat, a cut-out of
    # the subject), so the subject is found even when the target is the whole image.
    whole_picture: bool = False
    finds: object = None  # edit -> [queries] to locate, overriding the target rule
    measures: tuple = ()  # analyses the build reads (see pipelines.measure)
    ai: bool = False  # needs the AI content model (FLUX Kontext)
    area_safe: bool = False  # can be limited to a marked area
    steps: tuple = ()  # a workflow's procedure ids, for the catalog
    examples: tuple = ()  # requests this pipeline answers, for the catalog and the bench
    menu: bool = True  # offered to the planner (False: only reached through rules or workflows)
    tags: tuple = field(default=())
    # What the request must say for this pipeline to fit: a regular expression over the edit's
    # words, or a function of the edit. A planner choice that does not fit is asked again
    # (“make the water more turquoise” once came back as the colour-splash workflow).
    requires: object = None

    @property
    def workflow(self):
        return self.expand is not None

    def fits(self, edit):
        if self.requires is None:
            return True
        if callable(self.requires):
            return bool(self.requires(edit))
        import re

        return bool(re.search(self.requires, f'{edit.get("quote", "")} {edit.get("choice", "")}', re.IGNORECASE))


REGISTRY = {}


def register(pipeline):
    if pipeline.id in REGISTRY:
        raise ValueError(f'Pipeline {pipeline.id} is registered twice.')
    if pipeline.stage not in STAGES and pipeline.stage != 'workflow':
        raise ValueError(f'Pipeline {pipeline.id} has an unknown stage {pipeline.stage}.')
    if pipeline.category not in dict(CATEGORIES):
        raise ValueError(f'Pipeline {pipeline.id} has an unknown category {pipeline.category}.')
    if (pipeline.build is None) == (pipeline.expand is None):
        raise ValueError(f'Pipeline {pipeline.id} needs exactly one of build or expand.')
    REGISTRY[pipeline.id] = pipeline
    return pipeline


def procedure(id, title, category, stage, summary, **extra):
    """Register the decorated function as a procedure's build."""
    def decorate(function):
        register(Pipeline(id=id, title=title, category=category, stage=stage, summary=summary, build=function,
                          **extra))
        return function
    return decorate


def workflow(id, title, category, summary, steps, **extra):
    """Register the decorated function as a workflow's expansion into procedures."""
    def decorate(function):
        register(Pipeline(id=id, title=title, category=category, stage='workflow', summary=summary,
                          expand=function, steps=tuple(steps), **extra))
        return function
    return decorate
