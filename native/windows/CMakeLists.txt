# Copyright (c) 2026 dafagareth
# SPDX-License-Identifier: MIT

# Set C++17 and compiler warnings. On Windows, build the WASAPI helper and link
# its COM libraries; with MSVC, use the static runtime. When testing is enabled,
# build the converter test and register it with CTest on either platform.

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
