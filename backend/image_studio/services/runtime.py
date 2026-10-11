"""A shared admission lock prevents browser and Krita GPU sessions overlapping."""

import threading

render_session = threading.Lock()
