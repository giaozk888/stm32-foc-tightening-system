cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# Preserve an explicitly supplied tool search path in IDF's separate
# bootloader configure step (Windows task runners may sanitize child PATH).
if(CMAKE_PROGRAM_PATH)
    string(REPLACE ";" "|" gateway_program_path "${CMAKE_PROGRAM_PATH}")
    idf_build_set_property(EXTRA_CMAKE_ARGS "-DCMAKE_PROGRAM_PATH=${gateway_program_path}" APPEND)
endif()
project(stm32_esp32_gateway)
