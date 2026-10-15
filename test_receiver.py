# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dafagareth
"""Optional device checks: ADB_SPEAKER_TEST_SERIAL=SERIAL python3 -m unittest test_receiver."""
import os
import subprocess
import time
import unittest
import uuid

import speaker


@unittest.skipUnless(os.environ.get('ADB_SPEAKER_TEST_SERIAL'), 'requires an explicitly selected Android device')
class ReceiverDeviceTest(unittest.TestCase):
    def test_delayed_fragmented_and_empty_input(self):
        adb = ['adb', '-s', os.environ['ADB_SPEAKER_TEST_SERIAL']]
        remote = '/data/local/tmp/adb-speaker-test-' + uuid.uuid4().hex + '.dex'
        subprocess.run([*adb, 'push', str(speaker.build()), remote], check=True,
                       stdout=subprocess.DEVNULL)
        try:
            for payload, expected in [(b'', 'PLAYED bytes=0 frames=0'),
                                      (b'\0' * 960, 'PLAYED bytes=960 frames=240'),
                                      (b'\0', 'Truncated PCM frame')]:
                with self.subTest(size=len(payload)):
                    process = subprocess.Popen(
                        [*adb, 'shell', '-T', 'CLASSPATH=' + remote,
                         'app_process', '/', 'AdbSpeaker', '0', 'quiet', 'default'],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    try:
                        speaker.wait_ready(process)
                        # Exercise an idle host and a read that ends inside a stereo frame.
                        time.sleep(.2)
                        if payload:
                            process.stdin.write(payload[:1])
                            process.stdin.flush()
                            time.sleep(.1)
                        _, errors = process.communicate(payload[1:], timeout=5)
                        self.assertIn(expected, errors.decode())
                        self.assertEqual(process.returncode, 1 if len(payload) == 1 else 0)
                    finally:
                        speaker.stop(process)
                        for pipe in (process.stdin, process.stdout, process.stderr):
                            pipe.close()
        finally:
            subprocess.run([*adb, 'shell', 'rm', '-f', remote], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
