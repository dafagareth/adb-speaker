// SPDX-License-Identifier: MIT
/*
 * adb-speaker — Linux desktop audio to Android over ADB
 * Copyright (c) 2026 dafagareth
 *
 * Receives stereo PCM audio through a temporary Android process.
 */
import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Process;
import android.os.Debug;
import java.io.IOException;
import java.io.InputStream;
import java.util.Locale;

/** Receives stereo 48 kHz signed little-endian 16-bit PCM over ADB stdin. */
public final class AdbSpeaker {
    private static final int RATE = 48000;
    private static final int FRAME_BYTES = 4;

    public static void main(String[] args) {
        try {
            float gain = args.length == 0 ? 0.25f : Float.parseFloat(args[0]);
            if (Float.isNaN(gain) || Float.isInfinite(gain) || gain < 0 || gain > 1) {
                throw new IllegalArgumentException("Gain must be between 0 and 1");
            }
            String priority = args.length > 2 ? args[2] : "default";
            if (!priority.equals("default") && !priority.equals("audio") && !priority.equals("urgent")) {
                throw new IllegalArgumentException("Invalid thread priority");
            }
            if (!priority.equals("default")) {
                try {
                    Process.setThreadPriority(priority.equals("audio")
                            ? Process.THREAD_PRIORITY_AUDIO : Process.THREAD_PRIORITY_URGENT_AUDIO);
                } catch (SecurityException denied) {
                    System.err.println("PRIORITY request denied; keeping current thread priority");
                }
            }
            receive(gain, args.length > 1 ? args[1] : "quiet");
            // app_process may retain Android Binder threads after main returns.
            System.exit(0);
        } catch (Exception error) {
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private static void receive(float gain, String display) throws Exception {
        boolean watch = !display.equals("quiet");
        boolean terminal = display.equals("terminal");
        int minimum = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) {
            throw new IOException("Unsupported audio format: " + minimum);
        }
        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                .setBufferSizeInBytes(Math.max(minimum, 3840))
                .build();
        try {
            if (track.getState() != AudioTrack.STATE_INITIALIZED) {
                throw new IOException("AudioTrack did not initialize");
            }
            // Leave jitter headroom: 10 and 20 ms buffers underrun on the tested phone.
            if (track.setBufferSizeInFrames(RATE * 30 / 1000) < 0) {
                throw new IOException("AudioTrack buffer tuning failed");
            }
            // Quiet proof-of-concept; leave the phone's global media volume unchanged.
            track.setVolume(gain);
            boolean playing = false;
            InputStream input = System.in;
            byte[] buffer = new byte[960];
            int pending = 0;
            long bytes = 0;
            System.err.println("READY pid=" + Process.myPid() + " rate=" + RATE
                    + " buffer=" + track.getBufferSizeInFrames()
                    + " performance=" + track.getPerformanceMode()
                    + " priority=" + Process.getThreadPriority(Process.myTid()));
            System.out.println("READY");
            // The host waits for this signal before starting capture.
            System.out.flush();
            long started = System.nanoTime();
            long cpuStarted = Debug.threadCpuTimeNanos();
            long lastReport = started;
            long lastBytes = 0;
            int count;
            while ((count = input.read(buffer, pending, buffer.length - pending)) != -1) {
                int available = pending + count;
                // Pipe reads may split a stereo frame; keep its trailing bytes for the next read.
                int aligned = available - available % FRAME_BYTES;
                int offset = 0;
                while (offset < aligned) {
                    int written = track.write(buffer, offset, aligned - offset, AudioTrack.WRITE_BLOCKING);
                    if (written <= 0) {
                        throw new IOException("AudioTrack write failed: " + written);
                    }
                    offset += written;
                    bytes += written;
                    if (!playing) {
                        // Start only after PCM arrives, so capture startup cannot starve playback.
                        track.play();
                        playing = true;
                    }
                }
                pending = available - aligned;
                System.arraycopy(buffer, aligned, buffer, 0, pending);
                if (watch) {
                    // These counters describe AudioTrack input, not acoustic latency.
                    long now = System.nanoTime();
                    if (now - lastReport >= 1_000_000_000L) {
                        String status = String.format(Locale.ROOT,
                                "AUDIO | %ds | %.1f KiB/s | %.2f MiB | buffer %.0fms | underruns %d",
                                (now - started) / 1_000_000_000L,
                                (bytes - lastBytes) / 1024.0 / ((now - lastReport) / 1e9),
                                bytes / 1048576.0, track.getBufferSizeInFrames() * 1000.0 / RATE,
                                track.getUnderrunCount());
                        System.err.print(terminal ? "\r\033[2K" + status : status + "\n");
                        System.err.flush();
                        lastReport = now;
                        lastBytes = bytes;
                    }
                }
            }
            if (pending != 0) {
                throw new IOException("Truncated PCM frame");
            }
            long deadline = System.nanoTime() + 2_000_000_000L;
            while (Integer.toUnsignedLong(track.getPlaybackHeadPosition()) < bytes / FRAME_BYTES
                    && System.nanoTime() < deadline) {
                Thread.sleep(10);
            }
            AudioDeviceInfo route = track.getRoutedDevice();
            if (terminal) System.err.println();
            System.err.println("PLAYED bytes=" + bytes + " frames="
                    + Integer.toUnsignedLong(track.getPlaybackHeadPosition())
                    + " route=" + (route == null ? "unknown" : route.getType())
                    + " underruns=" + track.getUnderrunCount()
                    + " elapsed_ms=" + (System.nanoTime() - started) / 1_000_000L
                    + " thread_cpu_ms=" + (Debug.threadCpuTimeNanos() - cpuStarted) / 1_000_000L);
        } finally {
            track.release();
        }
    }
}
