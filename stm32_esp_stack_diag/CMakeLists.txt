cmake_minimum_required(VERSION 3.22)
project(stm32_esp_stack_diag C ASM)

set(CMAKE_C_STANDARD 11)
set(APP_A "${CMAKE_CURRENT_LIST_DIR}/../foc2_app_a")
set(KERNEL "${APP_A}/Middlewares/FreeRTOS-Kernel")
set(HAL "${APP_A}/Drivers/STM32G4xx_HAL_Driver")

add_executable(stm32_esp_stack_diag
    src/main.c
    "${APP_A}/startup_stm32g474xx.s"
    "${APP_A}/Core/Src/system_stm32g4xx.c"
    "${APP_A}/Core/Src/router.c"
    "${APP_A}/Core/Src/esp_link.c"
    "${HAL}/Src/stm32g4xx_hal.c"
    "${HAL}/Src/stm32g4xx_hal_cortex.c"
    "${HAL}/Src/stm32g4xx_hal_gpio.c"
    "${HAL}/Src/stm32g4xx_hal_rcc.c"
    "${HAL}/Src/stm32g4xx_hal_rcc_ex.c"
    "${HAL}/Src/stm32g4xx_hal_uart.c"
    "${HAL}/Src/stm32g4xx_hal_uart_ex.c"
    "${KERNEL}/tasks.c"
    "${KERNEL}/queue.c"
    "${KERNEL}/list.c"
    "${KERNEL}/portable/GCC/ARM_CM4F/port.c"
    "${KERNEL}/portable/MemMang/heap_4.c"
)

target_include_directories(stm32_esp_stack_diag PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/config"
    "${APP_A}/Core/Inc"
    "${APP_A}/Drivers/CMSIS/Include"
    "${APP_A}/Drivers/CMSIS/Device/ST/STM32G4xx/Include"
    "${HAL}/Inc"
    "${KERNEL}/include"
    "${KERNEL}/portable/GCC/ARM_CM4F"
)
target_compile_definitions(stm32_esp_stack_diag PRIVATE USE_HAL_DRIVER STM32G474xx)
target_compile_options(stm32_esp_stack_diag PRIVATE
    -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    -Os -Wall -Wextra -ffunction-sections -fdata-sections
)
target_link_options(stm32_esp_stack_diag PRIVATE
    -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    "-T${CMAKE_CURRENT_LIST_DIR}/../stm32_esp_link_diag/STM32G474XX_RAM.ld"
    --specs=nano.specs --specs=nosys.specs
    -Wl,--gc-sections
    -Wl,--print-memory-usage
    "-Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/stm32_esp_stack_diag.map"
)
target_link_libraries(stm32_esp_stack_diag PRIVATE m c)

add_custom_command(TARGET stm32_esp_stack_diag POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:stm32_esp_stack_diag>
            "${CMAKE_CURRENT_BINARY_DIR}/stm32_esp_stack_diag.bin"
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:stm32_esp_stack_diag>
)
