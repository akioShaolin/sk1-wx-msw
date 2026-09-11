# Copyright (C) 2026 sK1 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate a launcher overlay before touching an existing Python runtime."""
import ctypes
import hashlib
import os
import shutil
import struct
import sys
import zipfile


def wide_path(path):
    path = os.path.abspath(path)
    if not isinstance(path, type(u'')):
        path = path.decode(sys.getfilesystemencoding())
    return path


def binary_metadata(path, version=False):
    try:
        with open(path, 'rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('missing MZ signature')
            stream.seek(60)
            offset = struct.unpack('<I', stream.read(4))[0]
            stream.seek(offset)
            if stream.read(4) != b'PE\0\0':
                raise ValueError('missing PE signature')
            machine = struct.unpack('<H', stream.read(2))[0]
        if machine not in (0x14c, 0x8664):
            raise ValueError('unsupported PE machine %#x' % machine)
        if not version:
            return machine, None
        api = ctypes.WinDLL('version', use_last_error=True)
        size_fn = api.GetFileVersionInfoSizeW
        size_fn.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
        size_fn.restype = ctypes.c_uint32
        read_fn = api.GetFileVersionInfoW
        read_fn.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                           ctypes.c_uint32, ctypes.c_void_p]
        read_fn.restype = ctypes.c_int
        query = api.VerQueryValueW
        query.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                          ctypes.POINTER(ctypes.c_void_p),
                          ctypes.POINTER(ctypes.c_uint)]
        query.restype = ctypes.c_int
        size = size_fn(wide_path(path), None)
        if not size:
            raise ValueError('missing file version resource')
        data = ctypes.create_string_buffer(size)
        if not read_fn(wide_path(path), 0, size, data):
            raise ctypes.WinError(ctypes.get_last_error())
        pointer, length = ctypes.c_void_p(), ctypes.c_uint()
        if not query(data, u'\\', ctypes.byref(pointer), ctypes.byref(length)):
            raise ValueError('missing fixed file version')
        if length.value < 52:
            raise ValueError('truncated fixed file version')
        fields = struct.unpack('<13I', ctypes.string_at(pointer, 52))
        if fields[0] != 0xfeef04bd:
            raise ValueError('invalid fixed file version signature')
        ms, ls = fields[2:4]
        return machine, (ms >> 16, ms & 65535, ls >> 16, ls & 65535)
    except (IOError, OSError, ValueError, struct.error) as error:
        raise RuntimeError('Cannot verify binary metadata for %r: %s' % (path, error))


def loaded_python_dll():
    # python.exe need not have version resources; inspect its loaded DLL.
    if sys.version_info[:2] != (2, 7) or not hasattr(sys, 'dllhandle'):
        raise RuntimeError('Launcher assembly requires Windows Python 2.7')
    api = ctypes.WinDLL('kernel32', use_last_error=True).GetModuleFileNameW
    api.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    api.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    count = api(sys.dllhandle, buffer, len(buffer))
    if not count or count >= len(buffer):
        raise RuntimeError('Cannot identify the build interpreter Python DLL')
    return buffer.value


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.sha256(stream.read()).digest()


def overlay_launcher(output, destination, executable, interpreter,
                     metadata=binary_metadata, interpreter_dll=None):
    """Validate all inputs first; preserve every pre-existing runtime file.

    metadata/interpreter_dll injection is for deterministic simulated tests.
    Only sk1.exe and, when needed, an identical copy of the target's own
    _ctypes.pyd at the executable root are allowed to be overlaid.
    """
    target_dll = os.path.join(destination, 'python27.dll')
    identity = metadata(target_dll, True)
    machine, version = identity
    if version is None or version[:2] != (2, 7):
        raise RuntimeError('Target must have verifiable Python 2.7 version metadata')
    if interpreter_dll is None:
        interpreter_dll = loaded_python_dll()
    for path in (interpreter_dll, os.path.join(output, 'python27.dll')):
        if metadata(path, True) != identity:
            raise RuntimeError('Python version/architecture mismatch: %r versus %r. '
                               'Build with the exact target Python runtime.' %
                               (path, target_dll))
    launcher = os.path.join(output, executable)
    for path in (interpreter, launcher, os.path.join(destination, 'sk1.exe')):
        if metadata(path, False)[0] != machine:
            raise RuntimeError('PE architecture mismatch: %r versus target' % path)

    def target_dependency(name, content_hash):
        candidates = [os.path.join(destination, name),
                      os.path.join(destination, 'libs', name),
                      os.path.join(destination, 'dlls', name)]
        for candidate in candidates:
            if os.path.isfile(candidate):
                if metadata(candidate, False)[0] != machine:
                    raise RuntimeError('Dependency architecture mismatch: %r' % candidate)
                if digest(candidate) != content_hash:
                    raise RuntimeError('Dependency differs from build: %r. '
                                       'Use the matching runtime/toolchain.' % candidate)
                return candidate
        raise RuntimeError('Target lacks verified dependency %r; no files replaced' % name)

    additions = []
    ctypes_verified = False
    for folder, dirs, files in os.walk(output):
        for name in files:
            relative = os.path.relpath(os.path.join(folder, name), output)
            if relative in (executable, 'python27.dll', 'w9xpopen.exe'):
                continue
            if name.lower().endswith(('.pyd', '.dll')):
                source = os.path.join(folder, name)
                if metadata(source, False)[0] != machine:
                    raise RuntimeError('Generated dependency architecture mismatch: %r' % source)
                # CRT subdirectories retain their layout. Existing root/libs/dlls
                # candidates are also valid for DLLs already loaded by Python.
                candidate = target_dependency(relative, digest(source))
                if relative == '_ctypes.pyd':
                    ctypes_verified = True
                if relative == '_ctypes.pyd' and candidate != os.path.join(destination, relative):
                    additions.append((candidate, os.path.join(destination, relative)))
            elif name.lower().endswith('.manifest'):
                target = os.path.join(destination, relative)
                if not os.path.isfile(target) or digest(target) != digest(os.path.join(folder, name)):
                    raise RuntimeError('Target CRT manifest missing or different: %r' % target)
            else:
                raise RuntimeError('Unverified launcher artifact: %r' % relative)
    # x86 bundles native extensions in the EXE. Validate those as well,
    # rather than assuming an interpreter version guarantees identical DLLs.
    with zipfile.ZipFile(launcher) as archive:
        for name in archive.namelist():
            if name.lower().endswith(('.pyd', '.dll')):
                target_dependency(name.replace('/', os.sep),
                                  hashlib.sha256(archive.read(name)).digest())
                if name == '_ctypes.pyd':
                    ctypes_verified = True
    if not ctypes_verified:
        raise RuntimeError('Launcher has no verified _ctypes.pyd for Unicode bootstrap')
    # All rejection paths above precede any destination write.
    for source, target in additions:
        shutil.copy2(source, target)
    shutil.copy2(launcher, os.path.join(destination, 'sk1.exe'))
