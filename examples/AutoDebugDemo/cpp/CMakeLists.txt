cmake_minimum_required(VERSION 3.16)
project(AutoDebugDemo CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Debug)  # keep symbols and line info for the debugger
endif()
add_executable(geometry geometry.cpp)
