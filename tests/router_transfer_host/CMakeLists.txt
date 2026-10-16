cmake_minimum_required(VERSION 3.22)
project(router_transfer_host LANGUAGES C CXX)
enable_testing()
set(CMAKE_C_STANDARD 11)
include(../../firmware_common/pigweed_transfer_host.cmake)
include(../allocator_hybrid_host/library.cmake)
project_add_buffer_host(pw_buffer_host)
add_executable(transfer_wire_test wire_test.c ../../firmware_common/router_transfer_wire.c)
target_include_directories(transfer_wire_test PRIVATE ../../firmware_common)
target_compile_options(transfer_wire_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
add_test(NAME binary_fragment_faults COMMAND transfer_wire_test)
add_executable(router_transfer_client ../../router_network/native/client_stdio.cc
    ../../router_network/native/transfer_client.cc ../../firmware_common/router_transfer_wire.c
    ../../firmware_common/router_network.c)
target_compile_definitions(router_transfer_client PRIVATE ROUTER_READ_ONLY_NETWORK=1
    ROUTER_READ_ONLY_TRANSFER=1)
target_include_directories(router_transfer_client PRIVATE ../../router_network/native
    ../../firmware_common ../../foc2_app_a/Core/Inc)
target_link_libraries(router_transfer_client PRIVATE pigweed_transfer_host)
target_compile_options(router_transfer_client PRIVATE -Wall -Wextra -Werror -UNDEBUG)
if(WIN32)
    # A CLI launched from normal Python must not require a MinGW DLL PATH.
    target_link_options(router_transfer_client PRIVATE -static)
endif()
foreach(slot a b)
    add_executable(router_transfer_${slot}_test endpoint_test.cpp logger.c ../router_rpc_host/bridge.c
        ../../router_network/native/transfer_client.cc
        ../../firmware_common/pw_router_transfer.cc ../../firmware_common/pw_log_store.c
        ../../firmware_common/pw_log_snapshot.c
        ../../firmware_common/router_transfer_wire.c ../../firmware_common/router_rpc_wire.c
        ../../firmware_common/router_network.c ../../foc2_app_${slot}/Core/Src/router.c)
    target_include_directories(router_transfer_${slot}_test PRIVATE ../../firmware_common
        ../../router_network/native ../../foc2_app_${slot}/Core/Inc ../uart_zero_copy_host/mocks
        ../../foc2_app_${slot}/Middleware/pigweed)
    target_compile_definitions(router_transfer_${slot}_test PRIVATE ROUTER_READ_ONLY_NETWORK=1
        ROUTER_READ_ONLY_RPC=1 ROUTER_READ_ONLY_TRANSFER=1 PW_TRANSFER_HOST=1 AS5047P_SPI_DMA=1)
    target_compile_definitions(router_transfer_${slot}_test PRIVATE PW_ALLOCATOR_HYBRID=1)
    target_compile_options(router_transfer_${slot}_test PRIVATE -Wall -Wextra -Werror -UNDEBUG
        -ffunction-sections -fdata-sections)
    target_link_options(router_transfer_${slot}_test PRIVATE -Wl,--gc-sections)
    target_link_libraries(router_transfer_${slot}_test PRIVATE pigweed_transfer_host pw_buffer_host)
    add_test(NAME router_transfer_${slot}_official_roundtrip COMMAND router_transfer_${slot}_test)
    set_tests_properties(router_transfer_${slot}_official_roundtrip PROPERTIES TIMEOUT 60)
endforeach()
