cmake_minimum_required(VERSION 3.12)
project(lubancat_hmi LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets Sql)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Widgets Sql)
include(../firmware_common/pigweed_transfer_host.cmake)

set(CAN_CONTROL_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../firmware_common"
    CACHE PATH "Shared non-actuating CAN control protocol source")
add_executable(lubancat_hmi src/main.cpp src/snapshot_store.cpp src/log_store.cpp src/log_download.cpp
    "${CAN_CONTROL_SOURCE_DIR}/can_control_v0.c" "${CAN_CONTROL_SOURCE_DIR}/can_log_v1.c")
target_sources(lubancat_hmi PRIVATE "${CAN_CONTROL_SOURCE_DIR}/can_rpc_transport.c")
target_include_directories(lubancat_hmi PRIVATE src "${CAN_CONTROL_SOURCE_DIR}")
target_compile_options(lubancat_hmi PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(lubancat_hmi PRIVATE Qt${QT_VERSION_MAJOR}::Widgets Qt${QT_VERSION_MAJOR}::Sql pigweed_transfer_host)

# The existing LubanCat MIPI application needs an explicit DRM UI plane on this
# board. Reuse its proven presenter for the on-device Qt 5 build only.
set(DRM_UI_PLANE_DIR "/home/cat/lubanmao-cpp-rknn/qt_cabin_panel/src"
    CACHE PATH "Existing LubanCat DRM UI plane source directory")
if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND QT_VERSION_MAJOR EQUAL 5 AND
   EXISTS "${DRM_UI_PLANE_DIR}/drm_ui_plane.cpp")
    set_target_properties(lubancat_hmi PROPERTIES AUTOMOC ON)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(LIBDRM REQUIRED libdrm)
    target_sources(lubancat_hmi PRIVATE
        "${DRM_UI_PLANE_DIR}/drm_ui_plane.cpp"
        "${DRM_UI_PLANE_DIR}/drm_ui_plane.h")
    target_include_directories(lubancat_hmi PRIVATE
        "${DRM_UI_PLANE_DIR}"
        ${LIBDRM_INCLUDE_DIRS}
        ${Qt5Gui_PRIVATE_INCLUDE_DIRS})
    target_link_libraries(lubancat_hmi PRIVATE ${LIBDRM_LIBRARIES})
    target_compile_definitions(lubancat_hmi PRIVATE HAS_DRM_UI_PLANE=1)
endif()

option(HMI_BUILD_TESTS "Build host-side protocol and trend tests" OFF)
if(HMI_BUILD_TESTS)
    enable_testing()
    add_executable(safety_report_v1_test tests/safety_report_v1_test.cpp)
    target_include_directories(safety_report_v1_test PRIVATE src "${CAN_CONTROL_SOURCE_DIR}")
    add_test(NAME safety_report_v1_test COMMAND safety_report_v1_test)
    add_executable(status_v1_test tests/status_v1_test.cpp)
    target_include_directories(status_v1_test PRIVATE src)
    add_test(NAME status_v1_test COMMAND status_v1_test)
    add_executable(measurement_v1_test tests/measurement_v1_test.cpp)
    target_include_directories(measurement_v1_test PRIVATE src)
    add_test(NAME measurement_v1_test COMMAND measurement_v1_test)
    add_executable(preflight_observation_test tests/preflight_observation_test.cpp)
    target_include_directories(preflight_observation_test PRIVATE src)
    add_test(NAME preflight_observation_test COMMAND preflight_observation_test)
    add_executable(control_workflow_test tests/control_workflow_test.cpp
        "${CAN_CONTROL_SOURCE_DIR}/can_control_v0.c")
    target_include_directories(control_workflow_test PRIVATE src "${CAN_CONTROL_SOURCE_DIR}")
    add_test(NAME control_workflow_test COMMAND control_workflow_test)
    add_executable(pigweed_log_test tests/pigweed_log_test.cpp)
    target_include_directories(pigweed_log_test PRIVATE src)
    add_test(NAME pigweed_log_test COMMAND pigweed_log_test)
    add_executable(can_log_v1_test tests/can_log_v1_test.cpp
        "${CAN_CONTROL_SOURCE_DIR}/can_log_v1.c")
    target_include_directories(can_log_v1_test PRIVATE src "${CAN_CONTROL_SOURCE_DIR}")
    add_test(NAME can_log_v1_test COMMAND can_log_v1_test)
    add_executable(log_store_test tests/log_store_test.cpp src/log_store.cpp)
    target_include_directories(log_store_test PRIVATE src)
    target_compile_definitions(log_store_test PRIVATE
        LOG_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/stm32-log-dump-20260930.log")
    target_link_libraries(log_store_test PRIVATE Qt${QT_VERSION_MAJOR}::Core)
    add_test(NAME log_store_test COMMAND log_store_test)
    add_executable(log_touch_ui_test tests/log_touch_ui_test.cpp src/log_store.cpp src/snapshot_store.cpp
        "${CAN_CONTROL_SOURCE_DIR}/can_control_v0.c" "${CAN_CONTROL_SOURCE_DIR}/can_log_v1.c")
    target_include_directories(log_touch_ui_test PRIVATE src "${CAN_CONTROL_SOURCE_DIR}")
    target_compile_definitions(log_touch_ui_test PRIVATE
        LEVEL_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/log-levels.log")
    target_link_libraries(log_touch_ui_test PRIVATE Qt${QT_VERSION_MAJOR}::Widgets Qt${QT_VERSION_MAJOR}::Sql)
    add_test(NAME log_touch_ui_test COMMAND log_touch_ui_test)
    add_executable(safety_ui_test tests/safety_ui_test.cpp src/log_store.cpp src/snapshot_store.cpp
        "${CAN_CONTROL_SOURCE_DIR}/can_control_v0.c" "${CAN_CONTROL_SOURCE_DIR}/can_log_v1.c")
    target_include_directories(safety_ui_test PRIVATE src "${CAN_CONTROL_SOURCE_DIR}")
    target_link_libraries(safety_ui_test PRIVATE Qt${QT_VERSION_MAJOR}::Widgets Qt${QT_VERSION_MAJOR}::Sql)
    add_test(NAME safety_ui_test COMMAND safety_ui_test)
    foreach(ui_test log_touch_ui_test safety_ui_test)
        target_sources(${ui_test} PRIVATE "${CAN_CONTROL_SOURCE_DIR}/can_rpc_transport.c")
        target_sources(${ui_test} PRIVATE src/log_download.cpp)
        target_link_libraries(${ui_test} PRIVATE pigweed_transfer_host)
    endforeach()
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
        add_executable(log_serial_reader_test tests/log_serial_reader_test.cpp src/log_store.cpp)
        target_include_directories(log_serial_reader_test PRIVATE src)
        target_link_libraries(log_serial_reader_test PRIVATE Qt${QT_VERSION_MAJOR}::Core)
        add_test(NAME log_serial_reader_test COMMAND log_serial_reader_test)
    endif()
    add_executable(telemetry_history_test tests/telemetry_history_test.cpp)
    target_include_directories(telemetry_history_test PRIVATE src)
    add_test(NAME telemetry_history_test COMMAND telemetry_history_test)
    add_executable(snapshot_store_test tests/snapshot_store_test.cpp src/snapshot_store.cpp)
    target_include_directories(snapshot_store_test PRIVATE src)
    target_link_libraries(snapshot_store_test PRIVATE Qt${QT_VERSION_MAJOR}::Sql)
    add_test(NAME snapshot_store_test COMMAND snapshot_store_test)
    if(WIN32 AND CMAKE_VERSION VERSION_GREATER_EQUAL 3.22)
        set_tests_properties(snapshot_store_test log_store_test log_touch_ui_test safety_ui_test PROPERTIES ENVIRONMENT_MODIFICATION
            "PATH=path_list_prepend:$<TARGET_FILE_DIR:Qt${QT_VERSION_MAJOR}::Core>")
    endif()
endif()

install(TARGETS lubancat_hmi RUNTIME DESTINATION bin)

# The acceptance client uses the same query/official Transfer implementation as
# the UI, without opening EGLFS or exposing a generic CAN transmit interface.
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    add_executable(can_fd_business_probe ../tools/can_fd_business_probe.cpp
        src/log_download.cpp "${CAN_CONTROL_SOURCE_DIR}/can_rpc_transport.c"
        "${CAN_CONTROL_SOURCE_DIR}/can_log_v1.c")
    target_include_directories(can_fd_business_probe PRIVATE src "${CAN_CONTROL_SOURCE_DIR}")
    target_compile_options(can_fd_business_probe PRIVATE -Wall -Wextra -Wpedantic)
    target_link_libraries(can_fd_business_probe PRIVATE pigweed_transfer_host)
endif()
