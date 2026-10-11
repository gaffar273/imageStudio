"""Copy the AI Prompt panel into Krita's plugin folder and switch it on.

Krita reads Python plugins from %APPDATA%\\krita\\pykrita (Linux: ~/.local/share/krita/pykrita)
and remembers which are enabled in %LOCALAPPDATA%\\kritarc (Linux: ~/.config/kritarc). Close
Krita before running this; it rewrites kritarc when it exits."""

import os
import shutil
from pathlib import Path

from image_studio.core.paths import ROOT

SOURCE = ROOT / 'integrations' / 'krita-plugin'
if os.name == 'nt':
    PYKRITA = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming') / 'krita' / 'pykrita'
    KRITARC = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'kritarc'
else:
    PYKRITA = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'krita' / 'pykrita'
    KRITARC = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'kritarc'
SETTING = 'enable_ai_prompt=true'


def enable():
    """Set enable_ai_prompt=true in kritarc's [python] section, leaving every other line
    as it is. (kritarc starts with settings outside any section, which INI parsers reject.)"""
    lines = KRITARC.read_text(encoding='utf-8').splitlines() if KRITARC.exists() else []
    lines = [line for line in lines if not line.startswith('enable_ai_prompt=')]
    if '[python]' in lines:
        lines.insert(lines.index('[python]') + 1, SETTING)
    else:
        lines += ['', '[python]', SETTING]
    KRITARC.parent.mkdir(parents=True, exist_ok=True)
    KRITARC.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    PYKRITA.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SOURCE / 'ai_prompt',
        PYKRITA / 'ai_prompt',
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__'),
    )
    shutil.copy2(SOURCE / 'ai_prompt.desktop', PYKRITA / 'ai_prompt.desktop')
    enable()
    print(
        f'Installed the AI panel to {PYKRITA / "ai_prompt"}. It opens with Krita '
        '(or Settings > Dockers > AI).'
    )


if __name__ == '__main__':
    main()
