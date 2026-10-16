/*
 * Project: adb-speaker
 * File: audio_convert.hpp
 * Description: Audio sample format conversion (float/int24/int32 to s16) and rate resampling.
 *
 * Copyright (c) 2026 dafagareth
 * SPDX-License-Identifier: MIT
 * Licensed under the MIT License (see LICENSE in repository root).
 * https://opensource.org/licenses/MIT
 */
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>
namespace adb_audio {
constexpr unsigned kOutputRate = 48000;
int16_t to_s16(float value) {
    if (!std::isfinite(value)) value = 0.0f;
    value = (std::max)(-1.0f, (std::min)(value, 1.0f));
    const float scaled = value < 0.0f ? value * 32768.0f : value * 32767.0f;
    return static_cast<int16_t>(std::lrint(scaled));
}

bool read_sample(const unsigned char* data, size_t index, unsigned bits, bool is_float, float& out) {
    if (is_float && bits == 32) {
        float sample;
        std::memcpy(&sample, data + index * 4, sizeof(sample));
        out = sample;
        return true;
    }
    switch (bits) {
    case 16: {
        int16_t sample;
        std::memcpy(&sample, data + index * 2, sizeof(sample));
        out = static_cast<float>(sample) / 32768.0f;
        return true;
    }
    case 24: {
        const unsigned char* p = data + index * 3;
        int32_t sample = static_cast<int32_t>(p[0]) |
                         (static_cast<int32_t>(p[1]) << 8) |
                         (static_cast<int32_t>(p[2]) << 16);
        if (sample & 0x800000) sample |= ~0xFFFFFF;
        out = static_cast<float>(sample) / 8388608.0f;
        return true;
    }
    case 32: {
        int32_t sample;
        std::memcpy(&sample, data + index * 4, sizeof(sample));
        out = static_cast<float>(static_cast<double>(sample) / 2147483648.0);
        return true;
    }
    default:
        return false;
    }
}

struct Resampler {
    double step;
    double position = 0.0;
    float previous[2]{0.0f, 0.0f};
    bool have_previous = false;
    std::vector<float> samples;

    explicit Resampler(unsigned source_rate) : step(static_cast<double>(source_rate) / kOutputRate) {}

    void reset() {
        position = 0.0;
        have_previous = false;
    }

    bool convert(const unsigned char* input, size_t frames, unsigned channels, unsigned bits,
                 bool is_float, std::vector<int16_t>& output) {
        output.clear();
        output.reserve(static_cast<size_t>(std::ceil(frames / step) + 4) * 2);

        // Signed stereo PCM16 at 48 kHz can be forwarded unchanged on Windows (little-endian).
        if (step == 1.0 && !is_float && bits == 16 && channels == 2) {
            output.resize(frames * 2);
            std::memcpy(output.data(), input, frames * 4);
            return true;
        }

        if (step > 1.0) {
            return false; // Downsampling above 48000 Hz without an anti-aliasing filter is rejected.
        }

        samples.resize(frames * 2);
        for (size_t frame = 0; frame < frames; ++frame) {
            float left, right;
            if (channels == 1) {
                if (!read_sample(input, frame, bits, is_float, left)) return false;
                right = left;
            } else if (!read_sample(input, frame * channels, bits, is_float, left) ||
                       !read_sample(input, frame * channels + 1, bits, is_float, right)) {
                return false;
            }
            samples[frame * 2] = left;
            samples[frame * 2 + 1] = right;
        }

        if (step == 1.0) {
            for (float sample : samples) {
                output.push_back(to_s16(sample));
            }
            return true;
        }

        if (!frames) return true;
        const bool first_packet = !have_previous;
        if (first_packet) {
            previous[0] = samples[0];
            previous[1] = samples[1];
            have_previous = true;
        }

        // Treat previous + this packet as one continuous source sequence. Linear
        // interpolation waits for the next packet when position reaches the boundary.
        const size_t sequence_frames = first_packet ? frames : frames + 1;
        auto sample_at = [&](size_t frame, unsigned channel) {
            if (first_packet) return samples[frame * 2 + channel];
            return frame == 0 ? previous[channel] : samples[(frame - 1) * 2 + channel];
        };
        const size_t limit = sequence_frames - 1;
        while (position < static_cast<double>(limit)) {
            const size_t first = static_cast<size_t>(position);
            const double fraction = position - static_cast<double>(first);
            const size_t second = first + 1;
            for (unsigned channel = 0; channel < 2; ++channel) {
                const float a = sample_at(first, channel);
                const float b = sample_at(second, channel);
                output.push_back(to_s16(static_cast<float>(a + (b - a) * fraction)));
            }
            position += step;
        }
        position -= static_cast<double>(limit);
        previous[0] = samples[(frames - 1) * 2];
        previous[1] = samples[(frames - 1) * 2 + 1];
        return true;
    }
};

}
