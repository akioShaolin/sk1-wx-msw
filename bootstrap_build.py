# Copyright (C) 2026 sK1 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Adapt the installed py2exe 0.6.9 bootstrap without vendoring its source."""

import atexit
import os
import shutil
import tempfile


def adapt_bootstrap(source, helper, bundled_extensions=False):
    replacements = (
        ("fname=sys.executable + '.log'", "fname=u'LOCALAPPDATA/TEMP bootstrap log'"),
        ("self._file = open(fname, 'a')",
         'self._file, fname = open_bootstrap_log()'),
        ('alert=sys._MessageBox', 'alert=bootstrap_message_box'),
        ('(fname, details)', '(fname, bootstrap_error_text(details))'),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError('Unexpected py2exe 0.6.9 bootstrap: ' + old)
        source = source.replace(old, new)
    prefix = ''
    if bundled_extensions:
        # Do not introduce zipextimporter/_memimporter into bundle_files=3.
        prefix = ('def _sk1_bootstrap_importer():\n'
                  '    import sys, zipextimporter\n'
                  '    if zipextimporter.ZipExtensionImporter not in sys.path_hooks:\n'
                  '        zipextimporter.install()\n')
    return prefix + helper + '\n' + source


def bootstrap_command():
    import py2exe
    from py2exe.build_exe import py2exe as BaseCommand

    if py2exe.__version__ != '0.6.9':
        raise RuntimeError('This build requires py2exe 0.6.9')

    class BootstrapCommand(BaseCommand):
        _sk1_boot_script = None

        def get_boot_script(self, boot_type):
            original = BaseCommand.get_boot_script(self, boot_type)
            if boot_type != 'common':
                return original
            if self._sk1_boot_script is None:
                with open(original, 'r') as stream:
                    source = stream.read()
                helper_path = os.path.join(os.path.dirname(__file__),
                                           'bootstrap_log.py')
                with open(helper_path, 'r') as stream:
                    helper = stream.read()
                generated = adapt_bootstrap(source, helper, self.bundle_files < 3)
                directory = tempfile.mkdtemp(prefix='sk1-py2exe-')
                atexit.register(shutil.rmtree, directory, True)
                self._sk1_boot_script = os.path.join(directory, 'boot_common.py')
                with open(self._sk1_boot_script, 'w') as stream:
                    stream.write(generated)
            return self._sk1_boot_script

    return BootstrapCommand


def install_launcher(resource_path, destination, portable):
    """Rebuild instead of shipping the launcher from the legacy resource ZIP."""
    import subprocess
    import sys

    project = os.path.abspath(os.path.join(resource_path, 'exe_proj'))
    output = tempfile.mkdtemp(prefix='sk1-launcher-')
    try:
        command = [sys.executable, 'sk1-exe-build.py',
                   'portable' if portable else 'py2exe', '--dist-dir', output]
        subprocess.check_call(command, cwd=project)
        executable = 'sk1_portable.exe' if portable else 'sk1.exe'
        from bootstrap_runtime import overlay_launcher
        overlay_launcher(output, destination, executable, sys.executable)
    finally:
        shutil.rmtree(output)
