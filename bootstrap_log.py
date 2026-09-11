# Copyright (C) 2026 sK1 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Python 2.7 bootstrap helpers, embedded before py2exe's common boot code."""

import os


def bootstrap_ctypes():
    # bundle_files=2 stores _ctypes.pyd inside the executable. A diagnostic
    # can occur before py2exe's ordinary importer-install code object runs.
    install = globals().get('_sk1_bootstrap_importer')
    if install is not None:
        install()
    import ctypes
    return ctypes


def windows_environment(name, kernel=None):
    ctypes = bootstrap_ctypes()
    if kernel is None:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    read = kernel.GetEnvironmentVariableW
    read.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    read.restype = ctypes.c_uint32
    size = 128
    for attempt in range(8):
        buffer = ctypes.create_unicode_buffer(size)
        ctypes.set_last_error(0)
        count = read(name, buffer, size)
        if not count:
            error = ctypes.get_last_error()
            if error in (0, 203):  # Empty or ERROR_ENVVAR_NOT_FOUND.
                return None
            raise ctypes.WinError(error)
        if count < size:
            return buffer.value
        size = count  # Required size includes the terminating NUL.
    raise OSError('Environment variable kept changing: %s' % name)


def bootstrap_error_text(error):
    try:
        return unicode(error)
    except UnicodeError:
        # Python 2 Windows exceptions can contain localized byte messages.
        # repr preserves those bytes as escapes without damaging path data.
        return repr(error).decode('ascii')
    except NameError:
        return str(error)


def bootstrap_message_box(hwnd, text, title):
    # The original C binding can coerce Unicode to ASCII. Keep the same
    # notification semantics with the Windows wide-character API.
    ctypes = bootstrap_ctypes()
    alert = ctypes.windll.user32.MessageBoxW
    alert.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                      ctypes.c_wchar_p, ctypes.c_uint]
    alert.restype = ctypes.c_int
    return alert(hwnd, bootstrap_error_text(text),
                 bootstrap_error_text(title), 0)


def open_bootstrap_log(environ=None, pid=None, reader=None):
    """Open a per-process log, never falling back to the executable or cwd."""
    if reader is None:
        reader = environ.get if environ is not None else windows_environment
    if pid is None:
        pid = os.getpid()
    errors = []
    for variable in (u'LOCALAPPDATA', u'TEMP'):
        try:
            base = reader(variable)
            if not base or not os.path.isabs(base) or not os.path.splitdrive(base)[0]:
                errors.append(u'%s is missing or not absolute' % variable)
                continue
            directory = os.path.join(base, u'sK1', u'logs')
            path = os.path.join(directory, u'sk1-bootstrap-%s.log' % pid)
            try:
                os.makedirs(directory)
            except OSError:
                if not os.path.isdir(directory):
                    raise
            return open(path, 'a'), path
        except (IOError, OSError) as error:
            errors.append(u'%s: %s' % (variable, bootstrap_error_text(error)))
    raise IOError(u'Cannot open bootstrap log: ' + u'; '.join(errors))
