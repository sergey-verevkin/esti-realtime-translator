"""Package the native UI for this Mac; retain the installed workspace runtime."""
from pathlib import Path
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
IDENTIFIER = 'local.realtime-translation.overlay'
target = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.home() / 'Applications/Realtime Translation.app'
required = ['translation/.venv/bin/python', 'capture-transcription/.venv/bin/python',
            'capture-transcription/.build/release/realtime-capture', 'translation/listen.sh']
for item in required:
    if not os.access(ROOT / item, os.X_OK):
        raise SystemExit(f'Missing executable: {ROOT / item}')
if target.exists():
    with (target / 'Contents/Info.plist').open('rb') as f:
        if plistlib.load(f).get('CFBundleIdentifier') != IDENTIFIER:
            raise SystemExit(f'Refusing to replace another application: {target}')
    running = subprocess.run(['pgrep', '-f', str(target / 'Contents/MacOS/realtime-overlay')], capture_output=True)
    if running.returncode == 0:
        raise SystemExit('Quit Realtime Translation from the ET menu before rebuilding the application.')
target.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='.realtime-build-', dir=target.parent) as temporary:
    bundle = Path(temporary) / target.name
    contents = bundle / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    (contents / 'Resources').mkdir()
    shutil.copy2(ROOT / 'overlay/.build/release/realtime-overlay', contents / 'MacOS/realtime-overlay')
    shutil.copy2(ROOT / 'overlay/Resources/AppIcon.icns', contents / 'Resources/AppIcon.icns')
    info = dict(CFBundleIconFile='AppIcon', CFBundleIdentifier=IDENTIFIER, CFBundleName='Realtime Translation',
        CFBundleDisplayName='Realtime Translation', CFBundleExecutable='realtime-overlay',
        CFBundlePackageType='APPL', CFBundleShortVersionString='1.0', CFBundleVersion='1',
        LSMinimumSystemVersion='14.2', LSUIElement=True, NSHighResolutionCapable=True,
        NSAudioCaptureUsageDescription='Системный звук используется для локального распознавания и перевода речи.',
        RealtimeWorkspaceRoot=str(ROOT))
    with (contents / 'Info.plist').open('wb') as f:
        plistlib.dump(info, f)
    subprocess.run(['codesign', '--force', '--sign', '-', '--identifier', IDENTIFIER, str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(bundle)], check=True)
    backup = Path(temporary) / 'previous.app'
    if target.exists(): target.rename(backup)
    try: bundle.rename(target)
    except BaseException:
        if backup.exists(): backup.rename(target)
        raise
subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister', '-f', str(target)], check=True)
print(f'Installed: {target}')
print(f'Runtime workspace: {ROOT}')
