cmake_minimum_required(VERSION 3.22)
project(stm32_can_link_diag C ASM)

option(CAN_RX_ONLY "Build bounded receive-only CAN diagnostic" OFF)
option(CAN_STATUS_V1_PROBE "Build bounded SRAM-only 0x180 status-format diagnostic" OFF)
if(CAN_RX_ONLY AND CAN_STATUS_V1_PROBE)
    message(FATAL_ERROR "CAN_RX_ONLY and CAN_STATUS_V1_PROBE are mutually exclusive")
endif()

set(CMAKE_C_STANDARD 11)
set(APP "${CMAKE_CURRENT_LIST_DIR}/../foc2_app_b")
set(HAL "${APP}/Drivers/STM32G4xx_HAL_Driver")
set(RAM_LINKER "${CMAKE_CURRENT_LIST_DIR}/../stm32_esp_link_diag/STM32G474XX_RAM.ld")

add_executable(stm32_can_link_diag
    src/main.c
    "${APP}/startup_stm32g474xx.s"
    "${APP}/Core/Src/system_stm32g4xx.c"
    "${HAL}/Src/stm32g4xx_hal.c"
    "${HAL}/Src/stm32g4xx_hal_cortex.c"
    "${HAL}/Src/stm32g4xx_hal_gpio.c"
    "${HAL}/Src/stm32g4xx_hal_rcc.c"
    "${HAL}/Src/stm32g4xx_hal_rcc_ex.c"
    "${HAL}/Src/stm32g4xx_hal_uart.c"
    "${HAL}/Src/stm32g4xx_hal_uart_ex.c"
    "${HAL}/Src/stm32g4xx_hal_fdcan.c"
)

target_include_directories(stm32_can_link_diag PRIVATE
    "${APP}/Core/Inc"
    "${APP}/Drivers/CMSIS/Include"
    "${APP}/Drivers/CMSIS/Device/ST/STM32G4xx/Include"
    "${HAL}/Inc"
)
target_compile_definitions(stm32_can_link_diag PRIVATE
    USE_HAL_DRIVER STM32G474xx CAN_LINK_PROBE_ONLY
    DIAG_VECTOR_BASE=0x20000000U)
if(CAN_RX_ONLY)
    target_compile_definitions(stm32_can_link_diag PRIVATE CAN_RX_ONLY=1)
endif()
if(CAN_STATUS_V1_PROBE)
    target_compile_definitions(stm32_can_link_diag PRIVATE CAN_STATUS_V1_PROBE=1)
endif()
target_compile_options(stm32_can_link_diag PRIVATE
    -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    -Os -Wall -Wextra -ffunction-sections -fdata-sections
)
target_link_options(stm32_can_link_diag PRIVATE
    -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    "-T${RAM_LINKER}"
    --specs=nano.specs --specs=nosys.specs
    -Wl,--gc-sections
    -Wl,--print-memory-usage
    "-Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/stm32_can_link_diag.map"
)
target_link_libraries(stm32_can_link_diag PRIVATE m c)

add_custom_command(TARGET stm32_can_link_diag POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:stm32_can_link_diag>
            "${CMAKE_CURRENT_BINARY_DIR}/stm32_can_link_diag.bin"
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:stm32_can_link_diag>
)
