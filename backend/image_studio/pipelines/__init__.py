"""The pipeline engine: every professional edit as a named, deterministic pipeline.

    from image_studio.pipelines import REGISTRY, get, catalog

See core.py for what a pipeline is, library/ for every pipeline, measure.py for the analyses
they read, and models/ for how any language or vision model is connected to choose them.
"""

from .core import CATEGORIES, REGISTRY, STAGES, Pipeline  # noqa: F401
from . import library  # noqa: F401,E402  (registers every pipeline)


def get(pipeline_id):
    return REGISTRY.get(pipeline_id)


def menu():
    """The pipelines offered to the planner, grouped by category, in registry order."""
    grouped = {key: [] for key, _ in CATEGORIES}
    for pipeline in REGISTRY.values():
        if pipeline.menu:
            grouped[pipeline.category].append(pipeline)
    return [(key, title, grouped[key]) for key, title in CATEGORIES if grouped[key]]


def catalog():
    """A plain description of every pipeline, for the interface, the API and the documentation."""
    return [{
        'id': p.id, 'title': p.title, 'category': p.category, 'category_title': dict(CATEGORIES)[p.category],
        'stage': p.stage, 'kind': 'workflow' if p.workflow else 'procedure', 'summary': p.summary,
        'options': list(p.options), 'steps': list(p.steps), 'measures': list(p.measures), 'ai': p.ai,
        'area_safe': p.area_safe, 'examples': list(p.examples),
    } for p in REGISTRY.values()]
