cmake_minimum_required(VERSION 3.22)
project(stm32_esp_link_diag C ASM)

set(CMAKE_C_STANDARD 11)
set(APP_B "${CMAKE_CURRENT_LIST_DIR}/../foc2_app_b")
set(HAL "${APP_B}/Drivers/STM32G4xx_HAL_Driver")
option(DIAG_RUN_FROM_RAM "Link diagnostic into SRAM, preserving A/B Flash" ON)

if(DIAG_RUN_FROM_RAM)
    set(DIAG_LINKER "${CMAKE_CURRENT_LIST_DIR}/STM32G474XX_RAM.ld")
    set(DIAG_VECTOR_BASE 0x20000000U)
else()
    set(DIAG_LINKER "${APP_B}/STM32G474XX_FLASH.ld")
    set(DIAG_VECTOR_BASE 0x08040000U)
endif()

add_executable(stm32_esp_link_diag
    src/main.c
    "${APP_B}/startup_stm32g474xx.s"
    "${APP_B}/Core/Src/system_stm32g4xx.c"
    "${HAL}/Src/stm32g4xx_hal.c"
    "${HAL}/Src/stm32g4xx_hal_cortex.c"
    "${HAL}/Src/stm32g4xx_hal_gpio.c"
    "${HAL}/Src/stm32g4xx_hal_rcc.c"
    "${HAL}/Src/stm32g4xx_hal_rcc_ex.c"
    "${HAL}/Src/stm32g4xx_hal_uart.c"
    "${HAL}/Src/stm32g4xx_hal_uart_ex.c"
)

target_include_directories(stm32_esp_link_diag PRIVATE
    "${APP_B}/Core/Inc"
    "${APP_B}/Drivers/CMSIS/Include"
    "${APP_B}/Drivers/CMSIS/Device/ST/STM32G4xx/Include"
    "${HAL}/Inc"
)
target_compile_definitions(stm32_esp_link_diag PRIVATE
    USE_HAL_DRIVER STM32G474xx DIAG_VECTOR_BASE=${DIAG_VECTOR_BASE})
target_compile_options(stm32_esp_link_diag PRIVATE
    -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    -Os -Wall -Wextra -ffunction-sections -fdata-sections
)
target_link_options(stm32_esp_link_diag PRIVATE
    -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    "-T${DIAG_LINKER}"
    --specs=nano.specs --specs=nosys.specs
    -Wl,--gc-sections
    -Wl,--print-memory-usage
    "-Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/stm32_esp_link_diag.map"
)
target_link_libraries(stm32_esp_link_diag PRIVATE m c)

add_custom_command(TARGET stm32_esp_link_diag POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:stm32_esp_link_diag>
            "${CMAKE_CURRENT_BINARY_DIR}/stm32_esp_link_diag.bin"
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:stm32_esp_link_diag>
)
