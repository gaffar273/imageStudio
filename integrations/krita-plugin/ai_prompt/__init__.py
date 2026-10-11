"""AI panel for Krita: edit pictures by prompt with Krita's tools and Image Studio's
models, and let Image Studio's browser app drive Krita (see link.py)."""
from krita import DockWidgetFactory, DockWidgetFactoryBase, Krita
from .docker import AIPromptDocker
from .link import LinkExtension

app = Krita.instance()
app.addExtension(LinkExtension(app))
# Krita 6 (PyQt6) only accepts the scoped enum name; Krita 5 also has the short one.
_position = getattr(getattr(DockWidgetFactoryBase, 'DockPosition', DockWidgetFactoryBase), 'DockRight')
app.addDockWidgetFactory(DockWidgetFactory('ai_prompt', _position, AIPromptDocker))
