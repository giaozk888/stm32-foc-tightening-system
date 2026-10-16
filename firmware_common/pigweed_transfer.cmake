# Build the pinned upstream engine, not a project replacement state machine.
# The caller already provides Chunk, protobuf, stream and RPC server sources.
set(PROJECT_TRANSFER_SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}")
function(project_add_transfer_engine target backend)
    foreach(source pw_transfer/transfer.cc pw_transfer/client.cc
            pw_transfer/client_context.cc pw_transfer/context.cc
            pw_transfer/server_context.cc pw_transfer/transfer_thread.cc
            pw_transfer/rate_estimate.cc pw_rpc/client.cc pw_rpc/client_call.cc
            pw_sync/mutex.cc pw_sync/binary_semaphore.cc pw_chrono/system_clock.cc
            pw_log/rate_limited.cc pw_thread/sleep.cc)
        target_sources(${target} PRIVATE "${PW_ROOT}/${source}")
    endforeach()
    target_include_directories(${target} BEFORE PUBLIC
        "${PROJECT_TRANSFER_SOURCE_DIR}/generated"
        "${PW_ROOT}/pw_thread/public" "${PW_ROOT}/pw_sync/public_overrides")
    target_compile_definitions(${target} PUBLIC PW_RPC_USE_GLOBAL_MUTEX=1
        PW_TRANSFER_CONFIG_LOG_LEVEL=3 PW_TRANSFER_DEFAULT_MAX_CLIENT_RETRIES=3
        PW_TRANSFER_DEFAULT_MAX_LIFETIME_RETRIES=12)
    if(backend STREQUAL "freertos")
        target_sources(${target} PRIVATE "${PW_ROOT}/pw_sync_freertos/binary_semaphore.cc"
            "${PW_ROOT}/pw_chrono_freertos/system_clock.cc" "${PW_ROOT}/pw_sync/interrupt_spin_lock.cc"
            "${PW_ROOT}/pw_thread_freertos/sleep.cc")
        target_include_directories(${target} PUBLIC "${PW_ROOT}/pw_sync_freertos/public"
            "${PW_ROOT}/pw_sync_freertos/public_overrides/mutex"
            "${PW_ROOT}/pw_sync_freertos/public_overrides/binary_semaphore"
            "${PW_ROOT}/pw_sync_freertos/public_overrides/interrupt_spin_lock"
            "${PW_ROOT}/pw_thread_freertos/sleep_public_overrides")
    else()
        find_package(Threads REQUIRED)
        target_sources(${target} PRIVATE "${PW_ROOT}/pw_sync_stl/binary_semaphore.cc"
            "${PW_ROOT}/pw_sync_stl/mutex.cc")
        target_include_directories(${target} PUBLIC "${PW_ROOT}/pw_sync_stl/public"
            "${PW_ROOT}/pw_sync_stl/public_overrides"
            "${PW_ROOT}/pw_chrono_stl/public" "${PW_ROOT}/pw_chrono_stl/clock_public_overrides"
            "${PW_ROOT}/pw_thread_stl/public" "${PW_ROOT}/pw_thread_stl/id_public_overrides"
            "${PW_ROOT}/pw_thread_stl/sleep_public_overrides")
        target_link_libraries(${target} PUBLIC Threads::Threads)
    endif()
endfunction()
