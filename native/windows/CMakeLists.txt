# Project: adb-speaker
# File: CMakeLists.txt
# Description: CMake configuration for WASAPI capture helper and conversion unit tests.
#
# Copyright (c) 2026 dafagareth
# SPDX-License-Identifier: MIT
# Licensed under the MIT License (see LICENSE in repository root).
# https://opensource.org/licenses/MIT

cmake_minimum_required(VERSION 3.16)
project(adb_speaker_capture LANGUAGES CXX)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(MSVC)
  add_compile_options(/W4 /EHsc)
  set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
else()
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()
if(WIN32)
  add_executable(wasapi_capture wasapi_capture.cpp)
  target_link_libraries(wasapi_capture PRIVATE ole32 uuid)
endif()
include(CTest)
if(BUILD_TESTING)
  add_executable(test_audio_convert ../../tests/native/test_audio_convert.cpp)
  target_include_directories(test_audio_convert PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME audio_convert COMMAND test_audio_convert)
endif()
