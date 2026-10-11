"""Starting programs the person works in, so they outlive the studio."""

import subprocess
import sys
from pathlib import Path

import psutil

# Apps the person works in. The engine starts them, so they are its child processes, but
# stopping the engine must never close them (unsaved work). photocraft-cli is the engine's own.
APPS = {'krita', 'photocraft'}


def is_app(process):
    try:
        return Path(process.name()).stem.lower() in APPS
    except psutil.Error:
        return False


def own_family(parent):
    """A process and everything it started, except the apps the person works in (and what they started)."""
    family = [parent]
    try:
        children = parent.children()
    except psutil.Error:
        return family
    for child in children:
        if not is_app(child):
            family += own_family(child)
    return family


def launch_detached(args, **options):
    """Start an app (Krita, PhotoCraft) that must keep running when the studio closes.

    The desktop app ties the engine to its window (a Windows job object), so anything the
    engine starts would be closed with it. Breaking away keeps unsaved work open; when the
    surrounding job does not allow that, the app still starts, just without breaking away.
    """
    options.setdefault('stdout', subprocess.DEVNULL)
    options.setdefault('stderr', subprocess.DEVNULL)
    if sys.platform != 'win32':
        return subprocess.Popen(args, start_new_session=True, **options)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
    except OSError:
        return subprocess.Popen(args, creationflags=flags, **options)
