"""Starting programs the person works in, so they outlive the studio."""

import subprocess
import sys


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
