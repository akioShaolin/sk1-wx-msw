# Copyright (C) 2026 sK1 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Overlay rejection simulations plus read-only native PE metadata checks."""
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile

from bootstrap_runtime import binary_metadata, digest, overlay_launcher


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='sk1-overlay-test-')
        self.target = os.path.join(self.root, 'target')
        self.output = os.path.join(self.root, 'output')
        os.makedirs(os.path.join(self.target, 'libs'))
        os.makedirs(self.output)
        self.interpreter = os.path.join(self.root, 'python.exe')
        self.dll = os.path.join(self.root, 'python27.dll')
        for path, data in ((self.interpreter, b'interpreter'),
                           (self.dll, b'build dll'),
                           (os.path.join(self.target, 'python27.dll'), b'keep target dll'),
                           (os.path.join(self.target, 'sk1.exe'), b'old launcher'),
                           (os.path.join(self.output, 'python27.dll'), b'generated dll'),
                           (os.path.join(self.target, 'libs', '_ctypes.pyd'), b'ctypes'),
                           (os.path.join(self.output, '_ctypes.pyd'), b'ctypes')):
            with open(path, 'wb') as stream:
                stream.write(data)
        self.executable = 'sk1.exe'
        with zipfile.ZipFile(os.path.join(self.output, self.executable), 'w') as archive:
            archive.writestr('os.pyc', b'fixture')
        self.machine = 0x14c
        self.overrides = {}

    def tearDown(self):
        shutil.rmtree(self.root)

    def metadata(self, path, version=False):
        if not os.path.isfile(path):
            raise RuntimeError('Missing metadata: ' + path)
        return self.overrides.get(path, (self.machine, (2, 7, 11150, 1013)
                                        if version else None))

    def overlay(self):
        overlay_launcher(self.output, self.target, self.executable, self.interpreter,
                         metadata=self.metadata, interpreter_dll=self.dll)

    def snapshot(self):
        return dict((os.path.relpath(os.path.join(folder, name), self.target),
                     digest(os.path.join(folder, name)))
                    for folder, dirs, files in os.walk(self.target) for name in files)

    def rejected_unchanged(self):
        before = self.snapshot()
        self.assertRaises(RuntimeError, self.overlay)
        self.assertEqual(before, self.snapshot())

    def test_matching_x86_preserves_runtime(self):
        before = self.snapshot()
        self.overlay()
        after = self.snapshot()
        self.assertNotEqual(before['sk1.exe'], after['sk1.exe'])
        for name in ('python27.dll', os.path.join('libs', '_ctypes.pyd')):
            self.assertEqual(before[name], after[name])
        self.assertEqual(after['_ctypes.pyd'], before[os.path.join('libs', '_ctypes.pyd')])

    def test_matching_portable_x64_simulation(self):
        self.machine = 0x8664
        os.rename(os.path.join(self.output, self.executable),
                  os.path.join(self.output, 'sk1_portable.exe'))
        self.executable = 'sk1_portable.exe'
        self.test_matching_x86_preserves_runtime()

    def test_micro_version_mismatch_leaves_all_bytes(self):
        self.overrides[self.dll] = (self.machine, (2, 7, 18150, 1013))
        self.rejected_unchanged()

    def test_generated_dll_mismatch_leaves_all_bytes(self):
        self.overrides[os.path.join(self.output, 'python27.dll')] = (
            self.machine, (2, 7, 18150, 1013))
        self.rejected_unchanged()

    def test_launcher_architecture_mismatch_leaves_all_bytes(self):
        self.overrides[os.path.join(self.output, self.executable)] = (0x8664, None)
        self.rejected_unchanged()

    def test_interpreter_architecture_mismatch_leaves_all_bytes(self):
        self.overrides[self.interpreter] = (0x8664, None)
        self.rejected_unchanged()

    def test_missing_version_leaves_all_bytes(self):
        self.overrides[os.path.join(self.target, 'python27.dll')] = (self.machine, None)
        self.rejected_unchanged()

    def test_missing_metadata_leaves_all_bytes(self):
        os.remove(os.path.join(self.output, 'python27.dll'))
        self.rejected_unchanged()

    def test_dependency_mismatch_leaves_all_bytes(self):
        with open(os.path.join(self.output, '_ctypes.pyd'), 'wb') as stream:
            stream.write(b'different dependency')
        self.rejected_unchanged()

    def test_missing_dependency_leaves_all_bytes(self):
        os.remove(os.path.join(self.target, 'libs', '_ctypes.pyd'))
        self.rejected_unchanged()

    def test_embedded_x86_dependency_preserves_runtime(self):
        os.remove(os.path.join(self.output, '_ctypes.pyd'))
        with zipfile.ZipFile(os.path.join(self.output, self.executable), 'a') as archive:
            archive.writestr('_ctypes.pyd', b'ctypes')
        before = self.snapshot()
        self.overlay()
        self.assertEqual(before['python27.dll'], self.snapshot()['python27.dll'])
        self.assertFalse(os.path.exists(os.path.join(self.target, '_ctypes.pyd')))

    def test_no_ctypes_artifact_rejected(self):
        os.remove(os.path.join(self.output, '_ctypes.pyd'))
        self.rejected_unchanged()


@unittest.skipUnless(os.name == 'nt', 'Windows binary metadata')
class NativeMetadataTests(unittest.TestCase):
    def test_running_interpreter_pe_machine(self):
        expected = 0x8664 if struct.calcsize('P') == 8 else 0x14c
        self.assertEqual(binary_metadata(sys.executable)[0], expected)

    def test_loaded_python_has_version_resource(self):
        if sys.version_info[:2] != (2, 7):
            self.skipTest('Python 2.7 loaded DLL identification')
        from bootstrap_runtime import loaded_python_dll
        machine, version = binary_metadata(loaded_python_dll(), True)
        self.assertEqual(version[:2], (2, 7))
        self.assertEqual(machine, 0x14c if struct.calcsize('P') == 4 else 0x8664)
