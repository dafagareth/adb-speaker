# adb-speaker

My laptop speakers stopped working, so I built this to use my Android phone as a speaker.
It sends desktop audio over USB with ADB, without installing an Android app.
Version 0.2.0 is experimental on Linux and Windows.

```mermaid
flowchart LR
    Desktop[Desktop audio] --> Capture[Host capture] --> ADB --> Receiver[Temporary Android receiver] --> Speaker[Phone speaker]
```

## Setup

1. Enable **USB debugging** on your phone (under Developer Options).
2. Connect your phone via USB and tap **Allow** on the computer authorization prompt.
3. Verify connection:
   - With system ADB: `adb devices`
   - With portable release: `.\_internal\bin\adb.exe devices` (Windows) or `./_internal/bin/adb devices` (Linux)
   The phone should be listed as `device`.

## Install and Run

### Portable Releases (Recommended — Zero Dependencies)

Download a package from [Releases](https://github.com/dafagareth/adb-speaker/releases),
extract it, and run from a terminal:

- **Windows:** `.\adb-speaker.exe stream` (bundles Python, WASAPI capture helper, and ADB)
- **Linux (x86_64, glibc 2.35+):** `./adb-speaker stream` (bundles Python, ADB, and `parec`; requires PulseAudio or PipeWire-Pulse)

On Windows, double-clicking `adb-speaker.exe` shows help and closes; use CMD or PowerShell.

### From Source (pip install)

Building or running from source does not bundle external tools. Ensure prerequisites are installed:
- **Linux:** Python 3.10+, `adb`, and `parec` (pulseaudio-utils) on PATH.
- **Windows:** Python 3.10+, `adb` on PATH, and compiled [WASAPI helper](docs/internals.md#windows-helper) on PATH.

```sh
python -m pip install .
adb-speaker stream
# Or run without installing:
python speaker.py stream
```

## Use

```sh
adb-speaker stream                 # Play desktop audio on the phone
adb-speaker stream --watch         # Show audio statistics (Linux only)
adb-speaker tone                   # Check phone playback
adb-speaker stream --serial SERIAL # Choose one connected phone
adb-speaker --help
```

Adjust the phone's media volume; `--gain 0.5` halves the receiver gain.
Use `--seconds 60` for a timed stream. Ctrl+C stops playback. After a cable
disconnect, reconnect and run again. One session can run per user.

## Troubleshooting

- **Phone missing:** check the USB cable and the USB debugging authorization prompt.
  On Linux, you may need Android udev rules. On Windows, if the phone is not listed,
  install your manufacturer's [OEM USB Driver](https://developer.android.com/studio/run/oem-usb)
  (or [Google USB Driver](https://developer.android.com/studio/run/win-usb) for Pixel devices).
- **No sound:** check phone volume, then try `tone`. If it works, check desktop
  capture; on Linux, `pactl info` should reach your audio server. Windows output
  must be mono/stereo at 48 kHz or below.
- **Audio gaps or delay:** try another cable or USB port and record a `--watch` log.
  Compare underruns within one session. Packet age is not total playback latency.
- **Session already running:** stop the existing process. An old lock file alone
  does not hold the lock.
- **Cleanup incomplete:** reconnect and run the printed cleanup command while no
  stream is active; it removes temporary receiver files.

See [internals and development](docs/internals.md), [contributing](docs/internals.md#contributing),
and [changelog](CHANGELOG.md). Windows playback has been tested in VMs, including
the portable package in a Windows Server VM. Physical Windows hardware and measured
end-to-end latency remain unverified.

## License

Copyright (c) 2026 dafagareth. [MIT](LICENSE). Bundled dependencies keep their own licenses.
