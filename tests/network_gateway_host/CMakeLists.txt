cmake_minimum_required(VERSION 3.22)
project(network_gateway_host C)
enable_testing()
add_executable(network_gateway_test contract_test.c
    ../../firmware_common/network_v1.c ../../esp32_s3_gateway/main/modbus_ro.c
    ../../esp32_s3_gateway/main/router_frame.c)
target_include_directories(network_gateway_test PRIVATE ../../firmware_common ../../esp32_s3_gateway/main)
target_compile_features(network_gateway_test PRIVATE c_std_11)
if(MSVC)
    target_compile_options(network_gateway_test PRIVATE /W4 /WX /UNDEBUG)
else()
    target_compile_options(network_gateway_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
endif()
add_test(NAME network_gateway_contract COMMAND network_gateway_test)
