cmake_minimum_required(VERSION 3.22)
project(can_control_v0_host LANGUAGES C)

enable_testing()
add_executable(can_control_v0_test
    contract_test.c
    ../../firmware_common/can_control_v0.c)
target_compile_features(can_control_v0_test PRIVATE c_std_11)
target_include_directories(can_control_v0_test PRIVATE ../../firmware_common)
if(MSVC)
    target_compile_options(can_control_v0_test PRIVATE /W4 /WX)
else()
    target_compile_options(can_control_v0_test PRIVATE -Wall -Wextra -Werror -pedantic)
endif()
add_test(NAME can_control_v0_test COMMAND can_control_v0_test)
