# Changelog

## 0.2.0 — 2026-10-17 (Experimental)

Changes since `v0.1.0`.

- Added Windows WASAPI capture with ADB `exec-in`, session locking, and audio conversion.
  Fixed resampling across capture packets and audio discontinuities.
- Added portable Linux and Windows builds with Python, ADB, and capture tools,
  plus dependency notices, checksums, and smoke checks. Windows pins Platform-Tools r35.0.0.
- Added Linux packet timestamps, clock synchronization, a 50 ms relay queue, and stale-audio
  rejection. Fixed startup timeouts, playback startup, buffer allocation, and cleanup.
- Reorganized Python/native sources and tests; added pip installation, module execution,
  `--version`, Makefile, Linux/Windows CI, draft release workflow, and contributor docs.
- Select capture by OS and reject unsupported options. Removed `--capture pipewire`
  and `--priority`; `--watch` remains Linux-only.

A 900-second screen-locked phone session was reported successful. Windows playback
was demonstrated in a Windows 10 VM; the Windows portable package was also tested
in a Windows Server VM, with audio reported to sound comparable to Linux.
Physical Windows hardware and measured end-to-end latency remain unverified.
Windows capture supports mono/stereo at 48 kHz or below. One session per user;
reconnect requires rerunning the command.

## 0.1.0 — Experimental

Initial version tagged at commit `2bb2780`.

- Linux desktop audio over ADB with a bundled temporary Android receiver; no APK or Java
  needed for normal use. Included PulseAudio capture and experimental PipeWire/priority options.
- `stream`, `tone`, device selection, gain, duration limits, and audio statistics,
  with session locking, cleanup, and disconnect diagnostics.
- Host tests, setup instructions, and MIT license.
