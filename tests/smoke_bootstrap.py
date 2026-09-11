# Copyright (C) 2026 sK1 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and run two minimal GUI launchers with the matching bundled py2exe.

Run with 32-bit or 64-bit Python 2.7. No system installation is performed.
This does not replace the real sK1/Explorer forwarding smoke test.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import ctypes


def main():
    if sys.version_info[:2] != (2, 7):
        raise RuntimeError('Use Python 2.7 of the architecture under test')
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    arch = 'win64' if sys.maxsize > 2 ** 32 else 'win32'
    bundle_files = 3 if arch == 'win64' or '--unbundled' in sys.argv else 2
    installer = ('py2exe-0.6.9.win64-py2.7.amd64.exe' if arch == 'win64'
                 else 'py2exe-0.6.9.win32-py2.7.exe')
    temporary = tempfile.mkdtemp(prefix='sk1-native-smoke-')
    try:
        with zipfile.ZipFile(os.path.join(root, arch + '-devres',
                                         'installers', installer)) as archive:
            archive.extractall(temporary)
        for name in ('bootstrap_log.py', 'bootstrap_build.py'):
            shutil.copyfile(os.path.join(root, name),
                            os.path.join(temporary, name))
        setup = (
            'import sys\n'
            'sys.path.insert(0, %r)\n'
            'from distutils.core import setup\n'
            'from bootstrap_build import bootstrap_command\n'
            'import py2exe\n'
            'BaseProbe = bootstrap_command()\n'
            'class ProbeCommand(BaseProbe):\n'
            '    def get_boot_script(self, kind):\n'
            '        path = BaseProbe.get_boot_script(self, kind)\n'
            '        if kind == "common" and not getattr(self, "probe_added", False):\n'
            '            with open(path, "a") as stream: stream.write(%r)\n'
            '            self.probe_added = True\n'
            '        return path\n'
            "setup(cmdclass={'py2exe': ProbeCommand}, "
            "windows=['probe.py'], options={'py2exe': {'bundle_files': %d}}, "
            'zipfile=None)\n'
        ) % (os.path.join(temporary, 'PLATLIB'),
             '\nimport sys\n'
             'def probe_dialog(hwnd, text, title):\n'
             '    assert isinstance(text, unicode)\n'
             '    sys.stderr.write("normal-exit notification delivered\\n")\n'
             'sys.stderr.write.im_func.func_defaults = (probe_dialog, u"probe")\n'
             'sys.stderr.write("before ordinary importer and entry script\\n")\n'
             'if os.environ["TEMP"].decode("mbcs") != windows_environment(u"TEMP"):\n'
             '    sys.stderr.write("ANSI path loss reproduced\\n")\n',
             bundle_files)
        with open(os.path.join(temporary, 'setup.py'), 'w') as stream:
            stream.write(setup)
        with open(os.path.join(temporary, 'probe.py'), 'w') as stream:
            stream.write("import os, sys, time\n"
                         "sys.stderr.write('native bootstrap diagnostic\\n')\n"
                         "time.sleep(0.2)\n")
        process = subprocess.Popen([sys.executable, 'setup.py', 'py2exe'],
                                   cwd=temporary, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        output = process.communicate()[0]
        if process.returncode:
            raise RuntimeError(output)
        executable = os.path.join(temporary, 'dist', 'probe.exe')
        sys.path.insert(0, root)
        # Native metadata/overlay check against a disposable matching runtime
        # fixture, not against the user's sK1 installation.
        from bootstrap_runtime import overlay_launcher, digest
        target = os.path.join(temporary, 'matching-runtime')
        os.makedirs(os.path.join(target, 'libs'))
        for name in os.listdir(os.path.dirname(executable)):
            if name.lower().endswith(('.dll', '.pyd')):
                shutil.copy2(os.path.join(os.path.dirname(executable), name), target)
        with zipfile.ZipFile(executable) as archive:
            for name in archive.namelist():
                if name.lower().endswith(('.dll', '.pyd')):
                    assert '/' not in name and '\\' not in name, name
                    with open(os.path.join(target, 'libs', name), 'wb') as stream:
                        stream.write(archive.read(name))
        shutil.copy2(executable, os.path.join(target, 'sk1.exe'))
        dll_hash = digest(os.path.join(target, 'python27.dll'))
        overlay_launcher(os.path.dirname(executable), target, 'probe.exe', sys.executable)
        assert dll_hash == digest(os.path.join(target, 'python27.dll'))
        print('PASS: native matching-runtime overlay preserves Python DLL bytes')
        from bootstrap_log import windows_environment
        setter = ctypes.windll.kernel32.SetEnvironmentVariableW
        setter.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        setter.restype = ctypes.c_int
        acp = ctypes.windll.kernel32.GetACP()
        component = u'\u6d4b\u8bd5'
        outside_acp = False
        try:
            component.encode('cp%s' % acp)
        except UnicodeEncodeError:
            outside_acp = True
            print('Outside-ACP native regression covered; ACP=%s' % acp)
        else:
            print('ACP=%s represents test path; no outside-ACP claim' % acp)
        saved_env = dict((key, windows_environment(key))
                         for key in (u'LOCALAPPDATA', u'TEMP'))
        for preferred in (True, False):
            base = os.path.join(unicode(temporary), component,
                                u'local' if preferred else u'fallback')
            os.makedirs(base)
            # SetEnvironmentVariableW + env=None preserve the Unicode process
            # environment; Python 2.7's env=dict would corrupt the fixture.
            try:
                if not setter(u'LOCALAPPDATA', base if preferred else None):
                    raise ctypes.WinError()
                if not setter(u'TEMP', base):
                    raise ctypes.WinError()
                processes = [subprocess.Popen([executable]) for _ in range(2)]
            finally:
                for key, value in saved_env.items():
                    setter(key, value)
            for process in processes:
                import time
                deadline = time.time() + 20
                while process.poll() is None and time.time() < deadline:
                    time.sleep(0.05)
                if process.poll() is None:
                    for child in processes:
                        if child.poll() is None:
                            child.kill()
                        child.wait()
                    raise RuntimeError('Native launcher timed out')
                if process.returncode != 0:
                    raise RuntimeError('Native launcher failed')
            logs = glob.glob(os.path.join(base, 'sK1', 'logs', '*.log'))
            assert len(logs) == 2, logs
            for path in logs:
                with open(path) as stream:
                    text = stream.read()
                    assert 'native bootstrap diagnostic' in text
                    assert 'before ordinary importer and entry script' in text
                    assert 'normal-exit notification delivered' in text
                    if outside_acp:
                        assert 'ANSI path loss reproduced' in text
            assert not os.path.exists(executable + '.log')
        print('PASS: %s bundle_files=%s early bootstrap, Unicode, concurrency, normal exit, LOCALAPPDATA/TEMP'
              % (arch, bundle_files))
    finally:
        shutil.rmtree(unicode(temporary))


if __name__ == '__main__':
    main()
