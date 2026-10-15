"""Every registered pipeline, one module per area of the craft. Importing this package registers
them all; the order here is the order of the planner's menu within each category."""

from . import (adjust, ai, camera_develop, cutout, develop, effects, framing, graphics, layers, looks,  # noqa: F401
               retouch, workflows)
