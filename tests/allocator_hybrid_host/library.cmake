set(PW_BUFFER_TEST_DIR "${CMAKE_CURRENT_LIST_DIR}")
function(project_add_buffer_host target)
    find_package(Threads REQUIRED)
    set(pw "${PW_BUFFER_TEST_DIR}/../../third_party/pigweed")
    add_library(${target} STATIC
        "${PW_BUFFER_TEST_DIR}/../../firmware_common/pw_managed_buffer.cc"
        "${PW_BUFFER_TEST_DIR}/test_heap.cc"
        "${pw}/pw_allocator/allocator.cc"
        "${pw}/pw_allocator/freertos_allocator.cc")
    target_compile_features(${target} PUBLIC cxx_std_20)
    target_link_libraries(${target} PUBLIC Threads::Threads)
    target_compile_definitions(${target} PRIVATE PW_BUFFER_HOST_TEST=1)
    target_include_directories(${target} PUBLIC
        "${PW_BUFFER_TEST_DIR}/../../firmware_common" "${PW_BUFFER_TEST_DIR}/mocks")
    target_include_directories(${target} PRIVATE
        "${pw}/pw_assert/print_and_abort_assert_public_overrides"
        "${pw}/pw_assert/print_and_abort_check_public_overrides"
        "${pw}/third_party/fuchsia/repo/sdk/lib/stdcompat/include")
    foreach(module pw_allocator pw_assert pw_bytes pw_containers pw_function pw_numeric
            pw_polyfill pw_preprocessor pw_result pw_span pw_status pw_string pw_toolchain)
        target_include_directories(${target} PRIVATE "${pw}/${module}/public")
    endforeach()
endfunction()
