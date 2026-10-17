/*
 * Project: adb-speaker
 * File: PlaybackDelay.java
 * Description: Host-read-to-presentation delay estimation from advancing AudioTrack timestamps.
 *
 * Copyright (c) 2026 dafagareth
 * SPDX-License-Identifier: MIT
 * Licensed under the MIT License (see LICENSE in repository root).
 * https://opensource.org/licenses/MIT
 */

/**
 * Estimates host-read-to-presentation delay from advancing AudioTrack timestamps.
 * Kept free of Android imports so host tests can verify edge cases with standard javac/java.
 */
final class PlaybackDelay {
    private long previousFrame;
    private long previousTime;
    private int previousUnderruns;
    private boolean ready;

    long estimate(boolean available, long frame, long time, long now, int underruns,
                  long packetFrame, long packetTime) {
        if (!available || now - time < 0 || now - time > 1_000_000_000L) {
            ready = false;
            return -1;
        }
        // HAL timestamps can stall during warmup or after an underrun; require two
        // strictly advancing samples with no intervening underruns before trusting the slope.
        boolean advancing = ready && (int) (frame - previousFrame) > 0
                && time > previousTime && underruns == previousUnderruns;
        previousFrame = frame;
        previousTime = time;
        previousUnderruns = underruns;
        ready = true;
        // AudioTrack's underlying 32-bit frame counter wraps every ~24h51m at 48 kHz,
        // while packetFrame grows as a 64-bit long; signed 32-bit subtraction preserves the delta.
        long frames = (int) (packetFrame - frame);
        if (!advancing || packetTime == 0 || Math.abs(frames) > 48000) return -1;
        long delay = time + frames * 1_000_000_000L / 48000 - packetTime;
        return delay < 0 ? -1 : delay;
    }
}
