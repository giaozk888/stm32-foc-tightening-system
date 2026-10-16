set(PW_ROOT "${CMAKE_CURRENT_LIST_DIR}/../third_party/pigweed")
include("${CMAKE_CURRENT_LIST_DIR}/pigweed_transfer.cmake")
add_library(pigweed_transfer_host STATIC)
target_sources(pigweed_transfer_host PRIVATE "${PROJECT_TRANSFER_SOURCE_DIR}/host_log_backend.cpp")
set_property(TARGET pigweed_transfer_host PROPERTY CXX_STANDARD 20)
target_compile_features(pigweed_transfer_host PUBLIC cxx_std_20)
# GCC 10's early libstdc++ ranges/span implementation rejects Pigweed's inline
# string deduction. Use the official checked pw::span backend on this compiler;
# do not patch upstream headers or remove constant-initialization checks.
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 11)
    target_compile_definitions(pigweed_transfer_host PUBLIC PW_SPAN_ENABLE_ASSERTS=1)
endif()
foreach(source pw_status/status.cc pw_containers/intrusive_item.cc pw_varint/varint.cc
        pw_varint/stream.cc pw_protobuf/decoder.cc pw_protobuf/encoder.cc pw_protobuf/find.cc
        pw_protobuf/stream_decoder.cc pw_stream/memory_stream.cc pw_rpc/call.cc
        pw_rpc/channel.cc pw_rpc/channel_list.cc pw_rpc/endpoint.cc pw_rpc/packet.cc
        pw_rpc/packet_meta.cc pw_rpc/server.cc pw_rpc/server_call.cc pw_rpc/service.cc
        pw_rpc/raw/method.cc pw_transfer/chunk.cc pw_log/rate_limited.cc
        pw_log_string/handler.cc)
    target_sources(pigweed_transfer_host PRIVATE "${PW_ROOT}/${source}")
endforeach()
foreach(module pw_assert pw_bytes pw_containers pw_function pw_log pw_log_string
        pw_numeric pw_memory pw_polyfill pw_preprocessor pw_result pw_span pw_status
        pw_string pw_rpc pw_protobuf pw_stream pw_sync pw_toolchain pw_transfer pw_varint pw_chrono)
    target_include_directories(pigweed_transfer_host PUBLIC "${PW_ROOT}/${module}/public")
endforeach()
target_include_directories(pigweed_transfer_host PUBLIC
    "${PW_ROOT}/pw_assert/print_and_abort_assert_public_overrides"
    "${PW_ROOT}/pw_assert/print_and_abort_check_public_overrides"
    "${PW_ROOT}/pw_log_string/public_overrides" "${PW_ROOT}/pw_rpc/raw/public"
    "${PW_ROOT}/third_party/fuchsia/repo/sdk/lib/fit/include"
    "${PW_ROOT}/third_party/fuchsia/repo/sdk/lib/stdcompat/include"
    "${PROJECT_TRANSFER_SOURCE_DIR}/../foc2_app_a/Middleware/pigweed")
target_compile_definitions(pigweed_transfer_host PUBLIC PW_RPC_ENCODING_BUFFER_SIZE_BYTES=128
    PW_RPC_COMPLETION_REQUEST_CALLBACK=1)
project_add_transfer_engine(pigweed_transfer_host stl)
