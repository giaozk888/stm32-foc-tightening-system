cmake_minimum_required(VERSION 3.22)
project(uart_zero_copy_host LANGUAGES C CXX)
enable_testing()
find_package(Threads REQUIRED)
include(../allocator_hybrid_host/library.cmake)
project_add_buffer_host(pw_buffer_host)
add_library(uart_pure STATIC
    ../../firmware_common/uart_tx_pool.c
    ../../firmware_common/pw_log_store.c
    ../../firmware_common/uart_rx_cursor.c
    ../../firmware_common/uart_line_parser.c
    ../../firmware_common/tighten_params.cpp)
target_include_directories(uart_pure PUBLIC ../../firmware_common)
target_compile_features(uart_pure PUBLIC c_std_11 cxx_std_17)
add_executable(uart_core_test core_test.cpp)
target_compile_features(uart_core_test PRIVATE cxx_std_17)
target_link_libraries(uart_core_test PRIVATE uart_pure Threads::Threads)
add_executable(uart_adapter_test adapter_test.c
    ../../foc2_app_a/Core/Src/uart_async.c
    ../../foc2_app_a/Core/Src/uart_rx_dma.c)
target_include_directories(uart_adapter_test PRIVATE mocks ../../foc2_app_a/Core/Inc)
target_link_libraries(uart_adapter_test PRIVATE uart_pure)
foreach(target uart_pure uart_core_test uart_adapter_test)
    target_compile_options(${target} PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
endforeach()
add_test(NAME uart_lock_free_ownership_stress COMMAND uart_core_test)
add_test(NAME uart_dma_adapter_faults COMMAND uart_adapter_test)
add_executable(uart_adapter_b_test adapter_test.c
    ../../foc2_app_b/Core/Src/uart_async.c
    ../../foc2_app_b/Core/Src/uart_rx_dma.c)
target_include_directories(uart_adapter_b_test PRIVATE mocks ../../foc2_app_b/Core/Inc)
target_link_libraries(uart_adapter_b_test PRIVATE uart_pure)
target_compile_options(uart_adapter_b_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
add_test(NAME uart_dma_adapter_b_faults COMMAND uart_adapter_b_test)
set_tests_properties(uart_lock_free_ownership_stress uart_dma_adapter_faults uart_dma_adapter_b_faults
    PROPERTIES TIMEOUT 30)

# Use the actual upstream codec, not a mock encoder. RTOS/HAL remain mocks.
set(PW_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/pigweed)
add_library(pigweed_log_codec STATIC ${PW_ROOT}/pw_base64/base64.cc
    ${PW_ROOT}/pw_tokenizer/base64.cc)
target_compile_features(pigweed_log_codec PRIVATE cxx_std_20)
target_compile_options(pigweed_log_codec PRIVATE -ffunction-sections -fdata-sections)
target_include_directories(pigweed_log_codec PUBLIC
    ${PW_ROOT}/third_party/fuchsia/repo/sdk/lib/stdcompat/include
    ${PW_ROOT}/pw_assert/print_and_abort_assert_public_overrides
    ${PW_ROOT}/pw_assert/print_and_abort_check_public_overrides)
foreach(module pw_assert pw_base64 pw_bytes pw_containers pw_function pw_numeric
    pw_polyfill pw_preprocessor pw_result pw_span pw_status pw_string
    pw_tokenizer pw_toolchain)
    target_include_directories(pigweed_log_codec PUBLIC ${PW_ROOT}/${module}/public)
endforeach()

foreach(slot a b)
    set(app ../../foc2_app_${slot})
    add_executable(shared_log_${slot}_test shared_log_test.c
        ${app}/Core/Src/uart_async.c ${app}/Core/Src/uart_rx_dma.c
        ${app}/Middleware/pigweed/pw_log_backend.c
        ${app}/Middleware/pigweed/pw_log_router_bridge.c
        ../../firmware_common/pw_can_log.c ../../firmware_common/can_log_v1.c)
    target_sources(shared_log_${slot}_test PRIVATE ../../firmware_common/pw_log_snapshot.c)
    target_include_directories(shared_log_${slot}_test PRIVATE mocks ${app}/Core/Inc
        ${app}/Middleware/pigweed)
    target_link_libraries(shared_log_${slot}_test PRIVATE uart_pure pigweed_log_codec)
    target_link_options(shared_log_${slot}_test PRIVATE -Wl,--gc-sections)
    target_compile_definitions(shared_log_${slot}_test PRIVATE PW_LOG_HOST_TEST=1)
    target_compile_options(shared_log_${slot}_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
    add_test(NAME shared_log_${slot}_ownership_faults COMMAND shared_log_${slot}_test)
    set_tests_properties(shared_log_${slot}_ownership_faults PROPERTIES TIMEOUT 30)
endforeach()

foreach(slot a b)
    add_executable(router_span_${slot}_test router_span_test.c
        ../../foc2_app_${slot}/Core/Src/router.c)
    target_include_directories(router_span_${slot}_test PRIVATE mocks
        ../../foc2_app_${slot}/Core/Inc)
    target_compile_options(router_span_${slot}_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
    add_test(NAME router_span_${slot}_wire_compatibility COMMAND router_span_${slot}_test)
    set_tests_properties(router_span_${slot}_wire_compatibility PROPERTIES TIMEOUT 30)
endforeach()

add_executable(log_store_test log_store_test.cpp)
target_link_libraries(log_store_test PRIVATE uart_pure Threads::Threads)
target_compile_features(log_store_test PRIVATE cxx_std_17)
target_compile_options(log_store_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
add_test(NAME shared_log_pool_concurrent_owners COMMAND log_store_test)
set_tests_properties(shared_log_pool_concurrent_owners PROPERTIES TIMEOUT 30)

foreach(slot a b)
    set(app ../../foc2_app_${slot})
    add_executable(hybrid_uart_${slot}_test adapter_test.c
        ${app}/Core/Src/uart_async.c ${app}/Core/Src/uart_rx_dma.c router_encoder.c)
    target_include_directories(hybrid_uart_${slot}_test PRIVATE mocks ${app}/Core/Inc)
    target_compile_definitions(hybrid_uart_${slot}_test PRIVATE PW_ALLOCATOR_HYBRID=1)
    target_link_libraries(hybrid_uart_${slot}_test PRIVATE uart_pure pw_buffer_host)
    target_compile_options(hybrid_uart_${slot}_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
    target_compile_options(hybrid_uart_${slot}_test PRIVATE -ffunction-sections -fdata-sections)
    target_link_options(hybrid_uart_${slot}_test PRIVATE -Wl,--gc-sections)
    add_test(NAME hybrid_uart_${slot}_dma_ownership_faults COMMAND hybrid_uart_${slot}_test)

    add_executable(hybrid_log_${slot}_test shared_log_test.c
        ${app}/Core/Src/uart_async.c ${app}/Core/Src/uart_rx_dma.c router_encoder.c
        ${app}/Middleware/pigweed/pw_log_backend.c
        ${app}/Middleware/pigweed/pw_log_router_bridge.c
        ../../firmware_common/pw_can_log.c ../../firmware_common/can_log_v1.c
        ../../firmware_common/pw_log_snapshot.c)
    target_include_directories(hybrid_log_${slot}_test PRIVATE mocks ${app}/Core/Inc
        ${app}/Middleware/pigweed)
    target_compile_definitions(hybrid_log_${slot}_test PRIVATE PW_ALLOCATOR_HYBRID=1 PW_LOG_HOST_TEST=1)
    target_link_libraries(hybrid_log_${slot}_test PRIVATE uart_pure pigweed_log_codec pw_buffer_host)
    target_link_options(hybrid_log_${slot}_test PRIVATE -Wl,--gc-sections)
    target_compile_options(hybrid_log_${slot}_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
    target_compile_options(hybrid_log_${slot}_test PRIVATE -ffunction-sections -fdata-sections)
    add_test(NAME hybrid_log_${slot}_snapshot_faults COMMAND hybrid_log_${slot}_test)
    set_tests_properties(hybrid_uart_${slot}_dma_ownership_faults hybrid_log_${slot}_snapshot_faults
        PROPERTIES TIMEOUT 30)
endforeach()
