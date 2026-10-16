/*
 * Project: adb-speaker
 * File: test_audio_convert.cpp
 * Description: Unit tests for sample conversion, clipping, NaN handling, and resampling.
 *
 * Copyright (c) 2026 dafagareth
 * SPDX-License-Identifier: MIT
 * Licensed under the MIT License (see LICENSE in repository root).
 * https://opensource.org/licenses/MIT
 */
#include "../../native/windows/audio_convert.hpp"
#include <cstdlib>
#include <iostream>
#include <limits>
using namespace adb_audio;
void check(bool ok, const char* message) {
    if (!ok) { std::cerr << message << '\n'; std::exit(1); }
}
int main() {
    check(to_s16(2) == 32767 && to_s16(-2) == -32768, "clipping");
    check(to_s16(std::numeric_limits<float>::quiet_NaN()) == 0, "NaN");
    const int16_t pcm[] = {-32768, 32767, -123, 123};
    std::vector<int16_t> out;
    Resampler native(48000);
    check(native.convert(reinterpret_cast<const unsigned char*>(pcm), 2, 2, 16, false, out), "PCM16");
    check(out == std::vector<int16_t>(pcm, pcm + 4), "PCM16 exact passthrough");
    const float mono[] = {-1, 0, 1};
    check(native.convert(reinterpret_cast<const unsigned char*>(mono), 3, 1, 32, true, out), "mono");
    check(out == std::vector<int16_t>({-32768,-32768,0,0,32767,32767}), "mono duplication");
    float value;
    const unsigned char negative24[] = {0, 0, 128};
    check(read_sample(negative24, 0, 24, false, value) && value == -1, "PCM24 sign");
    check(!read_sample(negative24, 0, 8, false, value), "unsupported depth");
    std::vector<float> signal(441 * 2, .25f);
    Resampler resampler(44100);
    check(resampler.convert(reinterpret_cast<const unsigned char*>(signal.data()), 441, 2, 32, true, out), "resampling");
    check(out.size() >= 958 && out.size() <= 962, "resampling duration");
    auto first = out;
    resampler.reset();
    resampler.convert(reinterpret_cast<const unsigned char*>(signal.data()), 441, 2, 32, true, out);
    check(out == first, "discontinuity resets history");

    resampler.reset();
    std::vector<float> silence(441 * 2, 0.0f);
    check(resampler.convert(reinterpret_cast<const unsigned char*>(silence.data()), 441, 2, 32, true, out), "silence after reset");
    check(std::all_of(out.begin(), out.end(), [](int16_t s) { return s == 0; }), "silence after reset outputs all zeros");
    check(resampler.convert(reinterpret_cast<const unsigned char*>(silence.data()), 441, 2, 32, true, out), "consecutive silence");
    check(std::all_of(out.begin(), out.end(), [](int16_t s) { return s == 0; }), "consecutive silence outputs all zeros");

    Resampler high_rate(96000);
    check(!high_rate.convert(reinterpret_cast<const unsigned char*>(signal.data()), 441, 2, 32, true, out), "reject rate > 48kHz");

    std::vector<float> chirp(882 * 2);
    for (size_t i = 0; i < 882; ++i) {
        float sample = std::sin(static_cast<float>(i) * 0.1f) * 0.8f;
        chirp[i * 2] = sample;
        chirp[i * 2 + 1] = -sample;
    }
    std::vector<int16_t> whole_out;
    Resampler whole_resampler(44100);
    check(whole_resampler.convert(reinterpret_cast<const unsigned char*>(chirp.data()), 882, 2, 32, true, whole_out), "whole convert");

    for (size_t chunk_size : {7, 31, 64, 128}) {
        Resampler chunk_resampler(44100);
        std::vector<int16_t> chunked_out;
        for (size_t offset = 0; offset < 882; offset += chunk_size) {
            size_t count = std::min(chunk_size, 882 - offset);
            std::vector<int16_t> chunk_part;
            check(chunk_resampler.convert(reinterpret_cast<const unsigned char*>(chirp.data() + offset * 2),
                                          count, 2, 32, true, chunk_part), "chunk convert");
            chunked_out.insert(chunked_out.end(), chunk_part.begin(), chunk_part.end());
        }
        check(chunked_out == whole_out, "chunked conversion matches whole-buffer conversion");
    }
}
