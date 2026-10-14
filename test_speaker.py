import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('speaker', HERE / 'speaker.py')
speaker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speaker)


class ReceiverLifecycleTest(unittest.TestCase):
    def test_receiver_readiness_timeout(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'],
                                   stdout=subprocess.PIPE)
        try:
            with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
                speaker.wait_ready(process, timeout=.05)
        finally:
            speaker.stop(process)
            process.stdout.close()

    def test_build_falls_back_from_stale_sdk_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            (project / 'AdbSpeaker.java').write_text('// fixture')
            sdk = root / 'Android/Sdk'
            for item in ['platforms/android-37/android.jar', 'build-tools/36.0.0/d8']:
                target = sdk / item
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            with patch.dict(os.environ, {'ANDROID_SDK_ROOT': '/not-installed', 'ANDROID_HOME': '/not-installed'}), \
                 patch.object(speaker, 'ROOT', project), \
                 patch.object(speaker.Path, 'home', return_value=root), \
                 patch.object(speaker.shutil, 'which', return_value='/usr/bin/javac'), \
                 patch.object(speaker.subprocess, 'run') as run:
                speaker.build()
                self.assertIn(str(sdk / 'platforms/android-37/android.jar'), run.call_args_list[0].args[0])
                self.assertEqual(run.call_args_list[1].args[0][0], str(sdk / 'build-tools/36.0.0/d8'))

    def test_transfer_and_failure_both_clean_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            calls = root / 'calls.jsonl'
            adb = root / 'adb'
            adb.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['SPEAKER_TEST_CALLS'], 'a') as log:
    log.write(json.dumps(sys.argv[1:])+'\\n')
if 'app_process' in sys.argv:
    if os.environ.get('SPEAKER_TEST_REJECT') == '1': sys.exit(3)
    print('READY', flush=True)
    payload = sys.stdin.buffer.read()
    assert len(payload) % 4 == 0 and len(payload) > 0
elif 'pidof' in sys.argv: sys.exit(1)
''')
            adb.chmod(0o755)
            with patch.dict(os.environ, {'SPEAKER_TEST_CALLS': str(calls)}), \
                 patch.object(speaker, 'build', return_value=root / 'classes.dex'), \
                 patch.object(speaker.Path, 'home', return_value=root):
                speaker.receive([str(adb)], 'tone', None)
                entries = [json.loads(line) for line in calls.read_text().splitlines()]
                self.assertEqual(entries[-1], ['shell', 'unlink', speaker.REMOTE])
                self.assertFalse(any('install' in entry for entry in entries))
                with patch.dict(os.environ, {'SPEAKER_TEST_REJECT': '1'}):
                    with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
                        speaker.receive([str(adb)], 'tone', None)
                entries = [json.loads(line) for line in calls.read_text().splitlines()]
                self.assertEqual(entries[-1], ['shell', 'unlink', speaker.REMOTE])

    def test_desktop_capture_uses_playback_monitor_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            calls = root / 'calls.jsonl'
            adb = root / 'adb'
            adb.write_text('''#!/usr/bin/env python3
import os, sys, time
if 'app_process' in sys.argv:
    time.sleep(.15)
    assert not os.path.exists(os.environ['SPEAKER_TEST_CALLS'])
    print('READY', flush=True)
    assert len(sys.stdin.buffer.read()) > 0
elif 'pidof' in sys.argv: sys.exit(1)
''')
            adb.chmod(0o755)
            capture = root / 'parec'
            capture.write_text('''#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ['SPEAKER_TEST_CALLS'], 'w') as log: json.dump(sys.argv[1:], log)
while True:
    sys.stdout.buffer.write(b'\\0' * 3840)
    sys.stdout.buffer.flush()
    time.sleep(.01)
''')
            capture.chmod(0o755)
            with patch.dict(os.environ, {'PATH': str(root) + ':' + os.environ['PATH'],
                                        'SPEAKER_TEST_CALLS': str(calls)}), \
                 patch.object(speaker, 'build', return_value=root / 'classes.dex'), \
                 patch.object(speaker.Path, 'home', return_value=root):
                speaker.receive([str(adb)], 'stream', .5)
                self.assertIn('--device=@DEFAULT_MONITOR@', json.loads(calls.read_text()))


if __name__ == '__main__':
    unittest.main()
