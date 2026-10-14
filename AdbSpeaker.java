import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Process;
import java.io.IOException;
import java.io.InputStream;

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
            receive(gain);
            // app_process may retain Android Binder threads after main returns.
            System.exit(0);
        } catch (Exception error) {
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private static void receive(float gain) throws Exception {
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
            track.play();
            System.err.println("READY pid=" + Process.myPid() + " rate=" + RATE
                    + " buffer=" + track.getBufferSizeInFrames()
                    + " performance=" + track.getPerformanceMode());
            System.out.println("READY");
            System.out.flush();
            InputStream input = System.in;
            byte[] buffer = new byte[960];
            int pending = 0;
            long bytes = 0;
            int count;
            while ((count = input.read(buffer, pending, buffer.length - pending)) != -1) {
                int available = pending + count;
                int aligned = available - available % FRAME_BYTES;
                int offset = 0;
                while (offset < aligned) {
                    int written = track.write(buffer, offset, aligned - offset, AudioTrack.WRITE_BLOCKING);
                    if (written <= 0) {
                        throw new IOException("AudioTrack write failed: " + written);
                    }
                    offset += written;
                    bytes += written;
                }
                pending = available - aligned;
                System.arraycopy(buffer, aligned, buffer, 0, pending);
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
            System.err.println("PLAYED bytes=" + bytes + " frames="
                    + Integer.toUnsignedLong(track.getPlaybackHeadPosition())
                    + " route=" + (route == null ? "unknown" : route.getType())
                    + " underruns=" + track.getUnderrunCount());
        } finally {
            track.release();
        }
    }
}
