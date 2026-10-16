cmake_minimum_required(VERSION 3.22)
project(router_rpc_host LANGUAGES C CXX)
enable_testing()
include(../../firmware_common/pigweed_transfer_host.cmake)
foreach(slot a b)
    add_executable(router_rpc_${slot}_test endpoint_test.cpp bridge.c
        ../../firmware_common/pw_router_rpc.cc
        ../../firmware_common/router_network.c ../../firmware_common/router_rpc_wire.c
        ../../foc2_app_${slot}/Core/Src/router.c)
    target_compile_definitions(router_rpc_${slot}_test PRIVATE
        ROUTER_READ_ONLY_NETWORK=1 ROUTER_READ_ONLY_RPC=1)
    target_include_directories(router_rpc_${slot}_test PRIVATE ../../firmware_common
        ../../foc2_app_${slot}/Core/Inc ../uart_zero_copy_host/mocks)
    target_compile_options(router_rpc_${slot}_test PRIVATE -Wall -Wextra -Werror -UNDEBUG
        -ffunction-sections -fdata-sections)
    target_link_options(router_rpc_${slot}_test PRIVATE -Wl,--gc-sections)
    target_link_libraries(router_rpc_${slot}_test PRIVATE pigweed_transfer_host)
    if(WIN32)
        target_link_libraries(router_rpc_${slot}_test PRIVATE winmm)
    endif()
    add_test(NAME router_rpc_${slot}_genuine_client_server COMMAND router_rpc_${slot}_test)
    set_tests_properties(router_rpc_${slot}_genuine_client_server PROPERTIES TIMEOUT 20)
endforeach()
add_executable(router_rpc_wire_probe ../router_network_host/wire_probe.c
    ../../firmware_common/router_network.c ../../firmware_common/router_rpc_wire.c)
target_include_directories(router_rpc_wire_probe PRIVATE ../../firmware_common)
target_compile_definitions(router_rpc_wire_probe PRIVATE ROUTER_READ_ONLY_RPC=1)
target_compile_options(router_rpc_wire_probe PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
