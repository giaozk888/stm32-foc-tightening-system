cmake_minimum_required(VERSION 3.22)
project(can_shadow_diag_host LANGUAGES C)

enable_testing()
add_executable(can_shadow_diag_test
    contract_test.c
    ../../firmware_common/can_shadow_diag.c)
target_compile_features(can_shadow_diag_test PRIVATE c_std_11)
target_include_directories(can_shadow_diag_test PRIVATE ../../firmware_common)
if(MSVC)
    target_compile_options(can_shadow_diag_test PRIVATE /W4 /WX)
else()
    target_compile_options(can_shadow_diag_test PRIVATE -Wall -Wextra -Werror -pedantic)
endif()
add_test(NAME can_shadow_diag_test COMMAND can_shadow_diag_test)
