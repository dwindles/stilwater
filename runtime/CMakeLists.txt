cmake_minimum_required(VERSION 3.20)
project(stilwater_runtime LANGUAGES CXX)

if(NOT CMAKE_SIZEOF_VOID_P EQUAL 4)
  message(FATAL_ERROR "Saints Row 2 is a 32-bit game. Configure with: -A Win32")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Static CRT so nothing extra has to be installed next to the game.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
add_compile_definitions(WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
add_compile_options(/W4 /permissive- /utf-8)

# The runtime that runs inside the game process.
add_library(stilwater SHARED src/dllmain.cpp src/log.cpp)
target_link_libraries(stilwater PRIVATE psapi)

# Starts the game suspended, loads stilwater.dll into it, then resumes it.
add_executable(stilwater-loader src/loader.cpp)
