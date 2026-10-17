/*
 * Project: adb-speaker
 * File: TestPlaybackDelay.java
 * Description: Unit tests for PlaybackDelay timestamp progression, underrun resets, and 32-bit wrap.
 *
 * Copyright (c) 2026 dafagareth
 * SPDX-License-Identifier: MIT
 * Licensed under the MIT License (see LICENSE in repository root).
 * https://opensource.org/licenses/MIT
 */
public final class TestPlaybackDelay {
    private static final long SECOND = 1_000_000_000L;

    private static void equal(long expected, long actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }

    private static PlaybackDelay primed() {
        PlaybackDelay delay = new PlaybackDelay();
        equal(-1, delay.estimate(true, 48000, 10 * SECOND, 10 * SECOND, 0, 48240, 10 * SECOND));
        return delay;
    }

    public static void main(String[] args) {
        PlaybackDelay delay = primed();
        equal(25_000_000, delay.estimate(true, 96000, 11 * SECOND, 11 * SECOND,
                0, 96240, 11 * SECOND - 20_000_000));
        // Reusing an old timestamp must not turn an extrapolated negative delay into zero.
        equal(-1, delay.estimate(true, 96000, 11 * SECOND, 12 * SECOND,
                0, 144240, 12 * SECOND));
        equal(-1, primed().estimate(true, 96000, 11 * SECOND, 11 * SECOND,
                0, 96240, 11 * SECOND + 10_000_000));
        equal(-1, primed().estimate(true, 96000, 11 * SECOND, 11 * SECOND,
                0, 96240, 0));
        equal(-1, primed().estimate(true, 96000, 11 * SECOND, 11 * SECOND,
                0, 0, 10 * SECOND));

        delay = primed();
        equal(-1, delay.estimate(true, 96000, 11 * SECOND, 11 * SECOND,
                1, 96240, 11 * SECOND));
        equal(5_000_000, delay.estimate(true, 144000, 12 * SECOND, 12 * SECOND,
                1, 144240, 12 * SECOND));

        // Missing, stale, and future timestamps require a fresh advancing pair.
        for (int failure = 0; failure < 3; failure++) {
            delay = primed();
            long now = failure == 1 ? 13 * SECOND : failure == 2 ? 10 * SECOND : 11 * SECOND;
            equal(-1, delay.estimate(failure != 0, 96000, 11 * SECOND, now,
                    0, 96240, 11 * SECOND));
            equal(-1, delay.estimate(true, 144000, 12 * SECOND, 12 * SECOND,
                    0, 144240, 12 * SECOND));
            equal(5_000_000, delay.estimate(true, 192000, 13 * SECOND, 13 * SECOND,
                    0, 192240, 13 * SECOND));
        }

        delay = new PlaybackDelay();
        long wrap = 1L << 32;
        equal(-1, delay.estimate(true, wrap - 48000, 10 * SECOND, 10 * SECOND,
                0, wrap - 47760, 10 * SECOND));
        equal(25_000_000, delay.estimate(true, 0, 11 * SECOND, 11 * SECOND,
                0, wrap + 240, 11 * SECOND - 20_000_000));
        // The packet can precede the timestamp across wrap, including later wraps.
        equal(15_000_000, delay.estimate(true, 48000, 12 * SECOND, 12 * SECOND,
                0, 2 * wrap + 47760, 12 * SECOND - 20_000_000));
        equal(-1, delay.estimate(true, 1, 13 * SECOND, 13 * SECOND,
                0, 241, 13 * SECOND));
    }
}
