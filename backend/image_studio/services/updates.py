"""Find public stable app releases; checking never downloads or runs an installer."""

import json
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

from image_studio.core import paths
from image_studio.core.version import current

REPO = 'https://github.com/gaffar273/imageStudio'
RELEASES = REPO + '/releases'
API = 'https://api.github.com/repos/gaffar273/imageStudio/releases?per_page=20'
MAX_RESPONSE = 2_000_000
CHECK_SECONDS = 6 * 60 * 60
REMIND_SECONDS = 24 * 60 * 60


class UpdateError(ValueError):
    pass


def number(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+[0-9A-Za-z.-]+)?', str(value))
    return tuple(map(int, match.groups())) if match else None


def select_release(releases, installed, platform):
    version = number(installed)
    if version is None:
        raise UpdateError(
            'The installed version could not be identified. Download the latest version from Releases.'
        )
    if not isinstance(releases, list):
        raise UpdateError('GitHub returned an unreadable release list. Try again later.')
    stable = [
        (number(item.get('tag_name')), item)
        for item in releases
        if isinstance(item, dict)
        and item.get('draft') is False
        and item.get('prerelease') is False
        and number(item.get('tag_name'))
    ]
    result = dict(current=installed, page=RELEASES)
    if not stable:
        return dict(result, status='unavailable', message='No public stable release is available yet.')
    latest, release = max(stable, key=lambda item: item[0])
    tag = release['tag_name']
    latest_text = '.'.join(map(str, latest))
    result.update(latest=latest_text, page=f'{RELEASES}/tag/{quote(tag, safe="")}')
    if latest <= version:
        return dict(
            result, status='current', message=f'You’re up to date. Image Studio {installed} is installed.'
        )
    filename = (
        f'ImageStudio-{latest_text}-Setup.exe'
        if platform == 'win32'
        else (f'image-studio-{latest_text}-linux-x86_64.tar.gz' if platform == 'linux' else None)
    )
    expected = f'{RELEASES}/download/{quote(tag, safe="")}/{filename}' if filename else None
    assets = release.get('assets') or []
    if not isinstance(assets, list):
        raise UpdateError('GitHub returned unreadable installer information. Try again later.')
    asset = next(
        (
            asset
            for asset in assets
            if isinstance(asset, dict)
            and asset.get('name') == filename
            and asset.get('browser_download_url') == expected
            and isinstance(asset.get('size'), int)
            and asset['size'] > 0
            and asset.get('state', 'uploaded') == 'uploaded'
        ),
        None,
    )
    if not asset:
        return dict(
            result,
            status='unavailable',
            message=f'Version {latest_text} has no installer for this computer yet.',
        )
    return dict(
        result,
        status='available',
        download=expected,
        size=asset['size'],
        message=f'Image Studio {latest_text} is available. You have {installed}.',
    )


def check():
    installed = current()
    if paths.PACKAGE:
        return dict(status='store', current=installed, message='Updates are managed by Microsoft Store.')
    request = urllib.request.Request(
        API,
        headers={
            'User-Agent': 'ImageStudio-update-check',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read(MAX_RESPONSE + 1)
        if len(payload) > MAX_RESPONSE:
            raise UpdateError('The release response was too large. View Releases or try again later.')
        return select_release(json.loads(payload), installed, sys.platform)
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429}:
            raise UpdateError(
                'Update checks are temporarily limited. Try again later or open Releases.'
            ) from exc
        raise UpdateError('Could not check for updates. Check your connection and try again.') from exc
    except (OSError, ValueError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError('Could not check for updates. Check your connection and try again.') from exc
