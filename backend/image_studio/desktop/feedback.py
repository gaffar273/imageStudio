"""Reporting a problem or a picture: a GitHub issue, filled in for the person to read and send.

Pictures are made by generative AI from what people type, so anyone must be able to report one
that is inappropriate (Microsoft Store policy 11.16). Nothing is sent from the app: the issue
opens in the browser, where the person sees everything before submitting it, and adds the
picture only if they choose to.
"""

import json
import re
from urllib.parse import urlencode

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from image_studio.core import paths

ISSUES = 'https://github.com/gaffar273/imageStudio/issues/new'
PUBLIC = 'This opens a public GitHub issue in your browser. You see it before it is sent and can change anything.'


def version():
    """'2.0.0' in an installed copy (build.json); '2.0.0 (source)' when run from the repository."""
    try:
        return json.loads(paths.BUILD_FILE.read_text(encoding='utf-8'))['version']
    except (OSError, ValueError, KeyError):
        pass
    try:
        text = (paths.ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        return re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1) + ' (source)'
    except (OSError, AttributeError):
        return 'unknown'


def footer():
    return f'\n\n---\nImage Studio {version()}' + (' (Microsoft Store)' if paths.PACKAGE else '')


def issue_url(title, body):
    return f'{ISSUES}?{urlencode(dict(title=title, body=body + footer()))}'


def picture_report(prompt, model):
    body = (
        'What is wrong with this picture?\n\n'
        '(For example: offensive, sexual, violent, or it shows a real person. Attaching the picture is up '
        'to you.)\n\n'
        f'Prompt: {prompt or "none saved"}\n'
        f'Model: {model or "unknown"}'
    )
    return issue_url('Report a picture', body)


def problem_report():
    return issue_url('', 'What happened, and what did you expect?\n')


def open_report(url):
    QDesktopServices.openUrl(QUrl(url))
