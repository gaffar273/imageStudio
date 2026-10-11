"""What this computer can run: graphics cards, memory and processor, on Windows and Linux.

Only the standard library and psutil are used, so the desktop app can ask without loading
any model. NVIDIA cards are read through nvidia-smi (exact memory and live use); other
cards are listed from the system so the app can explain what they can and cannot do.
"""

import functools
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import psutil

GB = 1024**3
VENDORS = {'10de': 'NVIDIA', '1002': 'AMD', '8086': 'Intel'}
VIRTUAL = ('basic display', 'basic render', 'virtual', 'parsec', 'remote', 'mirror', 'indirect')


def quiet():
    """No console window flashing up from the windowed app."""
    return dict(creationflags=subprocess.CREATE_NO_WINDOW) if sys.platform == 'win32' else {}


def number(value):
    try:
        return float(value)
    except ValueError:
        return None  # nvidia-smi says [N/A] on some laptops


def nvidia():
    """Live state of each NVIDIA card; [] when there is none or no driver."""
    tool = shutil.which('nvidia-smi')
    if not tool:
        return []
    query = 'index,name,memory.total,memory.used,utilization.gpu,driver_version'
    try:
        output = subprocess.run(
            [tool, f'--query-gpu={query}', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5, check=False, **quiet(),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    cards = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(',')]
        if len(parts) != 6 or number(parts[2]) is None:
            continue
        cards.append(
            dict(
                name=parts[1],
                vendor='NVIDIA',
                vram_gb=round(number(parts[2]) / 1024, 1),
                used_gb=round((number(parts[3]) or 0) / 1024, 2),
                load=number(parts[4]),
                driver=parts[5],
                integrated=False,
            )
        )
    return cards


def windows_adapters():
    import winreg

    found = []
    path = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        return found
    with root:
        index = 0
        while True:
            try:
                child = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not child.isdigit():
                continue
            try:
                with winreg.OpenKey(root, child) as key:
                    name = winreg.QueryValueEx(key, 'DriverDesc')[0]
                    device = winreg.QueryValueEx(key, 'MatchingDeviceId')[0].lower()
                    try:
                        memory = int(winreg.QueryValueEx(key, 'HardwareInformation.qwMemorySize')[0])
                    except (OSError, ValueError, TypeError):
                        memory = 0
            except OSError:
                continue
            vendor = device.split('ven_')[1][:4] if 'ven_' in device else ''
            found.append((name, VENDORS.get(vendor, 'Other'), memory / GB))
    return found


def linux_adapters():
    found = []
    for card in sorted(Path('/sys/class/drm').glob('card[0-9]')):
        device = card / 'device'
        try:
            vendor = VENDORS.get((device / 'vendor').read_text().strip().removeprefix('0x'), 'Other')
            slot = dict(
                line.split('=', 1) for line in (device / 'uevent').read_text().splitlines() if '=' in line
            ).get('PCI_SLOT_NAME', '')
        except OSError:
            continue
        name = f'{vendor} graphics'
        if slot and shutil.which('lspci'):
            try:
                text = subprocess.run(['lspci', '-mm', '-s', slot], capture_output=True, text=True, timeout=5, check=False)
                fields = text.stdout.split('"')
                if len(fields) > 5:
                    name = f'{fields[3]} {fields[5]}'.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            memory = int((device / 'mem_info_vram_total').read_text()) / GB
        except (OSError, ValueError):
            memory = 0
        found.append((name, vendor, memory))
    return found


@functools.cache
def system_adapters():
    """Every display adapter the system reports (read once; it does not change while running)."""
    found = windows_adapters() if sys.platform == 'win32' else linux_adapters()
    return [item for item in found if not any(word in item[0].lower() for word in VIRTUAL)]


def graphics():
    """All graphics cards, NVIDIA first with live figures, then the others."""
    cards = nvidia()
    if not cards:  # no driver tools: fall back to what the system reports
        cards = [
            dict(name=name, vendor=vendor, vram_gb=round(memory, 1) if memory else None, used_gb=None,
                 load=None, driver=None, integrated=False)
            for name, vendor, memory in system_adapters()
            if vendor == 'NVIDIA'
        ]
    for name, vendor, memory in system_adapters():
        if vendor == 'NVIDIA':
            continue
        lower = name.lower()
        integrated = (vendor == 'Intel' and 'arc' not in lower) or (vendor == 'AMD' and memory < 2)
        cards.append(
            dict(name=name, vendor=vendor, vram_gb=round(memory, 1) if memory else None, used_gb=None,
                 load=None, driver=None, integrated=integrated)
        )
    return cards


def verdict(cards):
    """A tier and one plain sentence about local generation on these cards."""
    usable = [card for card in cards if card['vendor'] == 'NVIDIA' and card['vram_gb']]
    if usable:
        best = max(usable, key=lambda card: card['vram_gb'])
        name, memory = best['name'], best['vram_gb']
        if memory >= 11.5:
            return 'great', f'{name} ({memory:.0f} GB) runs every local model with room to spare.'
        if memory >= 7.5:
            return 'good', (
                f'{name} ({memory:.0f} GB) runs every local model. The largest ones use '
                'memory-saving modes, so they take a little longer.'
            )
        if memory >= 5.5:
            return 'limited', (
                f'{name} ({memory:.0f} GB) should run the quicker models. The largest editing '
                'models may not fit.'
            )
        return 'cloud', f'{name} ({memory:.0f} GB) has too little video memory for the local models.'
    discrete = [card for card in cards if not card['integrated']]
    if discrete:
        return 'cloud', (
            f'{discrete[0]["name"]} is not supported for local generation yet. The engine '
            'currently needs an NVIDIA graphics card.'
        )
    return 'cloud', 'No graphics card suitable for local generation was found.'


def cpu_name():
    if sys.platform == 'win32':
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0'
            ) as key:
                return winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError:
            pass
    else:
        try:
            for line in Path('/proc/cpuinfo').read_text().splitlines():
                if line.startswith('model name'):
                    return line.split(':', 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or 'Unknown processor'


def summary():
    cards = graphics()
    tier, text = verdict(cards)
    return dict(
        system=f'{platform.system()} {platform.release()}',
        cpu=cpu_name(),
        cores=psutil.cpu_count(logical=False),
        threads=psutil.cpu_count(),
        ram_gb=round(psutil.virtual_memory().total / GB, 1),
        gpus=cards,
        tier=tier,
        verdict=text,
    )


def usage():
    """Live figures for a status meter: NVIDIA video memory and load, system memory."""
    memory = psutil.virtual_memory()
    return dict(
        gpus=nvidia(),
        ram_used_gb=round(memory.used / GB, 1),
        ram_gb=round(memory.total / GB, 1),
    )
