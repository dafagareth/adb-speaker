# USB performance checks

## Local results, 2026-10-29

The Linux relay now resumes audio after sending the second periodic clock probe,
without waiting for its reply. It still waits for the first reply to drain earlier
audio. Android flushes the second reply before writing subsequent PCM to AudioTrack.
Clock sample acceptance, queue limits, and playback buffer defaults are unchanged.

The regression test failed with the old relay and passed with the change. It checks
packet order, fragmented replies, and preservation of the original PCM read times.

A local pipe experiment compared HEAD `b95b866` with the edited relay. Each run lasted
32 seconds and sent six probes. The fixture generated 960 bytes every 5 ms, simulated
30 ms of playback buffering, and delayed probe replies by 10 ms on the return path.
It used Python 3.14 on Linux, with `cProfile` enabled.

| Measurement | Before | After |
| --- | ---: | ---: |
| Largest receiver input gap within 200 ms after a probe | 36.1 ms | 15.9 ms |
| Relay process CPU time | 0.694 s | 0.777 s |
| Relay CPU usage, one core | 2.17% | 2.43% |
| Host PCM discarded | 0 ms | 0 ms |

These are single synthetic runs on a shared desktop, not USB latency or CPU
regression benchmarks. CPU figures include profiling overhead and exclude the
capture process, ADB, and Android. Most elapsed time was spent waiting in `select`.
There is no measured reason here to rewrite the relay or add compression.

A separate deterministic test models host/phone monotonic clock differences of
±100 ppm for ten simulated minutes. With symmetric 2 ms probe round trips every
10 seconds, mapping error stays below 5 ms. This does not test the capture or
playback sample clocks, asymmetric USB delays, or audible artifacts. No audio
resampling or drift correction was added.

## Device checks still needed

Device testing was deferred because no phone was connected. Linux keeps its 30 ms
playback buffer; 20 ms remains a candidate, not a verified new default.

- Compare the old and new relay at 30 ms over the same USB connection, five minutes
  each. Repeat in reverse order and check underruns around each 10-second probe.
- Compare 30 and 20 ms with the new relay using the same repeating audio. Record
  the actual buffer size, underruns, host/receiver drops, and valid presentation
  delay samples. Listen for clicks; exclude shutdown counters from steady playback.
- Run the better buffer setting for at least 30 minutes. Record clock offsets and
  round trips alongside queue and playback timing before attributing changes to
  sample-clock drift. Add rate correction only if sustained drift is demonstrated.
- Profile Python, capture, ADB, and Android separately during playback. Repeat
  without the profiler before claiming CPU improvements. Windows needs its own run.

`presentation_delay` excludes earlier capture buffering and acoustic output delay.
Physical end-to-end latency needs a separate measurement.
