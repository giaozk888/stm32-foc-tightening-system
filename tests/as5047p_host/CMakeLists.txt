cmake_minimum_required(VERSION 3.22)
project(as5047p_host_tests LANGUAGES C)

enable_testing()

foreach(slot IN ITEMS a b)
    add_executable(as5047p_dma_test_${slot} dma_engine_test.c
        ../../firmware_common/as5047p_dma_engine.c)
    target_compile_features(as5047p_dma_test_${slot} PRIVATE c_std_11)
    target_include_directories(as5047p_dma_test_${slot} PRIVATE
        ../../firmware_common "../../foc2_app_${slot}/Core/Inc")
    if(NOT MSVC)
        target_compile_options(as5047p_dma_test_${slot} PRIVATE -Wall -Wextra -Werror)
        target_link_libraries(as5047p_dma_test_${slot} PRIVATE m)
    endif()
    add_test(NAME as5047p_dma_${slot} COMMAND as5047p_dma_test_${slot})
    add_executable(as5047p_test_${slot} protocol_test.c)
    target_compile_features(as5047p_test_${slot} PRIVATE c_std_11)
    target_include_directories(as5047p_test_${slot} PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/../../foc2_app_${slot}/Core/Inc")
    if(NOT MSVC)
        target_link_libraries(as5047p_test_${slot} PRIVATE m)
    endif()
    add_test(NAME as5047p_${slot} COMMAND as5047p_test_${slot})

    add_executable(as5047p_transaction_test_${slot} transaction_test.c)
    target_compile_features(as5047p_transaction_test_${slot} PRIVATE c_std_11)
    target_include_directories(as5047p_transaction_test_${slot} PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/../../foc2_app_${slot}/Core/Inc")
    if(NOT MSVC)
        target_link_libraries(as5047p_transaction_test_${slot} PRIVATE m)
    endif()
    add_test(NAME as5047p_transaction_${slot}
             COMMAND as5047p_transaction_test_${slot})
endforeach()
