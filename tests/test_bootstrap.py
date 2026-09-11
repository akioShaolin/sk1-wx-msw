# Copyright (C) 2026 sK1 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run with Python 2.7: python -m unittest discover -s tests -v."""
import atexit
import linecache
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

from bootstrap_build import adapt_bootstrap
from bootstrap_log import open_bootstrap_log, windows_environment

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LogTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='sk1-test-')
        self.env = dict(LOCALAPPDATA=os.path.join(self.root, 'local'),
                        TEMP=os.path.join(self.root, 'temp'))

    def tearDown(self):
        shutil.rmtree(self.root)

    def path(self, env=None, pid=123):
        stream, path = open_bootstrap_log(self.env if env is None else env, pid)
        stream.write('diagnostic\n')
        stream.close()
        return path

    def test_localappdata(self):
        path = self.path()
        self.assertEqual(path, os.path.join(self.env['LOCALAPPDATA'],
                         'sK1', 'logs', 'sk1-bootstrap-123.log'))
        with open(path) as stream:
            self.assertEqual(stream.read(), 'diagnostic\n')

    def test_missing_preferred_location(self):
        self.assertTrue(self.path({'TEMP': self.env['TEMP']}).startswith(
            self.env['TEMP']))

    def test_unusable_preferred_location(self):
        with open(self.env['LOCALAPPDATA'], 'w') as stream:
            stream.write('not a directory')
        self.assertTrue(self.path().startswith(self.env['TEMP']))

    def test_relative_location_rejected(self):
        self.assertTrue(self.path(dict(LOCALAPPDATA='relative',
                                      TEMP=self.env['TEMP'])).startswith(
            self.env['TEMP']))

    def test_open_failure_uses_temp(self):
        directory = os.path.join(self.env['LOCALAPPDATA'], 'sK1', 'logs')
        os.makedirs(os.path.join(directory, 'sk1-bootstrap-123.log'))
        self.assertTrue(self.path().startswith(self.env['TEMP']))

    def test_distinct_live_handles(self):
        first, path1 = open_bootstrap_log(self.env, 1)
        try:
            second, path2 = open_bootstrap_log(self.env, 2)
            try:
                first.write('first')
                second.write('second')
                self.assertNotEqual(path1, path2)
            finally:
                second.close()
        finally:
            first.close()

    def test_existing_directory(self):
        self.assertEqual(self.path(), self.path())

    def test_non_ascii_profile(self):
        path = self.path({'LOCALAPPDATA': os.path.join(self.root, u'Jo\u00e3o')})
        self.assertTrue(os.path.isfile(path))

    def test_no_executable_side_fallback(self):
        original = sys.executable
        sys.executable = os.path.join(self.root, 'sk1.exe')
        try:
            self.assertRaises(IOError, open_bootstrap_log, {}, 1)
            self.assertEqual(os.listdir(self.root), [])
        finally:
            sys.executable = original

    def test_both_locations_unusable_are_diagnosable(self):
        for base in self.env.values():
            with open(base, 'w') as stream:
                stream.write('block directory creation')
        with self.assertRaises(IOError) as caught:
            open_bootstrap_log(self.env)
        from bootstrap_log import bootstrap_error_text
        text = bootstrap_error_text(caught.exception)
        self.assertIn('LOCALAPPDATA', text)
        self.assertIn('TEMP', text)

    def test_reader_failure_falls_back(self):
        def reader(name):
            if name == 'LOCALAPPDATA':
                raise OSError('API failure')
            return self.env[name]
        stream, path = open_bootstrap_log(reader=reader)
        stream.close()
        self.assertTrue(path.startswith(self.env['TEMP']))


@unittest.skipUnless(os.name == 'nt', 'Windows Unicode environment API')
class EnvironmentTests(unittest.TestCase):
    def test_unicode_environment_roundtrip_and_empty(self):
        import ctypes
        key = u'SK1_BOOTSTRAP_UNICODE_TEST'
        old = windows_environment(key)
        setter = ctypes.windll.kernel32.SetEnvironmentVariableW
        setter.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        try:
            value = u'\u6d4b\u8bd5' * 200
            self.assertTrue(setter(key, value))
            self.assertEqual(windows_environment(key), value)
            self.assertTrue(setter(key, u''))
            self.assertIsNone(windows_environment(key))
            self.assertTrue(setter(key, None))
            self.assertIsNone(windows_environment(key))
        finally:
            setter(key, old)

    def test_api_error_is_not_treated_as_missing(self):
        import ctypes
        class Kernel(object):
            pass
        kernel = Kernel()
        def read(name, buffer, size):
            ctypes.set_last_error(5)
            return 0
        kernel.GetEnvironmentVariableW = read
        self.assertRaises(OSError, windows_environment, u'LOCALAPPDATA', kernel)

    def test_buffer_growth_between_reads(self):
        class Kernel(object):
            pass
        kernel = Kernel()
        calls = []
        def read(name, buffer, size):
            calls.append(size)
            if len(calls) < 3:
                return size + 100
            buffer.value = u'\u6d4b\u8bd5'
            return 2
        kernel.GetEnvironmentVariableW = read
        self.assertEqual(windows_environment(u'TEMP', kernel), u'\u6d4b\u8bd5')
        self.assertEqual(calls, [128, 228, 328])


@unittest.skipUnless(sys.version_info[0] == 2,
                     'Exact py2exe source requires Python 2.7')
class HistoricalBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='sk1-history-test-')
        self.env = dict(LOCALAPPDATA=os.path.join(self.root, 'local'),
                        TEMP=os.path.join(self.root, 'temp'))

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_both_real_bootstraps_capture_pre_entry_exception(self):
        with open(os.path.join(ROOT, 'bootstrap_log.py')) as stream:
            helper = stream.read()
        for arch, installer in (
            ('win32', 'py2exe-0.6.9.win32-py2.7.exe'),
            ('win64', 'py2exe-0.6.9.win64-py2.7.amd64.exe'),
        ):
            with zipfile.ZipFile(os.path.join(ROOT, arch + '-devres',
                                             'installers', installer)) as archive:
                source = archive.read('PLATLIB/py2exe/boot_common.py')
            source = source.replace('\r\n', '\n').replace('\r', '\n')
            code = compile(adapt_bootstrap(source, helper), 'boot_common.py', 'exec')
            saved = (sys.stderr, sys.stdout, linecache.getline, atexit.register)
            callbacks = []
            namespace = {}
            old_env = dict(os.environ)
            try:
                os.environ.update(self.env)
                sys.frozen = 'windows_exe'
                sys._MessageBox = lambda *args: None
                atexit.register = lambda *args: callbacks.append(args)
                existed = os.path.exists(self.env['LOCALAPPDATA'])
                eval(code, namespace)
                self.assertEqual(existed, os.path.exists(self.env['LOCALAPPDATA']))
                self.assertIsNone(sys.stderr._file)
                self.assertEqual(callbacks, [])
                # No entry script has executed. Exercise a failing next boot step.
                try:
                    raise RuntimeError('pre-entry diagnostic ' + arch)
                except RuntimeError:
                    import traceback
                    traceback.print_exc()
                path = os.path.join(self.env['LOCALAPPDATA'], 'sK1', 'logs',
                                    'sk1-bootstrap-%s.log' % os.getpid())
                with open(path) as stream:
                    self.assertIn('pre-entry diagnostic ' + arch, stream.read())
                self.assertIn(path, callbacks[0][2])
                self.assertNotIn("sys.executable + '.log'",
                                 adapt_bootstrap(source, helper))
            finally:
                if sys.stderr is not saved[0] and sys.stderr._file:
                    sys.stderr._file.close()
                sys.stderr, sys.stdout, linecache.getline, atexit.register = saved
                del sys.frozen
                if hasattr(sys, '_MessageBox'):
                    del sys._MessageBox
                os.environ.clear()
                os.environ.update(old_env)


class AdaptationTests(unittest.TestCase):
    def test_unknown_bootstrap_fails_closed(self):
        self.assertRaises(RuntimeError, adapt_bootstrap, 'unexpected', '')


if __name__ == '__main__':
    unittest.main()
