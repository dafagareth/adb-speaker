/*
 * Project: adb-speaker
 * File: AdbSpeaker.java
 * Description: Android receiver playing stereo 48kHz 16-bit PCM via AudioTrack.
 *
 * Copyright (c) 2026 dafagareth
 * SPDX-License-Identifier: MIT
 * Licensed under the MIT License (see LICENSE in repository root).
 * https://opensource.org/licenses/MIT
 */
import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioFormat;
import android.media.AudioTimestamp;
import android.media.AudioTrack;
import android.os.Process;
import android.os.Debug;
import java.io.EOFException;
import java.io.IOException;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.DataInputStream;
import java.io.BufferedInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Receives stereo 48 kHz signed little-endian 16-bit PCM over ADB stdin. */
public final class AdbSpeaker {
    private static final int RATE = 48000;
    private static final int FRAME_BYTES = 4;

    public static void main(String[] args) {
        String readyPath = args.length > 2 ? args[2] : null;
        if ("-".equals(readyPath)) readyPath = null;
        try {
            int bufferMs = args.length > 3 ? Integer.parseInt(args[3]) : 30;
            if (bufferMs < 10 || bufferMs > 200) throw new IllegalArgumentException("Invalid audio buffer size");
            boolean packets = args.length > 4;
            if (packets && !args[4].equals("packet-v1")) throw new IllegalArgumentException("Unknown audio protocol");
            float gain = args.length == 0 ? 0.25f : Float.parseFloat(args[0]);
            if (Float.isNaN(gain) || Float.isInfinite(gain) || gain < 0 || gain > 1) {
                throw new IllegalArgumentException("Gain must be between 0 and 1");
            }
            receive(gain, args.length > 1 ? args[1] : "quiet", readyPath, bufferMs, packets);
            // app_process may retain Android Binder threads after main returns.
            System.exit(0);
        } catch (Exception error) {
            if (readyPath != null) {
                try {
                    writeStatus(readyPath, "ERROR " + error.getMessage());
                } catch (IOException ignored) {
                    // The host will report its readiness timeout if the marker cannot be written.
                }
            }
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private static void receive(float gain, String display, String readyPath, int bufferMs, boolean packets) throws Exception {
        boolean watch = !display.equals("quiet");
        boolean terminal = display.equals("terminal");
        int minimum = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) {
            throw new IOException("Unsupported audio format: " + minimum);
        }
        int targetFrames = RATE * bufferMs / 1000;
        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                .setBufferSizeInBytes(Math.max(minimum, Math.max(3840, targetFrames * FRAME_BYTES)))
                .build();
        try {
            if (track.getState() != AudioTrack.STATE_INITIALIZED) {
                throw new IOException("AudioTrack did not initialize");
            }
            if (track.setBufferSizeInFrames(targetFrames) < 0) {
                throw new IOException("AudioTrack buffer tuning failed");
            }
            // Quiet proof-of-concept; leave the phone's global media volume unchanged.
            track.setVolume(gain);
            boolean playing = false;
            InputStream input = System.in;
            DataInputStream packetInput = new DataInputStream(new BufferedInputStream(input, 4096));
            AudioTimestamp stamp = new AudioTimestamp();
            PlaybackDelay playbackDelay = new PlaybackDelay();
            long[] metadata = new long[3];
            long sequence = -1;
            long discarded = 0;
            long packetAge = 0;
            long maxPacketAge = 0;
            long lastFrame = 0;
            long lastStamp = 0;
            byte[] buffer = new byte[960];
            int pending = 0;
            long bytes = 0;
            System.err.println("READY pid=" + Process.myPid() + " rate=" + RATE
                    + " buffer=" + track.getBufferSizeInFrames()
                    + " performance=" + track.getPerformanceMode()
                    + " priority=" + Process.getThreadPriority(Process.myTid()));
            if (readyPath == null) {
                System.out.println("READY");
                System.out.flush();
            } else {
                writeStatus(readyPath, "READY");
            }
            long started = System.nanoTime();
            long cpuStarted = Debug.threadCpuTimeNanos();
            long lastReport = started;
            long lastBytes = 0;
            int count;
            while (true) {
                if (packets) {
                    count = AudioPacket.read(packetInput, buffer, metadata);
                    if (count == -1) break;
                    if (metadata[1] != sequence + 1) throw new IOException("Audio packet sequence mismatch");
                    sequence = metadata[1];
                    if (metadata[0] == 0) {
                        System.out.println("SYNC " + sequence + " " + System.nanoTime());
                        System.out.flush();
                        continue;
                    }
                    // Timestamp 0 disables age checks when the host lacks a reliable clock sample.
                    // ponytail: static 100 ms ceiling covers the 50 ms host queue plus up to 25 ms
                    // one-way error from 50 ms RTT probes; tighten only if probe bounds shrink.
                    packetAge = metadata[2] == 0 ? 0 : Math.max(0, System.nanoTime() - metadata[2]);
                    maxPacketAge = Math.max(maxPacketAge, packetAge);
                    if (packetAge > 100_000_000L) {
                        discarded += count;
                        count = 0;
                    }
                } else {
                    count = input.read(buffer, pending, buffer.length - pending);
                    if (count == -1) break;
                }
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
                if (packets && aligned > 0) {
                    lastFrame = (bytes - aligned) / FRAME_BYTES;
                    lastStamp = metadata[2];
                }
                pending = available - aligned;
                System.arraycopy(buffer, aligned, buffer, 0, pending);
                if (watch) {
                    // These counters describe AudioTrack input and HAL timestamps, not acoustic latency.
                    long now = System.nanoTime();
                    if (now - lastReport >= 1_000_000_000L) {
                        String status = String.format(Locale.ROOT,
                                "AUDIO | %ds | %.1f KiB/s | %.2f MiB | buffer %.0fms | underruns %d",
                                (now - started) / 1_000_000_000L,
                                (bytes - lastBytes) / 1024.0 / ((now - lastReport) / 1e9),
                                bytes / 1048576.0, track.getBufferSizeInFrames() * 1000.0 / RATE,
                                track.getUnderrunCount());
                        if (packets) {
                            // Query AudioTrack.getTimestamp() at 1 Hz report intervals rather than per packet
                            // to avoid HAL binder overhead in the audio write loop.
                            long latency = playbackDelay.estimate(playing && track.getTimestamp(stamp),
                                    stamp.framePosition, stamp.nanoTime, System.nanoTime(),
                                    track.getUnderrunCount(), lastFrame, lastStamp);
                            status += String.format(Locale.ROOT,
                                    " | packet_age %s | presentation_delay %s | skipped %.1fms",
                                    metadata[2] == 0 ? "unknown" : String.format(Locale.ROOT, "%.1fms", packetAge / 1e6),
                                    latency < 0 ? "unknown" : String.format(Locale.ROOT, "%.1fms", latency / 1e6),
                                    discarded * 1000.0 / (RATE * FRAME_BYTES));
                        }
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
                    + " discarded_bytes=" + discarded + " max_packet_age_ms=" + maxPacketAge / 1_000_000L
                    + " elapsed_ms=" + (System.nanoTime() - started) / 1_000_000L
                    + " thread_cpu_ms=" + (Debug.threadCpuTimeNanos() - cpuStarted) / 1_000_000L);
        } finally {
            track.release();
        }
    }

    private static void writeStatus(String path, String status) throws IOException {
        try (FileOutputStream output = new FileOutputStream(path)) {
            output.write(status.getBytes(StandardCharsets.UTF_8));
        }
    }

    static final class AudioPacket {
        static int read(DataInputStream input, byte[] pcm, long[] metadata) throws IOException {
            int first = input.read();
            if (first == -1) return -1;
            try {
                int magic = (first << 24) | (input.readUnsignedByte() << 16)
                        | (input.readUnsignedByte() << 8) | input.readUnsignedByte();
                if (magic != 0x41444231) throw new IOException("Invalid audio packet magic");
                int type = input.readInt();
                metadata[0] = type;
                metadata[1] = input.readLong();
                metadata[2] = input.readLong();
                int length = input.readInt();
                if (metadata[1] < 0 || (type != 0 && type != 1)
                        || (type == 0 && length != 0)
                        || (type == 1 && (length <= 0 || length > pcm.length || length % FRAME_BYTES != 0))) {
                    throw new IOException("Invalid audio packet header");
                }
                input.readFully(pcm, 0, length);
                return length;
            } catch (EOFException truncated) {
                throw new IOException("Truncated audio packet", truncated);
            }
        }
    }
}
