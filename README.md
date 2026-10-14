# adb-speaker

My laptop speakers broke, so I built this to use my Android phone as a speaker.
It sends Linux desktop audio to the phone over ADB, without installing an Android app.

## Installation

You need Linux, Python 3, `adb`, and `parec`, with PulseAudio or PipeWire's
PulseAudio compatibility server running. The Android receiver is included;
Java and the Android SDK are only needed if you change its source.

1. Download or clone this repository and open its directory.
2. Enable USB debugging on your phone, connect it by USB, and approve the debugging prompt.
3. Check that `adb devices` lists your phone as `device`.
4. Start streaming:

   ```bash
   python3 speaker.py stream
   ```

For the shorter `adb-speaker` command, run these from the repo:

```bash
mkdir -p ~/.local/bin
chmod +x speaker.py
ln -s "$PWD/speaker.py" ~/.local/bin/adb-speaker
```

Keep the repo in place and make sure `~/.local/bin` is on your `PATH`.

## Usage

```bash
adb-speaker stream                  # Play desktop audio on the phone
adb-speaker stream --watch          # Show audio statistics
adb-speaker tone                    # Play three test notes
adb-speaker --help                  # Show all options
```

Adjust the listening volume on your phone. Streaming uses full receiver gain;
`--gain 0.5` lowers it to 50%. Test tones default to 25% gain.

If several phones are connected, select one with `--serial SERIAL`, using the
serial shown by `adb devices`. One streaming session can run at a time.

Press Ctrl+C to stop. If the cable disconnects, reconnect it and run the command again.

## How it works

```text
Desktop audio → PulseAudio/PipeWire monitor → parec → ADB → AudioTrack → Phone
```

The program pushes a small DEX receiver to the phone and starts it with
`app_process`. Audio travels as uncompressed stereo PCM at 48 kHz. Python manages
the processes; the audio flows directly from capture to ADB. The receiver is
removed when the session ends normally.

The watcher shows data rate, effective buffer size, and Android's underrun count.
It does not measure the delay between the laptop and the speaker.

Tested on a POCO 23122PCD1G running Android 16. Other phones and screen-off
playback still need verification; end-to-end latency has not been reliably measured.

## References

- [Android Developers: AudioTrack](https://developer.android.com/reference/android/media/AudioTrack)
- [Android Developers: ADB](https://developer.android.com/tools/adb)
- [PipeWire: pw-cat](https://docs.pipewire.org/page_man_pw-cat_1.html)

## License

Copyright (c) 2026 dafagareth. [MIT](LICENSE).
External tools and libraries retain their own licenses.
