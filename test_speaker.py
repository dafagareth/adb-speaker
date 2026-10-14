# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dafagareth
"""Exercise host lifecycle behavior with fake processes, without a connected phone."""
import importlib.util
import contextlib
import fcntl
import io
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
if spec is None or spec.loader is None:
    raise ImportError('Cannot load speaker.py for tests')
speaker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speaker)


class ReceiverLifecycleTest(unittest.TestCase):
    def test_help_and_empty_command_work_without_adb(self):
        for arguments in ([], ['--help']):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(HERE / 'speaker.py'), *arguments],
                    env={**os.environ, 'PATH': ''}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, '')
                self.assertIn('stream: forward desktop audio', result.stdout)
                self.assertIn('Advanced options:', result.stdout)
                self.assertIn('python3 speaker.py stream', result.stdout)

    def test_cli_gain_defaults_and_overrides(self):
        for arguments, expected_gain in [(['stream'], 1.0), (['tone'], 0.25),
                                         (['stream', '--gain', '0.5'], 0.5),
                                         (['tone', '--gain', '1'], 1.0)]:
            with self.subTest(arguments=arguments), \
                 patch.object(sys, 'argv', ['speaker.py', *arguments]), \
                 patch.object(speaker.shutil, 'which', return_value='/fake/tool'), \
                 patch.object(speaker, 'choose_device', return_value=['adb', '-s', 'test-phone']), \
                 patch.object(speaker, 'receive') as receive:
                speaker.main()
                receive.assert_called_once_with(['adb', '-s', 'test-phone'], arguments[0],
                                                None, expected_gain, False, 'default', 'pulse')

    def test_pipewire_requires_a_playback_target(self):
        with patch.object(speaker.subprocess, 'check_output', return_value='\n'):
            with self.assertRaisesRegex(RuntimeError, 'No default playback sink'):
                speaker.capture_command('pipewire')

    def test_pipewire_is_rejected_for_tone(self):
        result = subprocess.run([sys.executable, str(HERE / 'speaker.py'), 'tone',
                                 '--capture', 'pipewire'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--capture pipewire is available only for stream', result.stderr)

    def test_invalid_priority_is_rejected_before_connecting(self):
        result = subprocess.run([sys.executable, str(HERE / 'speaker.py'), 'stream',
                                 '--priority', 'realtime'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid choice', result.stderr)

    def test_watch_is_rejected_for_tone(self):
        result = subprocess.run([sys.executable, str(HERE / 'speaker.py'), 'tone', '--watch'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--watch is available only for stream', result.stderr)

    def test_disconnect_stops_capture_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adb = root / 'adb'
            adb.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
root = Path(os.environ['SPEAKER_TEST_ROOT'])
if 'app_process' in sys.argv:
    print('READY', flush=True)
    sys.stdin.buffer.read(4)
    (root / 'offline').touch()
    sys.exit(1)
elif 'get-state' in sys.argv:
    sys.exit(1)
elif 'shell' in sys.argv:
    (root / 'unexpected-cleanup').touch()
''')
            adb.chmod(0o755)
            capture = root / 'parec'
            capture.write_text('''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
Path(os.environ['SPEAKER_TEST_ROOT'], 'capture-pid').write_text(str(os.getpid()))
sys.stdout.buffer.write(b'\\0' * 4)
sys.stdout.buffer.flush()
time.sleep(30)
''')
            capture.chmod(0o755)
            errors = io.StringIO()
            with patch.dict(os.environ, {'PATH': str(root) + ':' + os.environ['PATH'],
                                        'SPEAKER_TEST_ROOT': str(root)}), \
                 patch.object(speaker, 'build', return_value=root / 'classes.dex'), \
                 patch.object(speaker.Path, 'home', return_value=root), \
                 contextlib.redirect_stderr(errors):
                with self.assertRaisesRegex(RuntimeError, 'Phone disconnected'):
                    speaker.receive([str(adb)], 'stream', 2)
            self.assertTrue((root / 'offline').exists())
            self.assertFalse((root / 'unexpected-cleanup').exists())
            self.assertIn('After reconnecting', errors.getvalue())
            with self.assertRaises(ProcessLookupError):
                os.kill(int((root / 'capture-pid').read_text()), 0)
            with (root / '.cache/adb-speaker/session.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_receiver_readiness_timeout(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'],
                                   stdout=subprocess.PIPE)
        try:
            with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
                speaker.wait_ready(process, timeout=.05)
        finally:
            speaker.stop(process)
            if process.stdout is not None:
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
elif 'get-state' in sys.argv: print('device')
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
    assert sys.argv[-2] == os.environ['SPEAKER_TEST_DISPLAY']
    assert sys.argv[-1] == os.environ['SPEAKER_TEST_PRIORITY']
    assert not os.path.exists(os.environ['SPEAKER_TEST_CALLS'])
    print('READY', flush=True)
    assert len(sys.stdin.buffer.read()) > 0
elif 'get-state' in sys.argv: print('device')
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
            native = root / 'pw-cat'
            native.write_text(capture.read_text())
            native.chmod(0o755)
            stdbuf = root / 'stdbuf'
            stdbuf.write_text('''#!/usr/bin/env python3
import os, sys
assert sys.argv[1] == '-o0'
os.execvp(sys.argv[2], sys.argv[2:])
''')
            stdbuf.chmod(0o755)
            with patch.dict(os.environ, {'PATH': str(root) + ':' + os.environ['PATH'],
                                        'SPEAKER_TEST_CALLS': str(calls)}), \
                 patch.object(speaker, 'build', return_value=root / 'classes.dex'), \
                 patch.object(speaker.Path, 'home', return_value=root):
                for watch, tty, display, priority, backend in [(False, False, 'quiet', 'default', 'pulse'),
                                                               (True, False, 'log', 'audio', 'pulse'),
                                                               (True, True, 'terminal', 'urgent', 'pulse'),
                                                               (True, False, 'log', 'default', 'pipewire')]:
                    with self.subTest(display=display), \
                         patch.dict(os.environ, {'SPEAKER_TEST_DISPLAY': display,
                                                 'SPEAKER_TEST_PRIORITY': priority}), \
                         patch.object(speaker.subprocess, 'check_output', return_value='test-playback-sink\n'), \
                         patch.object(speaker.sys.stderr, 'isatty', return_value=tty):
                        calls.unlink(missing_ok=True)
                        speaker.receive([str(adb)], 'stream', .5, watch=watch, priority=priority,
                                        capture_backend=backend)
                        args = json.loads(calls.read_text())
                        if backend == 'pulse':
                            self.assertIn('--device=@DEFAULT_MONITOR@', args)
                        else:
                            self.assertEqual(args[args.index('--target') + 1], 'test-playback-sink')
                            self.assertIn('stream.capture.sink=true', args[args.index('--properties') + 1])
                            self.assertIn('--raw', args)


if __name__ == '__main__':
    unittest.main()
