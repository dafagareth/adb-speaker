/*
 * Project: adb-speaker
 * File: wasapi_capture.cpp
 * Description: Minimal WASAPI loopback capture helper emitting stereo PCM (48kHz/16-bit).
 *
 * Copyright (c) 2026 dafagareth
 * SPDX-License-Identifier: MIT
 * Licensed under the MIT License (see LICENSE in repository root).
 * https://opensource.org/licenses/MIT
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <audioclient.h>
#include <mmdeviceapi.h>
#include <ksmedia.h>
#include <wrl/client.h>
#include <atomic>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include <io.h>
#include <fcntl.h>

#include "audio_convert.hpp"
using adb_audio::Resampler;
using Microsoft::WRL::ComPtr;

namespace {
std::atomic_bool g_running{true};

BOOL WINAPI on_console_control(DWORD event) {
    if (event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT || event == CTRL_CLOSE_EVENT) {
        g_running.store(false);
        return TRUE;
    }
    return FALSE;
}

void report_hr(const char* action, HRESULT hr) {
    std::fprintf(stderr, "wasapi-capture: %s failed (0x%08lX)\n", action,
                 static_cast<unsigned long>(hr));
}

bool has_format(const WAVEFORMATEX* format, WORD tag, const GUID& sub) {
    if (format->wFormatTag == tag) return true;
    if (format->wFormatTag == WAVE_FORMAT_EXTENSIBLE &&
        format->cbSize >= sizeof(WAVEFORMATEXTENSIBLE) - sizeof(WAVEFORMATEX)) {
        return IsEqualGUID(reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(format)->SubFormat, sub);
    }
    return false;
}
} // namespace

int wmain() {
    _setmode(_fileno(stdout), _O_BINARY);
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    SetConsoleCtrlHandler(on_console_control, TRUE);

    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) { report_hr("COM initialization", hr); return 1; }

    ComPtr<IMMDeviceEnumerator> enumerator;
    ComPtr<IMMDevice> device;
    ComPtr<IAudioClient> audio_client;
    ComPtr<IAudioCaptureClient> capture;
    WAVEFORMATEX* format = nullptr;
    HANDLE event_handle = nullptr;
    bool started = false;
    int result = 1;

    do {
        hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                              IID_PPV_ARGS(&enumerator));
        if (FAILED(hr)) { report_hr("create device enumerator", hr); break; }
        hr = enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &device);
        if (FAILED(hr)) { report_hr("get default render endpoint", hr); break; }
        hr = device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
                              reinterpret_cast<void**>(audio_client.GetAddressOf()));
        if (FAILED(hr)) { report_hr("activate audio client", hr); break; }
        hr = audio_client->GetMixFormat(&format);
        if (FAILED(hr)) { report_hr("get mix format", hr); break; }

        const bool float_format = has_format(format, WAVE_FORMAT_IEEE_FLOAT, KSDATAFORMAT_SUBTYPE_IEEE_FLOAT);
        const bool pcm_format = has_format(format, WAVE_FORMAT_PCM, KSDATAFORMAT_SUBTYPE_PCM);
        if ((!float_format && !pcm_format) || (format->wBitsPerSample != 16 &&
             format->wBitsPerSample != 24 && format->wBitsPerSample != 32) ||
             format->nChannels < 1 || format->nChannels > 2 || format->nBlockAlign == 0 ||
             format->nSamplesPerSec == 0 || format->nSamplesPerSec > adb_audio::kOutputRate ||
             (float_format && format->wBitsPerSample != 32)) {
            std::fprintf(stderr, "wasapi-capture: unsupported mix format (%u Hz, %u channels, %u bits).\n"
                         "Rates above 48000 Hz are unsupported. In Windows Sound Settings, set format to 48000 Hz.\n",
                         format->nSamplesPerSec, format->nChannels, format->wBitsPerSample);
            break;
        }

        event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event_handle) { std::fprintf(stderr, "wasapi-capture: CreateEvent failed\n"); break; }
        hr = audio_client->Initialize(AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
            0, 0, format, nullptr);
        if (FAILED(hr)) { report_hr("initialize loopback", hr); break; }
        hr = audio_client->SetEventHandle(event_handle);
        if (FAILED(hr)) { report_hr("set capture event", hr); break; }
        hr = audio_client->GetService(IID_PPV_ARGS(&capture));
        if (FAILED(hr)) { report_hr("get capture service", hr); break; }
        hr = audio_client->Start();
        if (FAILED(hr)) { report_hr("start loopback", hr); break; }
        started = true;

        std::fprintf(stderr, "WASAPI ready: source=%u Hz/%u ch/%u bit, output=48000 Hz/2 ch/16 bit\n",
                     format->nSamplesPerSec, format->nChannels, format->wBitsPerSample);
        Resampler resampler(format->nSamplesPerSec);
        std::vector<int16_t> converted;
        std::vector<BYTE> zero_input;
        result = 0;
        while (g_running.load()) {
            const DWORD wait_result = WaitForSingleObject(event_handle, 1000);
            if (wait_result == WAIT_TIMEOUT) continue;
            if (wait_result != WAIT_OBJECT_0) {
                std::fprintf(stderr, "wasapi-capture: capture event wait failed\n");
                result = 1;
                break;
            }
            UINT32 packet_frames = 0;
            hr = capture->GetNextPacketSize(&packet_frames);
            if (FAILED(hr)) { report_hr("get next packet size", hr); result = 1; break; }
            while (packet_frames > 0 && g_running.load()) {
                BYTE* data = nullptr;
                UINT32 frames = 0;
                DWORD flags = 0;
                hr = capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
                if (FAILED(hr)) { report_hr("get capture buffer", hr); result = 1; break; }
                if (flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY) {
                    // Never interpolate between samples on opposite sides of a capture gap.
                    resampler.reset();
                }
                const BYTE* source = data;
                if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                    // Preserve resampler timing while emitting silence.
                    zero_input.resize(static_cast<size_t>(frames) * format->nBlockAlign);
                    std::fill(zero_input.begin(), zero_input.end(), BYTE{0});
                    source = zero_input.data();
                }
                bool ok = resampler.convert(source, frames, format->nChannels,
                                            format->wBitsPerSample, float_format, converted);
                if (ok && !converted.empty()) {
                    ok = std::fwrite(converted.data(), sizeof(int16_t) * 2,
                                     converted.size() / 2, stdout) == converted.size() / 2;
                }
                hr = capture->ReleaseBuffer(frames);
                if (FAILED(hr)) { report_hr("release capture buffer", hr); result = 1; break; }
                if (!ok) {
                    std::fprintf(stderr, "wasapi-capture: writing PCM output failed\n");
                    result = 1;
                    break;
                }
                hr = capture->GetNextPacketSize(&packet_frames);
                if (FAILED(hr)) { report_hr("get next packet size", hr); result = 1; break; }
            }
            if (result != 0) break;
        }
    } while (false);

    if (started) audio_client->Stop();
    if (format) CoTaskMemFree(format);
    if (event_handle) CloseHandle(event_handle);
    CoUninitialize();
    return result;
}
