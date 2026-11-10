// Copyright (c) 2026 dafagareth
// SPDX-License-Identifier: MIT

/**
 * Check that the AudioTrack timestamp is recent and has advanced since the last
 * sample without a new underrun. Find the packet's frame relative to that timestamp,
 * allowing for the 32-bit counter to wrap. Convert the frame difference to time at
 * 48 kHz and subtract the packet's mapped host read time. Return -1 if a check fails
 * or the calculated delay is negative.
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
