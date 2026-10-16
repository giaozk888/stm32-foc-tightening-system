# Deliberately keep the original START/tightening and current/speed loops.
# This profile recompiles current numeric policy; it is not a binary patch of
# the pinned October 8 artifact and must never inherit hard-OFF/short-test gates.
option(FOC_ORIGINAL_CLOSED_LOOP_UPDATED "Original START control with current numeric policy; powered acceptance pending" OFF)
if(FOC_ORIGINAL_CLOSED_LOOP_UPDATED)
    foreach(flag
        FOC_PROTECTED_CLOSED_LOOP FOC_COMPACT_CLOSED_LOOP FOC_ADC_WINDOW
        FOC_ISOLATED_CONCURRENCY FOC_ZERO_MEDIAN_COMPUTE_ONLY
        FOC_CURRENT_SPIKE_ONLY FOC_CURRENT_TREND4 FOC_FEEDBACK_SAFETY_BINDING
        FOC_CONTROL_CHAIN_RECONNECT FOC_RAW_OBSERVE_ONLY FOC_FILTERED_OBSERVE_ONLY
        FOC_ADAPTIVE_FILTER_EXPERIMENT FOC_ZERO_TOTAL_BUDGET_OFF
        FOC_RAM_HOT_PATH FOC_IRQ_COMPACT FOC_FAST_MATH FOC_PAIR_FAST_PATH
        FOC_GUARD_FAST_PATH FOC_FEEDBACK_FAST_PATH FOC_GATE_REUSE FOC_IRQ_SOURCE_TRACE
        AS5047P_DMA_IRQ_PREEMPT_ADC ZERO_RETEST_BOOT SAFETY_LOCKED_BOOT
        ADC_DMA_RAW_DIAGNOSTIC SWITCH_FEEDBACK_DIAGNOSTIC FOC_ZERO_FAILURE_TRACE
        FOC_OC_LAYERED_SELFTEST TIGHTEN_SYNTHETIC_BENCH TIGHTEN_SPEED_X2_OFFLINE
        CAN_LINK_PROBE_ONLY CAN_FD_EXPERIMENT CAN_MOTOR_CONTROL_SERVICE)
        if(${flag})
            message(FATAL_ERROR "Original updated control cannot mix with ${flag}")
        endif()
    endforeach()
    if(NOT AS5047P_SPI_DMA OR NOT ROUTER_READ_ONLY_TRANSFER OR
       NOT CAN_CONTROL_REJECT_ONLY OR NOT UART_FIRMWARE_TRANSFER OR PW_ALLOCATOR_HYBRID)
        message(FATAL_ERROR "Original updated control requires the original DMA/read-only Router/Transfer profile")
    endif()
    target_compile_definitions(stm32cubemx INTERFACE FOC_ORIGINAL_CLOSED_LOOP_UPDATED=1)
endif()
