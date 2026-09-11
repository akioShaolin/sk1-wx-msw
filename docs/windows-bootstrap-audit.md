# Windows bootstrap audit and review corrections (issue #7)

## Scope and repository state

Audited and corrected on 2026-09-10 in `akioShaolin/sk1-wx-msw`, branch
`fix/windows-bootstrap-log`. The original implementation began with a clean
working tree. At that time, fetching confirmed `main`, `origin/main`,
`upstream/main` and the existing fix branch all pointed to
`02c64043ba5dbd2f587de531539577e2bcfe6a23`; no merge was necessary.

The corrective task preserved the intentional three modified and five new
files and added runtime validation and its tests. No application/save/IPC
code, installed runtime, association, or machine/user environment setting
was changed. No commit, push, PR or other publication was made.

**Logging and runtime-preservation corrections do not establish that issue
#7 is resolved.** The permission dialog can mask a different startup
exception. The x64 application test below reproduces a separate Unicode forwarding failure.

## Exact historical bootstrap evidence

Both bundled installers declare py2exe `0.6.9`:

| Architecture | Installer under its `installers` directory | SHA-256 |
| --- | --- | --- |
| win32 | `py2exe-0.6.9.win32-py2.7.exe` | `610a8800de3d973ed5ed4ac505ab42ad058add18a68609ac09e6cf3598ef056c` |
| win64 | `py2exe-0.6.9.win64-py2.7.amd64.exe` | `ab923d471173594b7ec793cec014f87af947beebef5a54cb62f688faccfd6328` |

Their `PLATLIB/py2exe/boot_common.py` payloads are byte-identical, SHA-256
`73db7dc9afe806b9324a75be85eaa2f639a1d1221efa89ef2f0712f7f197a341`.
Their `build_exe.py` payloads are also identical, SHA-256
`6f94f38edcd1ccd51b1469cb1e8409cf7cabc34dec691f1b6954d8b640a75b18`.
Evidence comes from those payloads, not modern py2exe behavior.

`build_executable()` uses the GUI `run_w.exe` template and writes marshalled
code objects into the `PYTHONSCRIPT` resource, ID 1, in this order:

1. `get_boot_script('common')`;
2. installation of zipextimporter when `bundle_files < 3`;
3. optional variables/custom bootstrap;
4. entry script.

The module finder also processes `get_boot_script('common')`. The override
therefore affects both dependency collection and the first embedded code.
The stock common script installs stderr redirection early but opens
`sys.executable + '.log'` only on the first stderr write, in append mode.
It flushes each write and registers an exit notification on success/failure.
This does not prove why the official bundle's forwarding failed or whether
its log access suffered ACL denial or a sharing violation. Native loader
failures before Python executes remain outside Python-level logging.

Both launcher build scripts use compression and `zipfile=None`; x86 uses
`bundle_files=2`, x64 uses `bundle_files=3`. The historical resources contain
Python 2.7.11 and wxPython 3.0.2.0 installers. Both build scripts retain the
pre-existing x86 VC90 CRT glob, including in the x64 tree. That discrepancy
still needs separate clean-machine verification; no CRT/toolchain upgrade
is included here.

## Correction 1: Unicode environment and early diagnostics

The original helper read Python 2.7 `os.environ`, whose ANSI representation
lost characters outside the active code page. `João` alone did not expose
that defect. With ACP 1252, the native regression now demonstrates that
`测试` becomes `??` in the old representation while the corrected logger
successfully opens the intended Unicode directory.

`bootstrap_log.py` now uses `GetEnvironmentVariableW`, keeping paths Unicode
through directory creation and file opening. It handles absent/empty values,
API failures, buffer growth and bounded retry when values change between
reads. It does not decode already lossy environment bytes to repair them.
Localized Python 2 byte exception messages are retained as escaped repr
text if Unicode conversion fails; path data is not discarded.

Policy remains lazy append logging to
`%LOCALAPPDATA%\sK1\logs\sk1-bootstrap-<PID>.log`, falling back to the same
subpath under `%TEMP%` when needed. Only fully qualified absolute paths are
accepted; there is no executable-side/cwd fallback. Existing directories and
concurrent creation are tolerated. Distinct live PIDs have distinct files;
PID reuse appends to an old log. No retention policy is added. If both
locations fail, their errors remain diagnosable in the exit notification.

`bootstrap_build.py` verifies py2exe 0.6.9 and four expected expressions in
the original source. It adapts filename selection, opening, the alert
callback and exception formatting. `MessageBoxW` preserves Unicode paths
in notifications; production notifications are not disabled. Stock flush,
stdout, traceback, notification-registration and linecache behavior remain.
Generated source lives in an OS temporary directory until build-process
exit. Existing notices are preserved; no py2exe/UniConvertor source is
vendored in this repository.

ctypes is imported lazily. In `bundle_files=2`, a function generated only for
that mode installs the toolchain's zipextimporter hook if needed before
importing ctypes. `_ctypes.pyd` can therefore load from the executable even
before the ordinary importer code object executes. For `bundle_files=3`,
that function is omitted, avoiding an unnecessary importer dependency;
`_ctypes.pyd` is supplied beside the executable. Module discovery scans the
same generated code and includes its imports. Both arrangements were
exercised natively on x86; the x64 external-extension arrangement also passed
the matching 2.7.11 validation below.

## Correction 2: validated overlay, preserved runtime

The previous overlay copied all generated runtime files, including
`python27.dll`. A 2.7.18 build could overwrite a target 2.7.11 DLL. No crash
was demonstrated, but changing the historical runtime violated task scope.

`bootstrap_runtime.py`, called by `bootstrap_build.install_launcher`, now
validates every input before writing destination artifacts:

- Read PE signatures and Machine fields for actual architecture.
- Read Windows fixed file-version resources for the target/generated Python
  DLLs and the DLL loaded by the build interpreter. Require exact matching
  architecture and complete fixed version, including micro/release/build
  fields. `python.exe` may lack version resources: locate its loaded DLL via
  `GetModuleFileNameW(sys.dllhandle)` and check the executable's PE separately.
- Check generated and existing launcher architectures against that runtime.
- Match emitted and embedded native dependencies against target files using
  PE architecture and SHA-256. Check emitted CRT manifests against the target.
  Missing/different dependencies, unverifiable metadata and unknown output
  artifacts fail with an explanation, before destination writes.
- Permit only `sk1.exe` and, when external ctypes needs it, an identical copy
  of the target's own `libs/_ctypes.pyd` at the executable root. Require a
  verified ctypes artifact. Preserve existing `python27.dll` and dependencies.
  The legacy `w9xpopen.exe` output is not deployed or used by this bootstrap.

Both architecture scripts register the same bootstrap command. No arguments
build `sk1.py`; `portable` selects `sk1_portable.py`; explicit `py2exe` plus
options is supported. Installed and portable package assembly use the same
guarded overlay after extracting historical resources. Build failures abort;
an old ZIP launcher cannot silently be shipped after a failed rebuild.

The dependency comparison is deliberately conservative: different extension
bytes are rejected even if compatibility might be possible. It is not a
complete GUI/runtime certification. Rejection is proven to leave destination
bytes unchanged; disk failure during subsequent allowed copies is not claimed
to be transactional. Existing CRT arrangements still need release validation.

## Validation commands and results

Run from the repository root in PowerShell:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
C:\Python27\python.exe -B -m unittest discover -s tests -v
py -3 -B -m unittest discover -s tests -v
C:\Python27\python.exe -B tests/smoke_bootstrap.py
C:\Python27\python.exe -B tests/smoke_bootstrap.py --unbundled
```

The environment assignment above applies only to that shell and its children.

| Interpreter | Architecture | Suite result |
| --- | --- | --- |
| `C:\Python27\python.exe`, 2.7.18 | x86 | 30 passed, 0 skipped |
| `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`, 3.13.3 | x64 | 28 passed, 2 skipped |

Python 3 skips original Python 2 bootstrap execution and Python 2 loaded-DLL
identification. Tests execute the adapted real bootstrap payload from both
installers under Python 2.7, including lazy opening and a pre-entry exception.
They cover Unicode API behavior, fallback, both locations failing and path
policy. Runtime rejection tests use explicitly simulated version/architecture
metadata and compare the whole destination file set and hashes before/after.
Matching installed x86 and portable x64 cases are simulations, not native
application validation. Separate tests read native PE and version metadata.

Both native x86 smoke modes passed. Each launches four processes: two
concurrent processes for LOCALAPPDATA and two for TEMP. Real disposable
`测试` directories are outside the observed **ACP 1252**. The fixture uses
`SetEnvironmentVariableW` and child creation with `env=None`; no ANSI dict
corrupts the fixture. The child records the old ANSI loss and successful
corrected logging. A test-only suffix in the first common bootstrap writes
before the ordinary importer and entry script, proving early ctypes access.

The revised smoke uses normal exit, not `os._exit()`. A test-only replacement
of stderr's notification callback records actual atexit delivery with Unicode
text. The early diagnostic, entry diagnostic, notification marker, separate
PID logs and absence of `probe.exe.log` are verified. Production MessageBoxW
remains active. The later x64 probe below observed its real window text and
dismissed its actual OK control, exercising normal notification shutdown.
The smoke also runs the native metadata guard against a disposable matching
runtime fixture and checks that the target Python DLL bytes remain unchanged.

`--unbundled` tests the external-extension arrangement on x86. It does not
validate an x64 executable. Builds use temporary ASCII staging because the
historical dependency scanner can fail on Unicode build paths. Unicode log
destinations are tested separately. Test artifacts are removed with Unicode
paths; no installed runtime was replaced. Earlier 11-test results describe the
initial implementation and are superseded by the results above.

## Matching x64 review and application validation

The focused review found no actionable defect blocking isolated application
validation. Production helpers, build scripts and tests were not changed in
this review; their nine recorded hashes remained identical afterward.

The existing `%LOCALAPPDATA%\sK1-2.0rc5-dev` runtime was verified as x64,
Python 2.7.11, installed entry `sk1.py`. The bundled Python MSI cabinets were
read and extracted into a new disposable tree, without MSI installation or
registry registration. The matching py2exe installer was extracted there too.
The interpreter reported 2.7.11, AMD64, py2exe 0.6.9; PE Machine was `0x8664`
and Python DLL fixed version was `(2, 7, 11150, 1013)`. No persistent PATH or
user/machine environment changes were made. `IsUserAnAdmin()` returned zero.

With this exact x64 interpreter, all **30 deterministic tests passed** and the
native unbundled smoke passed, including early ctypes, concurrent Unicode
logging, normal exit and the runtime metadata guard. ASCII build staging was
used; actual log destinations included `测试` outside ACP 1252.

The guarded overlay changed only `sk1.exe` in the runtime copy and added an
identical copy of its own `libs/_ctypes.pyd` at the root. All 3,263 original
runtime files remained unchanged. The following SHA-256 values distinguish
normal and deliberately failing builds:

| Artifact | SHA-256 |
| --- | --- |
| Original launcher | `c3052115aec400d6a0c478bc2693fbe90ee7b68f4591405465cf75b6c2527d1c` |
| Normal candidate, `candidate-runtime/sk1.exe` | `570ceee02227ffd39fb4ed3dcf5b5f183d95e6c6fe4b1e96cc5258b6e8e310b7` |
| Diagnostic, `diagnostic-probe-v2/sk1.exe` | `c4e3b102b998e718db8a2e46ee18e2879b0d250375d7f9fa1de91bff401d48f7` |
| Original and candidate `python27.dll` | `541cf010d23b4af9bea97b4d385da8351a01db812109e17746a9cc599cd033ec` |

### Real diagnostic windows and directory permissions

A separate x64 diagnostic executable raised a controlled exception before a
no-op entry script. Four processes, two per LOCALAPPDATA/TEMP scenario,
retained their early tracebacks in separate PID logs under Unicode paths.
The executable directory denied writes while retaining read/execute access;
a direct write check failed with permission denied. ACLs were saved and
restored. No executable-side log appeared.

The actual MessageBoxW window text contained the complete Unicode log path.
The harness clicked each real OK child control and observed process exit
without forced termination. This exercises production notification delivery,
not only registration or a test replacement callback. An earlier exploratory
fixture incorrectly assumed the OK control ID and used an entry with missing
application libraries; its records are retained but are not counted as the
successful diagnostic run. The corrected results are in
`records/diagnostic-windows-v2.json`.

### Configuration isolation and sequential A/B result

Before GUI startup, the matching interpreter loaded the copied runtime's
actual fsutils and configuration code. Child HOME/USERPROFILE resolved to a
fresh disposable profile, `sk1_run` defaulted to `~`, and server mode was true.
Preferences, normal `sk1.log`, `lock` and `socket` all resolved under that
profile's `.config/sk1-wx`. Both invocations shared that profile; baseline and
candidate used separate equivalent profiles. Parent environment and live
user configuration were untouched.

Public shaping-fusion and shaping-intersection fixtures supplied distinct
valid content for `A with spaces.sk2` and `B ação.sk2`. A first exploratory
XML graphics fixture stalled during parsing and was excluded; its isolated
process and records are identified separately. The final observations were:

| Launcher/scenario | Primary PID | Secondary PID/exit | Observed result |
| --- | --- | --- | --- |
| Original, accented B | 23924 | 20404 / 255 | A stays open; B absent; original executable-side error log |
| Candidate, accented B | 4496 | 29424 / 255 | A stays open; B absent; traceback in intended PID log |
| Candidate, identical B bytes named `B ascii.sk2` | 12660 | 17588 / 0 | A and B tabs in the same primary; correct intersection content and full path |

Screenshots showed A alone after both accented attempts. The ASCII control
showed both tabs and B's distinct intersection drawing. The application log
confirmed both exact ASCII document paths loaded in the same primary. All
three final primary processes were closed normally with exit zero; error
dialogs were dismissed and the final secondary processes were not forcibly
terminated. Successful launches without stderr correctly produced no
bootstrap diagnostic.

Both accented attempts failed at the same application operation:

```text
sk1.py:63 -> sk1_run():95 -> check_server():80
UnicodeEncodeError: 'ascii' codec can't encode characters ...
```

Read-only inspection of the copied `libs/sk1/__init__.pyc` confirmed line 80
writes `'%s\n' % item` to the binary socket file, implicitly converting a
Unicode filename through ASCII. The candidate traceback is retained in
`candidate-logs/sK1/logs/sk1-bootstrap-29424.log`; the original traceback is
in `baseline-runtime/sk1.exe.log`. This is a pre-existing application encoding
failure, not a loader/dependency failure. No application/IPC code was edited.
The smallest next change is to review explicit UTF-8 serialization of
normalized filenames together with the receiver's decoding contract and a
regression covering accented names. The simultaneous-sender shared-file race
remains a separate follow-up.

### Explorer, release limits and retained evidence

Read-only `AssocQueryStringW` returned the existing installed command
`"C:\Program Files\sK1-2.0rc5\sk1.exe" "%1"`. Explorer validation of the
copied candidate remains pending; no association was changed. A later
controlled Explorer test must prove the actual executable and isolated
profile used. Direct invocation here does not establish Explorer behavior.

Missing historical ZIPs still prevent complete package/installer assembly.
Portable integration, clean-machine CRT validation, accented parent document
directories and simultaneous forwarding were not validated. The official
installation's original log failure was not reproduced under Process Monitor;
this audit does not establish ACCESS DENIED versus SHARING VIOLATION there.
Only the bootstrap logging component is validated: issue #7 is not resolved,
and accented sequential forwarding demonstrably still fails.

Exact private paths are retained only in the local disposable tree's
`records/context.json`. In commands below, `<review-root>` means that tree.
Useful records include `final-preservation.json`, `overlay-hashes.json`,
`x64-unit.log`, `x64-smoke.log`, `association.json`, the A/B JSON records,
configuration verification, process exits, application logs and screenshots.
The normal candidate and diagnostics are retained separately.

Repeat using PowerShell, waiting for A to finish loading before B:

```powershell
py -3 -B '<review-root>\scripts\launch_manual.py' A
py -3 -B '<review-root>\scripts\launch_manual.py' B
```

The prepared launcher verifies a separate manual profile before each launch,
constructs only the child environment, invokes the exact normal candidate,
and records PIDs. `ASCII` selects the identical-content filename control.
Expect accented B to produce the recorded application error; it is not a
passing workflow. Close only these test windows when finished. The retained
`cleanup.ps1` verifies the exact disposable root and refuses deletion while
any process executable in that tree remains running; after closing them:

```powershell
& '<review-root>\scripts\cleanup.ps1'
```

Cleanup has not been executed. No user process was terminated by image name,
and no installation, association or original runtime was modified.

## Diff hygiene and final state

`git diff --check` passed. The previously normalized launcher scripts remain
LF in the working tree (their index entries are CRLF); existing autocrlf
settings warn of conversion on a future checkout. `setup-sk1-msw.py` remains
CRLF in the working tree with its existing LF index convention. All new
Python and Markdown files use LF. No unrelated caches/files were removed.

Ordinary tracked diff: 3 files, 85 insertions and 70 deletions, including the
previous launcher line-ending normalization. That statistic excludes the
seven untracked files listed below, which contain helpers, tests and audit.

```text
 M setup-sk1-msw.py
 M win32-devres/exe_proj/sk1-exe-build.py
 M win64-devres/exe_proj/sk1-exe-build.py
?? bootstrap_build.py
?? bootstrap_log.py
?? bootstrap_runtime.py
?? docs/windows-bootstrap-audit.md
?? tests/smoke_bootstrap.py
?? tests/test_bootstrap.py
?? tests/test_runtime.py
```

## Primary references

- [GetEnvironmentVariableW](https://learn.microsoft.com/en-us/windows/win32/api/processenv/nf-processenv-getenvironmentvariablew): Unicode values, sizing and missing-variable behavior.
- [GetFileVersionInfoW](https://learn.microsoft.com/en-us/windows/win32/api/winver/nf-winver-getfileversioninfow): binary version-resource retrieval.
- [PE format](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format): signatures and architecture fields.
- [Historical py2exe release](https://sourceforge.net/projects/py2exe/files/py2exe/0.6.9/): the implementation evidence is the exact local payloads identified above.
