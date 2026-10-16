cmake_minimum_required(VERSION 3.22)
project(can_rpc_host LANGUAGES C CXX)
enable_testing()
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 20)
set(PW_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/pigweed)
add_library(can_rpc_transport STATIC ../../firmware_common/can_rpc_transport.c)
target_include_directories(can_rpc_transport PUBLIC ../../firmware_common ../../lubancat_hmi/src)
target_compile_options(can_rpc_transport PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
add_executable(transport_test transport_test.cpp)
target_link_libraries(transport_test PRIVATE can_rpc_transport)
target_compile_options(transport_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
add_test(NAME can_rpc_transport_faults COMMAND transport_test)
set_tests_properties(can_rpc_transport_faults PROPERTIES TIMEOUT 30)

add_library(pigweed_rpc STATIC)
foreach(file pw_status/status.cc pw_containers/intrusive_item.cc pw_varint/varint.cc
    pw_varint/stream.cc pw_protobuf/decoder.cc pw_protobuf/encoder.cc pw_protobuf/find.cc
    pw_stream/memory_stream.cc pw_rpc/call.cc pw_rpc/channel.cc pw_rpc/channel_list.cc
    pw_rpc/endpoint.cc pw_rpc/packet.cc pw_rpc/packet_meta.cc pw_rpc/server.cc
    pw_rpc/server_call.cc pw_rpc/service.cc pw_rpc/raw/method.cc pw_transfer/chunk.cc
    pw_log_string/handler.cc pw_log/rate_limited.cc pw_protobuf/stream_decoder.cc
    pw_chrono/system_clock.cc)
    target_sources(pigweed_rpc PRIVATE ${PW_ROOT}/${file})
endforeach()

foreach(slot a b)
    add_executable(motor_rpc_${slot}_test motor_rpc_test.cpp bridge_mocks.c
        ../../firmware_common/motor_control.c ../../firmware_common/pw_can_rpc.c
        ../../firmware_common/pw_log_store.c ../../firmware_common/pw_log_snapshot.c
        ../../foc2_app_${slot}/Middleware/pigweed/pw_rpc_service.cc)
    target_include_directories(motor_rpc_${slot}_test PRIVATE ../uart_zero_copy_host/mocks
        ../../foc2_app_${slot}/Middleware/pigweed)
    target_compile_definitions(motor_rpc_${slot}_test PRIVATE CAN_RPC_READ_ONLY=1
        CAN_MOTOR_CONTROL_SERVICE=1 PW_TRANSFER_HOST=1 PW_ALLOCATOR_HYBRID=1)
    target_compile_options(motor_rpc_${slot}_test PRIVATE -Wall -Wextra -Werror -UNDEBUG
        -ffunction-sections -fdata-sections)
    target_link_options(motor_rpc_${slot}_test PRIVATE -Wl,--gc-sections)
    target_link_libraries(motor_rpc_${slot}_test PRIVATE can_rpc_transport pigweed_rpc pw_buffer_host)
    add_test(NAME motor_rpc_${slot}_official_server_and_client COMMAND motor_rpc_${slot}_test)
    set_tests_properties(motor_rpc_${slot}_official_server_and_client PROPERTIES TIMEOUT 30)
endforeach()
target_compile_definitions(pigweed_rpc PUBLIC
    PW_RPC_ENCODING_BUFFER_SIZE_BYTES=128 PW_RPC_COMPLETION_REQUEST_CALLBACK=1)
target_compile_options(pigweed_rpc PRIVATE -ffunction-sections -fdata-sections)
target_include_directories(pigweed_rpc PUBLIC
    ${PW_ROOT}/pw_assert/print_and_abort_assert_public_overrides
    ${PW_ROOT}/pw_assert/print_and_abort_check_public_overrides
    ${PW_ROOT}/pw_log_string/public_overrides
    ${PW_ROOT}/pw_chrono_stl/public
    ${PW_ROOT}/pw_chrono_stl/clock_public_overrides
    ${PW_ROOT}/pw_rpc/raw/public
    ${PW_ROOT}/third_party/fuchsia/repo/sdk/lib/fit/include
    ${PW_ROOT}/third_party/fuchsia/repo/sdk/lib/stdcompat/include)
foreach(module pw_assert pw_bytes pw_containers pw_function pw_log pw_log_string
    pw_numeric pw_memory pw_polyfill pw_preprocessor pw_result pw_span pw_status pw_string
    pw_rpc pw_protobuf pw_stream pw_sync pw_toolchain pw_transfer pw_varint pw_chrono)
    target_include_directories(pigweed_rpc PUBLIC ${PW_ROOT}/${module}/public)
endforeach()
target_include_directories(pigweed_rpc PUBLIC ../../foc2_app_a/Middleware/pigweed)
include(../../firmware_common/pigweed_transfer.cmake)
project_add_transfer_engine(pigweed_rpc stl)
include(../allocator_hybrid_host/library.cmake)
project_add_buffer_host(pw_buffer_host)
foreach(slot a b)
    add_executable(rpc_${slot}_test official_transfer_test.cpp bridge_mocks.c ../../lubancat_hmi/src/log_download.cpp
        ../../firmware_common/pw_can_rpc.c
        ../../firmware_common/pw_log_store.c
        ../../firmware_common/pw_log_snapshot.c
        ../../foc2_app_${slot}/Middleware/pigweed/pw_rpc_service.cc)
    target_include_directories(rpc_${slot}_test PRIVATE ../uart_zero_copy_host/mocks
        ../../foc2_app_${slot}/Middleware/pigweed)
    target_compile_definitions(rpc_${slot}_test PRIVATE CAN_RPC_READ_ONLY=1 PW_TRANSFER_HOST=1
        PW_ALLOCATOR_HYBRID=1
        PW_TRANSFER_TEST_TIMEOUT_MS=2000)
    target_compile_options(rpc_${slot}_test PRIVATE -Wall -Wextra -Werror -UNDEBUG
        -ffunction-sections -fdata-sections)
    target_link_options(rpc_${slot}_test PRIVATE -Wl,--gc-sections)
    target_link_libraries(rpc_${slot}_test PRIVATE can_rpc_transport pigweed_rpc pw_buffer_host)
    if(WIN32)
        target_link_libraries(rpc_${slot}_test PRIVATE winmm)
    endif()
    add_test(NAME can_rpc_${slot}_real_server_roundtrip COMMAND rpc_${slot}_test)
    set_tests_properties(can_rpc_${slot}_real_server_roundtrip PROPERTIES TIMEOUT 120)
endforeach()
