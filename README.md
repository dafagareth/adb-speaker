# adb-speaker

Streams Linux desktop playback into a temporary Android `AudioTrack` process.
The receiver is compiled locally, pushed as DEX and launched with `app_process`.
No browser, root, APK installation or TCP forwarding is involved.

Tested on the connected POCO 23122PCD1G, Android 16 / API 36. The three-note test
was confirmed audible by the owner. A ten-second desktop capture reached the
built-in speaker with 478,080 played frames and no reported buffer underruns.
End-to-end latency and screen-off operation have not yet been measured.

The receiver requests Android's low-latency path and limits its effective buffer
to 1,440 frames (30 ms), down from the original 7,688 frames (about 160 ms).
Capture requests 5 ms latency with 5 ms processing chunks; receiver reads are
also 5 ms. The phone accepted low-latency mode. A 480-frame buffer produced 10
underruns in 30 seconds; 960 frames produced zero in 20 seconds but one on a
30-second retest, so the default leaves more headroom. The final 1,440-frame
setting completed a 30-second test with zero reported underruns. These sizes
do not measure total laptop-to-speaker delay; stability under load may differ.

Capture starts only after the Android receiver signals readiness, preventing
audio from queuing during receiver startup. A missing readiness signal times out
after ten seconds. A local capture-only check saw median delivery intervals drop
from about 10.65 ms to 5.33 ms with the smaller capture request; this does not
measure acoustic latency. The existing PulseAudio capture remains in use.
The combined readiness/5 ms capture version completed a 30-second phone test
with one reported underrun; glitch-free operation is not yet established.

## Run

From this repository:

```bash
# Three ascending notes. Be ready to listen before running it.
python3 speaker.py tone

# Copy current laptop playback to the phone until Ctrl+C.
python3 speaker.py stream

# Full receiver gain (the default is 25%).
python3 speaker.py stream --gain 1

# Stop automatically after ten seconds.
python3 speaker.py stream --seconds 10
```

Only one authorized ADB device may be connected unless `--serial SERIAL` is set.
`ANDROID_SERIAL` is also supported. USB debugging authorization is needed once.

The receiver defaults to 25% gain without changing the phone's system volume.
For normal receiver gain, add `--gain 1`; adjust carefully using the current media
volume on the phone. The laptop's existing output is copied, not muted or rerouted.
The capture source is the playback monitor, not the microphone.

Requirements: Python 3, adb, parec (PulseAudio or
PipeWire's PulseAudio compatibility), javac and Android SDK platform/build-tools.
Set `ANDROID_SDK_ROOT` or `ANDROID_HOME` if the SDK is outside `~/Android/Sdk`.
The first run builds `build/classes.dex`; later runs reuse it until Java changes.

Each session removes `/data/local/tmp/daemontalk-adb-speaker.dex` when it finishes.
If the USB cable is removed or the host is killed, cleanup cannot be guaranteed.
After reconnecting, remove a leftover file with:

```bash
adb shell unlink /data/local/tmp/daemontalk-adb-speaker.dex
```

Sessions are serialized with a local lock. Cleanup targets only the unique
receiver process launched by that session. No phone packages or persistent phone
settings are changed. Laptop build files remain in the ignored `build/` directory.

## Scope

Audio is raw stereo 48 kHz / signed 16-bit little-endian PCM, about 192 KB/s.
There is no video receiver yet. Android/OEM audio routing and power management
can differ; compatibility with other phones is not established by this test.
A speaker route and played frames confirm the audio pipeline, not an acoustic
latency measurement. Avoid forwarding the phone back into the same desktop output,
which would create an audio loop.

Host-side lifecycle tests use fake adb/parec and never contact a phone:

```bash
python3 -m unittest discover -s . -p 'test_*.py'
```
