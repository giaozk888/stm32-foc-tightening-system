cmake_minimum_required(VERSION 3.22)
project(tighten_params_host LANGUAGES C CXX)
enable_testing()
add_executable(tighten_params_test recipe_test.cpp c_abi_contract.c
    ../../firmware_common/tighten_params.cpp
    ../../firmware_common/tighten_params_storage.cpp)
target_include_directories(tighten_params_test PRIVATE ../../firmware_common)
target_compile_features(tighten_params_test PRIVATE c_std_11 cxx_std_17)
if(MSVC)
    target_compile_options(tighten_params_test PRIVATE /W4 /WX /UNDEBUG)
else()
    target_compile_options(tighten_params_test PRIVATE -Wall -Wextra -Werror -pedantic -UNDEBUG)
    target_compile_options(tighten_params_test PRIVATE
        $<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions;-fno-rtti;-fno-threadsafe-statics>)
endif()
add_test(NAME tighten_params_compatibility COMMAND tighten_params_test)

add_executable(tighten_storage_test storage_test.cpp
    ../../firmware_common/tighten_params.cpp
    ../../firmware_common/tighten_params_storage.cpp)
target_include_directories(tighten_storage_test PRIVATE ../../firmware_common)
target_compile_features(tighten_storage_test PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(tighten_storage_test PRIVATE /W4 /WX /UNDEBUG)
else()
    target_compile_options(tighten_storage_test PRIVATE -Wall -Wextra -Werror
        -pedantic -UNDEBUG -fno-exceptions -fno-rtti -fno-threadsafe-statics)
endif()
add_test(NAME tighten_storage_compatibility COMMAND tighten_storage_test)

add_executable(tighten_speed_x2_test speed_x2_test.cpp
    ../../firmware_common/tighten_params.cpp
    ../../firmware_common/tighten_params_storage.cpp)
target_include_directories(tighten_speed_x2_test PRIVATE ../../firmware_common)
target_compile_definitions(tighten_speed_x2_test PRIVATE TIGHTEN_SPEED_X2_OFFLINE=1)
target_compile_features(tighten_speed_x2_test PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(tighten_speed_x2_test PRIVATE /W4 /WX /UNDEBUG)
else()
    target_compile_options(tighten_speed_x2_test PRIVATE -Wall -Wextra -Werror
        -pedantic -UNDEBUG -fno-exceptions -fno-rtti -fno-threadsafe-statics)
endif()
add_test(NAME tighten_double_speed_offline COMMAND tighten_speed_x2_test)
