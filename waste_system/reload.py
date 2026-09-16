"""waste_system/reload.py
Development-only live-reload endpoint.

Django's ``runserver`` auto-reloads on *.py changes but nothing tells the
browser to refresh when a template or static asset changes. This module
exposes a tiny JSON endpoint (``/__dev__/livereload/``) that returns a
signature of the source tree — the newest modification time among
``templates/``, ``locale/``, ``static/`` and every ``*.py`` file. base.html
polls it every ~1.5s while DEBUG=True and issues a ``location.reload()`` the
moment the signature changes, so edits to templates, CSS/JS and Python all
appear live with no manual refresh.

Only mounted when DEBUG=True (see waste_system/urls.py); never in production.
"""

import os

from django.conf import settings
from django.http import JsonResponse

# Directories that must never feed the signature: generated output, vendor
# trees and large binary blobs (torch model weights, media uploads, backups)
# all live here and changing them is not a source edit.
_SKIP_DIRS = {
    '.git',
    '.venv',
    'venv',
    '__pycache__',
    '.pytest_cache',
    'media',
    'staticfiles',
    'node_modules',
    'ml_models',
    'backups',
}


def _walk_mtime(relative_root, extension=None):
    """Newest mtime among files (and their directories) under ``relative_root``.

    Directories are included so a deletion bumps the signature too — deleting
    a file only changes its parent directory's mtime, not any surviving file.
    """
    root = str(settings.BASE_DIR / relative_root)
    if not os.path.isdir(root):
        return 0.0
    latest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if extension is not None and not name.endswith(extension):
                continue
            path = os.path.join(dirpath, name)
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if mtime > latest:
                latest = mtime
        for dirname in dirnames:
            path = os.path.join(dirpath, dirname)
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if mtime > latest:
                latest = mtime
        try:
            mtime = os.stat(dirpath).st_mtime
        except OSError:
            mtime = 0.0
        if mtime > latest:
            latest = mtime
    return latest


def live_signature():
    """Signature of the whole editable tree, as a stable string."""
    outputs = [_walk_mtime(name) for name in ('templates', 'locale', 'static')]
    # *.py anywhere in the project (minus _SKIP_DIRS) drives runserver's
    # auto-reloader, so bumping them should refresh open tabs as well.
    outputs.append(_walk_mtime('.', extension='.py'))
    return '%.6f' % max(outputs)


def livereload_ping(request):
    """GET only. Returns a no-store JSON signature for the dev poller."""
    response = JsonResponse({'sig': live_signature()})
    response['Cache-Control'] = 'no-store'
    return response