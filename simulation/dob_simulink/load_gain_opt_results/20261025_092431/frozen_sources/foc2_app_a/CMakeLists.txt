cmake_minimum_required(VERSION 3.22)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

set(CMAKE_PROJECT_NAME foc2)
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)
project(${CMAKE_PROJECT_NAME} LANGUAGES C CXX ASM)
message("Build type: " ${CMAKE_BUILD_TYPE})

# Keep the deployed baud unchanged; 2M is an opt-in, unverified hardware profile.
set(UART_LOG_BAUD "115200" CACHE STRING "LPUART1 baud; 2000000 needs hardware validation")
if(NOT UART_LOG_BAUD MATCHES "^(115200|2000000)$")
    message(FATAL_ERROR "UART_LOG_BAUD must be 115200 or 2000000")
endif()

# Isolated, transmit-only CAN wiring probe. OFF for normal A/B firmware.
option(CAN_LINK_PROBE_ONLY "Build the motor-disabled CAN link probe" OFF)
option(CAN_STATUS_TELEMETRY "Publish read-only 0x180 CAN status from normal APP" ON)
option(CAN_SHADOW_DIAG "Enable non-actuating CAN request/reply diagnostics" OFF)
option(CAN_CONTROL_REJECT_ONLY "Reply REJECT_DISABLED to all valid control frames" OFF)
option(CAN_LOG_STREAM "Mirror Pigweed logs over bounded read-only CAN transport" OFF)
option(PW_LOG_TOKENIZED_DEFAULT "Tokenize ordinary PW_LOG diagnostics; keep UART command/reply text unchanged" OFF)
option(PW_TARGET_UNIT_TESTS "Include startup-only Pigweed generic unit tests (not safety selfchecks)" ON)
set(PW_LOG_STORE_SLOTS "64" CACHE STRING "Shared log records; 48 saves 3328 RAM bytes; legacy default 64")
set_property(CACHE PW_LOG_STORE_SLOTS PROPERTY STRINGS 48 64)
if(NOT PW_LOG_STORE_SLOTS MATCHES "^(48|64)$")
    message(FATAL_ERROR "PW_LOG_STORE_SLOTS must be 48 or 64")
endif()
option(SAFETY_LOCKED_BOOT "Boot into non-actuating raw-sampling/interlock diagnostics" OFF)
option(ZERO_RETEST_BOOT "Output-locked service/zero-only diagnostics; never motor-ready" OFF)
option(FOC_OC_LAYERED_SELFTEST "Fixed synthetic protection selftest; standalone power-locked service ONLY" OFF)
option(ZERO_MEDIAN_DIAGNOSTIC "Locked-only three-point median/raw zero contrast; no motor qualification" OFF)
option(SWITCH_FEEDBACK_DIAGNOSTIC "Open-load explicit PWM/bridge interference capture; never motor control" OFF)
option(SWITCH_SIGNAL_ONLY_DIAGNOSTIC "Switch diagnostic with bridge enable compiled out; six-signal qualification ONLY" OFF)
option(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC "Disconnected-motor 50ms bridge fixture with filtered protection; NOT motor control" OFF)
if(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC AND (NOT SWITCH_FEEDBACK_DIAGNOSTIC OR SWITCH_SIGNAL_ONLY_DIAGNOSTIC))
    message(FATAL_ERROR "Filtered bridge requires standalone switch diagnostic, not signal-only")
endif()
if(SWITCH_SIGNAL_ONLY_DIAGNOSTIC AND NOT SWITCH_FEEDBACK_DIAGNOSTIC)
    message(FATAL_ERROR "Signal-only qualification requires switch feedback diagnostic")
endif()
if(SWITCH_FEEDBACK_DIAGNOSTIC AND (NOT ZERO_RETEST_BOOT OR NOT ZERO_MEDIAN_DIAGNOSTIC OR ADC_DMA_RAW_DIAGNOSTIC))
    message(FATAL_ERROR "Switch feedback requires standalone injected raw/median diagnostics")
endif()
if(ZERO_MEDIAN_DIAGNOSTIC AND (NOT ZERO_RETEST_BOOT OR ADC_DMA_RAW_DIAGNOSTIC))
    message(FATAL_ERROR "Zero median contrast requires standalone injected locked diagnostics")
endif()
option(ADC_DMA_RAW_DIAGNOSTIC "Finite timer-triggered IU/IV regular ADC DMA; locked service ONLY" OFF)
option(ADC_DMA_THREE_PHASE_DIAGNOSTIC "Add actual PC3/IW to output-locked raw DMA capture" OFF)
option(ADC_DMA_PARALLEL_DIAGNOSTIC "Independent ADC1/2/5 common-event PA0/PA1/PA8 raw DMA" OFF)
option(ADC_DMA_PARALLEL_LONG_SAMPLE "Locked diagnostic-only 247.5-cycle sampling contrast" OFF)
option(ADC_DMA_PA1_ONLY_DIAGNOSTIC "Locked PA1-only contrast; U/W not sampled" OFF)
option(ADC_DMA_ADC12_ONLY_DIAGNOSTIC "Locked ADC1/2-only contrast; W not sampled" OFF)
option(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC "Hard-off known-input raw capture with explicit drive-supply OFF/ON" OFF)
option(ADC_CONTROL_PINS_LOW_DIAGNOSTIC "Locked reference ONLY: six control pins held GPIO low" OFF)
option(ADC_DMA_REFERENCE_DOUBLE_CAPTURE "Locked GPIO-low ADC1/2 ONLY: 8192 pairs at unchanged 20 kHz" OFF)
if(ADC_DMA_REFERENCE_DOUBLE_CAPTURE AND NOT ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
    message(FATAL_ERROR "Double capture requires the GPIO-low locked reference diagnostic")
endif()
if(ADC_CONTROL_PINS_LOW_DIAGNOSTIC AND NOT ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
    message(FATAL_ERROR "Active-low pins require the standalone locked reference diagnostic")
endif()
if(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC AND
   (NOT ADC_DMA_ADC12_ONLY_DIAGNOSTIC OR NOT ADC_DMA_PARALLEL_LONG_SAMPLE OR
    NOT ADC_DMA_PARALLEL_DIAGNOSTIC OR NOT ADC_DMA_THREE_PHASE_DIAGNOSTIC OR
    NOT ADC_DMA_RAW_DIAGNOSTIC OR NOT ZERO_RETEST_BOOT OR ADC_DMA_PA1_ONLY_DIAGNOSTIC))
    message(FATAL_ERROR "Reference input contrast requires the standalone locked ADC1/2 long-sampling profile")
endif()
if(ADC_DMA_ADC12_ONLY_DIAGNOSTIC AND (NOT ADC_DMA_PARALLEL_LONG_SAMPLE OR ADC_DMA_PA1_ONLY_DIAGNOSTIC))
    message(FATAL_ERROR "ADC1/2-only contrast requires long sampling and excludes PA1-only")
endif()
if(ADC_DMA_PA1_ONLY_DIAGNOSTIC AND NOT ADC_DMA_PARALLEL_LONG_SAMPLE)
    message(FATAL_ERROR "PA1-only contrast requires the standalone long-sampling diagnostic")
endif()
if(ADC_DMA_PARALLEL_LONG_SAMPLE AND NOT ADC_DMA_PARALLEL_DIAGNOSTIC)
    message(FATAL_ERROR "Long sampling requires the standalone locked parallel diagnostic")
endif()
if(ADC_DMA_PARALLEL_DIAGNOSTIC AND NOT ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    message(FATAL_ERROR "Parallel capture requires the locked three-phase raw profile")
endif()
if(ADC_DMA_THREE_PHASE_DIAGNOSTIC AND NOT ADC_DMA_RAW_DIAGNOSTIC)
    message(FATAL_ERROR "Three-phase capture requires ADC_DMA_RAW_DIAGNOSTIC")
endif()
if(ADC_DMA_RAW_DIAGNOSTIC AND NOT ZERO_RETEST_BOOT)
    message(FATAL_ERROR "ADC DMA raw diagnostic requires ZERO_RETEST_BOOT")
endif()
option(ESP_NETWORK_OBSERVER "Transmit one-way network observations; no ESP commands" OFF)
option(CAN_RPC_READ_ONLY "Bounded CAN transport for isolated read-only Pigweed RPC" OFF)
option(CAN_MOTOR_CONTROL_SERVICE "CAN motor RPC service with permanently locked MCU admission" OFF)
if(CAN_MOTOR_CONTROL_SERVICE AND NOT CAN_RPC_READ_ONLY)
    message(FATAL_ERROR "Motor RPC service requires the existing CAN RPC transport")
endif()
option(UART_FIRMWARE_TRANSFER "Official local UART Transfer.Write; old IAP retained" ON)
option(PW_ALLOCATOR_HYBRID "Bounded non-real-time UART payloads and log snapshot indices" ON)
if(SAFETY_LOCKED_BOOT OR CAN_LINK_PROBE_ONLY)
    set(UART_FIRMWARE_TRANSFER OFF)
    set(PW_ALLOCATOR_HYBRID OFF)
endif()
option(ROUTER_READ_ONLY_NETWORK "Read-only multi-node Router diagnostics; no console forwarding" OFF)
option(ROUTER_READ_ONLY_RPC "Opt-in bounded unary Pigweed RPC over Router" OFF)
option(AS5047P_SPI_DMA "Experimental bounded-deadline SPI1 DMA encoder; hardware timing unverified" OFF)
option(AS5047P_DMA_IRQ_PREEMPT_ADC "Experimental protected-loop IRQ ordering: TIM7 > encoder DMA/TIM2 > ADC" OFF)
option(FOC_ADC_WINDOW "Opt-in CH4 window planner and ADC timing diagnostics; analog validation required" OFF)
option(FOC_ISOLATED_CONCURRENCY "Bounded compute-only acceptance; SD/MOE/CCER hard locked" OFF)
option(FOC_ZERO_MEDIAN_COMPUTE_ONLY "Median zero feeding the real FOC arithmetic; power remains hard off" OFF)
option(FOC_CURRENT_SPIKE_ONLY "Experimental chronological isolated-spike filter; output-locked profiles only" OFF)
option(FOC_CURRENT_TREND4 "Four-point trend candidate in hard-off FOC compute fixture" OFF)
option(FOC_ENABLE_LEGACY_CURRENT_REPAIR "Historical protected repair experiments ONLY; new candidate uses reject/freeze" OFF)
option(FOC_FAST_REJECT_COMPUTE_ONLY "Fast-reject real-feedback computation with bridge enable compiled out" OFF)
set(FOC_CURRENT_FEEDBACK_SIGN "-1" CACHE STRING "Control current sign of raw-minus-zero; +1 is hard-off comparison ONLY")
set_property(CACHE FOC_CURRENT_FEEDBACK_SIGN PROPERTY STRINGS -1 1)
if(NOT FOC_CURRENT_FEEDBACK_SIGN MATCHES "^(-1|1)$")
    message(FATAL_ERROR "FOC_CURRENT_FEEDBACK_SIGN must be -1 or 1")
endif()
if(FOC_CURRENT_FEEDBACK_SIGN STREQUAL "1" AND NOT FOC_FAST_REJECT_COMPUTE_ONLY)
    message(FATAL_ERROR "Unqualified current polarity requires power-hard-off compute-only firmware")
endif()
if(FOC_PROTECTED_CLOSED_LOOP AND NOT FOC_ENABLE_LEGACY_CURRENT_REPAIR)
    if(NOT FOC_GUARD_FAST_PATH OR NOT FOC_LATEST_ORIGINAL_FSM OR
       FOC_RC_DEFERRED_SHADOW OR FOC_REPAIR_WINDOW_TRACE)
        message(FATAL_ERROR "Use FastCurrentReject preset, or explicitly select legacy research repair")
    endif()
endif()
if(FOC_FAST_REJECT_COMPUTE_ONLY AND (NOT FOC_PROTECTED_CLOSED_LOOP OR FOC_ENABLE_LEGACY_CURRENT_REPAIR))
    message(FATAL_ERROR "Fast reject compute-only requires the fast protected candidate")
endif()
option(FOC_PROTECTED_CLOSED_LOOP "Local one-shot 20rpm/400ms protected low-side motor trial; no boot actuation" OFF)
option(FOC_FAST_MATH "Opt-in bounded sin/cos and measured IRQ-body occupancy for protected FOC" OFF)
option(FOC_PAIR_FAST_PATH "Opt-in identical pair decisions with fixed-work reduction and first-late frame telemetry" OFF)
option(FOC_GUARD_FAST_PATH "Opt-in integer-only guardian and same-instant protection poll reuse" OFF)
option(FOC_FEEDBACK_FAST_PATH "Opt-in inline feedback kernels in protected O2 hot callers" OFF)
option(FOC_GATE_REUSE "Reuse hard-OFF gate proof only within one unchanged masked pair" OFF)
option(FOC_FAST_PATH_PROFILE "Power-hard-off phase DWT and actual CCR transaction evidence" OFF)
option(FOC_PREEMPT_COMMIT_PROBE "Hard-off IRQ attribution and non-invasive PWM timing" OFF)
option(FOC_HEAVY_PROFILE_ENABLE "Detailed IRQ attribution (OFF retains wall/deadline and actual PWM margin)" ON)
option(FOC_PWM_PIPELINE_CLOSED_LOOP "Protected original-FSM one-cycle PWM candidate; no automatic START" OFF)
option(FOC_LOADED_FSM_TRIAL "One-shot 20 rpm original tightening FSM with a 12 s lease; no automatic START" OFF)
option(FOC_SPEED_STARTUP_BRAKE "Loaded-trial SPEED integral rise guard and immediate stale-I braking release" OFF)
option(FOC_SPEED_BUMPLESS "SB2 bounded SPEED integral unload/rebuild; no immediate reset" OFF)
option(FOC_VOLTAGE_X2_TRIAL "Separate protected SB2 1.6V vector-limit comparison; integrator unchanged" OFF)
option(FOC_SPEED_BRAKE_TRACK "SB3 two-accepted-sample fast braking ceiling with integral tracking" OFF)
option(FOC_RUNDOWN_DIAGNOSTIC "Startup-only extended binary evidence; no control changes" OFF)
option(FOC_INTENT_FSM_CANDIDATE "Decoupled process FSM candidate; manual UART START only" OFF)
option(FOC_PWM_COMMON_MODE_ENABLE "Candidate equal-CCR offset for fixed ADC-window headroom" OFF)
option(FOC_RUNDOWN240_CANDIDATE "A-only manual 240rpm rundown / 300rpm trip; RAM recipe, SAVE disabled" OFF)
option(FOC_RUNDOWN240_TRAVEL20000 "A-only 240rpm subcandidate: 20000deg RAM travel, original 8s timeout" OFF)
option(FOC_ADC_COUNTS_100_40_CANDIDATE "A-only 20000deg subcandidate: TWO_SAMPLE jump=100 return=40, confirm/limit unchanged" OFF)
option(FOC_SPEED_PI_ANTI_WINDUP "A-only SB3 speed PI boundary admission; no trajectory or gain changes" OFF)
option(FOC_SPEED_SB3_DISABLE_CANDIDATE "A-only AW1 comparison: omit SB3 fast torque ceiling, retain independent protection" OFF)
option(FOC_SPEED_LEGACY_AW_COMPARE "A-only SB3-off comparison: remove new AW1, retain historical conditional integration" OFF)
option(FOC_SPEED_SCURVE_CANDIDATE "A-only AW0 SPEED jerk-limited reference; no PI/protection changes" OFF)
option(FOC_ACCEL_FEEDFORWARD_CANDIDATE "A-only S-curve acceleration FF and task-level evidence" OFF)
option(FOC_ACCEL_FF_AUDIT "A-only binary startup audit for S-curve acceleration current feedforward" OFF)
option(FOC_KA_IDENT_DIAG "A-only passive actual-Iq and actual-acceleration windows; no automatic identification writes" OFF)
option(FOC_KA_SYNC_DIAG "A-only coherent current/encoder short-window timestamps, read RAM after STOP" OFF)
option(FOC_KA_FULL_DIAG "A-only 2.4s coherent acceleration capture; no automatic Ka changes" OFF)
option(FOC_MECHANICAL_IDENT_DIAG "A-only passive mechanical current/encoder bins; no excitation or DOB actuation" OFF)
option(FOC_MECHANICAL_MOTION_DIAG "A-only explicit signed mechanical grid using existing protected FCAL owner" OFF)
option(FOC_MECHANICAL_HIGH_SPEED_DIAG "A-only supervised 500/600/700/800rpm grid, 1000rpm trip and 30000deg travel" OFF)
option(FOC_ENCODER_CONTROL_ADMISSION_FIX "A-only high-speed diagnostic: align plausibility envelope and reject false outer heartbeat" OFF)
option(FOC_OUTER_OBSERVE_AFTER_ACK "A-only encoder-fixed mechanical diagnostic: finish core update before task-only statistics, retain timing trace" OFF)
option(FOC_READY_TIMESTAMP_SNAPSHOT "A-only mechanical diagnostic: ordered ADC admission timestamps and failed-predicate latch" OFF)
option(FOC_MECHANICAL_REVERSE_IDENT_DIAG "A-only matching negative 600/700/800rpm identification; no DOB actuation" OFF)
option(FOC_MECHANICAL_DOB_SHADOW "A-only qualified normalized DOB observation, NEVER current feedback" OFF)
option(FOC_ID_STEADY_STATS "A-only unbiased fixed-window Id/Iq statistics; no control or gate changes" OFF)
option(FOC_DOB_ID_TRACE "A-only same-epoch Id/filter/reset/warmup trace reusing mechanical points" OFF)
option(FOC_DOB_REAL_TRACE "A-only passive fixed192ms raw task capture; reuse mechanical bins, default DOB OFF" OFF)
option(FOC_DOB_GAIN_AB_DIAG "A-only idle-selected DOB gain0.25/0.5 comparison; no saved parameter writes" OFF)
option(FOC_DOB_TREND_SHADOW "A-only read-only load trend observation; exclusive mechanical point buffer" OFF)
option(FOC_DOB_TREND_CONTINUOUS "A-only ABI2 whole-RUN trend trace independent of classifier lifecycle" OFF)
option(FOC_DOB_SATURATION_CONTINUE "A-only limited measurement observation; original feedback hold/fade and safety retained" OFF)
option(FOC_DOB_WARMUP_AB "A-only idle RAM selection of 5/3 tau, default five" OFF)
option(FOC_DOB_TREND_WINDOW75 "A-only 75ms/45point/45ms classifier window, unchanged ABI and trend filter" OFF)
option(FOC_DOB_LOAD_SPEED "A-only experimental RUNDOWN240/120 load speed selection" OFF)
option(FOC_DOB_LOAD_SPEED_CONTACT_HOLD "A-only preserve selected slow speed during unconfirmed contact" OFF)
if(FOC_DOB_LOAD_SPEED_CONTACT_HOLD AND NOT FOC_DOB_LOAD_SPEED)
    message(FATAL_ERROR "Contact-hold requires the opt-in load-speed candidate")
endif()
option(FOC_DOB_SHORT_LOW_RECOVERY "A-only bounded low-speed recovery candidate" OFF)
option(FOC_DOB_LOW_AUDIT "A-only persistent first/last short-low fallback snapshots" OFF)
if(FOC_DOB_LOW_AUDIT AND NOT FOC_DOB_SHORT_LOW_RECOVERY)
    message(FATAL_ERROR "Short-low audit requires its candidate")
endif()
if(FOC_DOB_SHORT_LOW_RECOVERY AND (NOT FOC_DOB_TREND_WINDOW75 OR FOC_DOB_RECOVERY_TIMING))
    message(FATAL_ERROR "Short-low candidate requires window75 and replaces recovery timing")
endif()
option(FOC_DOB_RECOVERY_TIMING "A-only passive recovery stage timing in unused75-window tail" OFF)
if(FOC_DOB_LOAD_SPEED AND (NOT FOC_DOB_TREND_WINDOW75 OR FOC_DOB_SHORT_LOW_RECOVERY OR FOC_DOB_LOW_AUDIT OR FOC_DOB_RECOVERY_TIMING))
    message(FATAL_ERROR "Load speed candidate requires exclusive window75 tail, without low-recovery experiments")
endif()
if(FOC_DOB_RECOVERY_TIMING AND NOT FOC_DOB_TREND_WINDOW75)
    message(FATAL_ERROR "Recovery timing requires the selected window75 A profile")
endif()
set(FOC_DOB_WARMUP_DEFAULT_TAU "5" CACHE STRING "A diagnostic startup warmup, 3 or 5 tau")
if(NOT FOC_DOB_WARMUP_DEFAULT_TAU MATCHES "^(3|5)$")
    message(FATAL_ERROR "DOB warmup default must be 3 or 5 tau")
endif()
if(FOC_DOB_WARMUP_AB AND NOT FOC_DOB_SATURATION_CONTINUE)
    message(FATAL_ERROR "Warmup A/B requires the saturation continuity candidate")
endif()
if(FOC_DOB_TREND_WINDOW75 AND (NOT FOC_DOB_WARMUP_AB OR NOT FOC_DOB_TREND_CONTINUOUS OR
   NOT FOC_DOB_WARMUP_DEFAULT_TAU STREQUAL "3"))
    message(FATAL_ERROR "Window75 requires the selected continuous warmup3 A profile")
endif()
if(FOC_DOB_SATURATION_CONTINUE AND (NOT FOC_DOB_TREND_CONTINUOUS OR NOT FOC_DOB_NORMAL_CONTROL OR
   NOT FOC_NORMAL_RUN_TRIP500 OR NOT FOC_DOB_ID_PRE_LPF_QUALITY))
    message(FATAL_ERROR "Saturation continuity requires the continuous normal500 pre-LPF candidate")
endif()
if(FOC_DOB_TREND_CONTINUOUS AND (NOT FOC_DOB_TREND_SHADOW OR NOT FOC_NORMAL_RUN_TRIP500))
    message(FATAL_ERROR "Continuous trend requires the selected normal500 shadow profile")
endif()
if(FOC_DOB_TREND_SHADOW AND (NOT FOC_DOB_NORMAL_CONTROL OR NOT FOC_DOB_CONTACT20_OBSERVE10 OR
   FOC_DOB_REAL_TRACE OR FOC_DOB_ID_TRACE OR FOC_DOB_GAIN_AB_DIAG))
    message(FATAL_ERROR "Trend shadow requires normal CONTACT20/observe10 A and exclusive capture buffer")
endif()
if(FOC_DOB_GAIN_AB_DIAG AND NOT FOC_DOB_REAL_TRACE)
    message(FATAL_ERROR "DOB gain A/B requires the existing passive raw-trace normal A profile")
endif()
if(FOC_DOB_REAL_TRACE AND (NOT FOC_DOB_NORMAL_CONTROL OR NOT FOC_DOB_CONTACT20_OBSERVE10))
    message(FATAL_ERROR "Raw trace requires the existing CONTACT20/observe10 normal A profile")
endif()
option(FOC_DOB_SPIKE_ADMISSION "A-only DOB dq-pair admission; never changes realtime current selection/protection" OFF)
option(FOC_DOB_ADMISSION_START_GUARD "A-only qualify motion before DOB admission, capture first event" OFF)
option(FOC_DOB_DIRECT_JUMP_REJECT "A-only DOB immediate pair reject above 0.100A, no return/transition classifier" OFF)
option(FOC_DOB_RECOVERABLE_ADMISSION "A-only DOB skip raw-adjacent jumps without count latch; recover after gaps" OFF)
option(FOC_DOB_PERSISTENT_QUALITY "A-only DOB consecutive jump and sustained Id quality confirmation" OFF)
option(FOC_DOB_ID_PRE_LPF_QUALITY "A-only quarantine suspect dq before DOB LPFs; preserve state on isolated spikes" OFF)
option(FOC_DOB_PRE_LPF_JUMP_200MA "A-only pre-LPF DOB absolute signed-current difference threshold 0.200A" OFF)
option(FOC_DOB_FEEDBACK_CANDIDATE "A-only bounded low-gain DOB feedback diagnostic; defaults OFF at runtime" OFF)
option(FOC_DOB_NORMAL_CONTROL "Normal tightening A: qualified DOB feedback gain0.25, enabled after warmup" OFF)
option(FOC_NORMAL_RUN_TRIP500 "User-selected normal-run500rpm overspeed; never changes target/Iq/PI/B rollback" OFF)
option(FOC_DOB_CONTACT20_OBSERVE10 "A-only normal DOB candidate: CONTACT20rpm, observe10rpm, fresh feedback remains20rpm" OFF)
if(FOC_DOB_CONTACT20_OBSERVE10 AND NOT FOC_DOB_NORMAL_CONTROL)
    message(FATAL_ERROR "CONTACT20/observe10 requires the isolated normal DOB A profile")
endif()
if(FOC_DOB_NORMAL_CONTROL AND (NOT FOC_DOB_FEEDBACK_CANDIDATE OR
   NOT FOC_MECHANICAL_IDENT_DIAG OR NOT FOC_INTENT_FSM_CANDIDATE OR
   FOC_DOB_FB_GAIN_ONE OR FOC_DOB_FB_GAIN_HALF OR FOC_DOB_FB_GAIN_015 OR
   FOC_MECHANICAL_MOTION_DIAG OR FOC_MECHANICAL_HIGH_SPEED_DIAG OR
   FOC_FRICTION_CALIBRATION_DIAG OR FOC_DOB_ID_TRACE OR FOC_ID_STEADY_STATS))
    message(FATAL_ERROR "Normal DOB requires normal intent FSM, passive current capture, fixed gain0.25 and no motion/calibration/trace diagnostic")
endif()
if(FOC_NORMAL_RUN_TRIP500 AND (NOT FOC_DOB_NORMAL_CONTROL OR NOT FOC_RUNDOWN240_CANDIDATE OR
   FOC_PSI_IDENT_DIAG OR FOC_PSI_IDENT_TRIP500 OR FOC_MECHANICAL_HIGH_SPEED_DIAG))
    message(FATAL_ERROR "Normal500 requires the normal protected DOB runtime, not an identification profile")
endif()
option(FOC_DOB_FB_GAIN_ONE "A-only diagnostic DOB gain1.0; compensation and motor limits unchanged" OFF)
option(FOC_DOB_FB_GAIN_HALF "A-only diagnostic DOB gain0.5; compensation and motor limits unchanged" OFF)
option(FOC_DOB_FB_GAIN_015 "A-only diagnostic DOB gain0.15; compensation and motor limits unchanged" OFF)
if(FOC_DOB_FB_GAIN_015 AND (NOT FOC_DOB_FEEDBACK_CANDIDATE OR FOC_DOB_FB_GAIN_ONE OR FOC_DOB_FB_GAIN_HALF))
    message(FATAL_ERROR "DOB gain0.15 requires feedback diagnostic and cannot combine with other gain overrides")
endif()
if(FOC_DOB_FB_GAIN_HALF AND (NOT FOC_DOB_FEEDBACK_CANDIDATE OR FOC_DOB_FB_GAIN_ONE))
    message(FATAL_ERROR "DOB gain0.5 requires feedback diagnostic and cannot combine with gain1")
endif()
if(FOC_DOB_FB_GAIN_ONE AND NOT FOC_DOB_FEEDBACK_CANDIDATE)
    message(FATAL_ERROR "DOB gain1.0 requires isolated feedback diagnostic")
endif()
if(FOC_DOB_FEEDBACK_CANDIDATE AND NOT (FOC_DOB_PRE_LPF_JUMP_200MA AND FOC_OUTER_OBSERVE_AFTER_ACK AND FOC_SPEED_FRICTION_CANDIDATE AND FOC_SPEED_PI_ANTI_WINDUP))
    message(FATAL_ERROR "DOB feedback requires isolated 200mA pre-LPF, task observer and total-output AW")
endif()
if(FOC_DOB_PRE_LPF_JUMP_200MA AND NOT FOC_DOB_ID_PRE_LPF_QUALITY)
    message(FATAL_ERROR "200mA DOB quality requires pre-LPF quarantine profile")
endif()
if(FOC_DOB_ID_PRE_LPF_QUALITY AND NOT FOC_DOB_PERSISTENT_QUALITY)
    message(FATAL_ERROR "Pre-LPF DOB quality requires persistent Id timing profile")
endif()
if(FOC_DOB_PERSISTENT_QUALITY AND NOT FOC_DOB_RECOVERABLE_ADMISSION)
    message(FATAL_ERROR "Persistent DOB quality requires recoverable profile")
endif()
if(FOC_DOB_RECOVERABLE_ADMISSION AND NOT FOC_DOB_DIRECT_JUMP_REJECT)
    message(FATAL_ERROR "Recoverable DOB admission requires direct jump profile")
endif()
if(FOC_DOB_DIRECT_JUMP_REJECT AND NOT FOC_DOB_ADMISSION_START_GUARD)
    message(FATAL_ERROR "DOB direct rejection requires isolated guarded diagnostic A")
endif()
if(FOC_DOB_ADMISSION_START_GUARD AND NOT FOC_DOB_SPIKE_ADMISSION)
    message(FATAL_ERROR "DOB start guard requires isolated spike-admission diagnostic A")
endif()
if(FOC_DOB_SPIKE_ADMISSION AND NOT FOC_DOB_ID_TRACE AND NOT FOC_DOB_NORMAL_CONTROL)
    message(FATAL_ERROR "DOB admission requires the isolated diagnostic trace profile")
endif()
if(FOC_DOB_ID_TRACE AND (NOT FOC_MECHANICAL_DOB_SHADOW OR FOC_ID_STEADY_STATS))
    message(FATAL_ERROR "DOB Id trace requires isolated shadow A, exclusive of steady statistics")
endif()
if(FOC_ID_STEADY_STATS AND NOT FOC_MECHANICAL_DOB_SHADOW)
    message(FATAL_ERROR "Id steady statistics require isolated DOB shadow A")
endif()
if(FOC_MECHANICAL_DOB_SHADOW AND (NOT FOC_READY_TIMESTAMP_SNAPSHOT OR
   NOT FOC_OUTER_OBSERVE_AFTER_ACK OR (NOT FOC_MECHANICAL_HIGH_SPEED_DIAG AND NOT FOC_DOB_NORMAL_CONTROL) OR FOC_MECHANICAL_REVERSE_IDENT_DIAG))
    message(FATAL_ERROR "DOB shadow requires the isolated readiness A profile, not reverse identification")
endif()
if(FOC_MECHANICAL_REVERSE_IDENT_DIAG AND (NOT FOC_READY_TIMESTAMP_SNAPSHOT OR NOT FOC_MECHANICAL_HIGH_SPEED_DIAG))
    message(FATAL_ERROR "Reverse identification requires the isolated high-speed readiness-snapshot A candidate")
endif()
if(FOC_READY_TIMESTAMP_SNAPSHOT AND NOT FOC_OUTER_OBSERVE_AFTER_ACK)
    message(FATAL_ERROR "Readiness snapshot fix requires the isolated outer-completion A candidate")
endif()
if(FOC_OUTER_OBSERVE_AFTER_ACK AND (NOT FOC_ENCODER_CONTROL_ADMISSION_FIX OR
   NOT FOC_MECHANICAL_IDENT_DIAG OR (NOT FOC_MECHANICAL_MOTION_DIAG AND NOT FOC_DOB_NORMAL_CONTROL) OR
   FOC_KA_SYNC_DIAG OR FOC_KA_FULL_DIAG OR FOC_KA_IDENT_DIAG OR
   FOC_ACCEL_FF_AUDIT OR FOC_STARTUP_TIMESTAMPS_DIAG))
    message(FATAL_ERROR "Deferred observations require the exclusive encoder-fixed mechanical A diagnostic")
endif()
if(FOC_ENCODER_CONTROL_ADMISSION_FIX AND NOT FOC_MECHANICAL_HIGH_SPEED_DIAG AND NOT FOC_DOB_NORMAL_CONTROL)
    message(FATAL_ERROR "Encoder admission fix is restricted to the explicit high-speed mechanical A candidate")
endif()
set(FOC_KA_SYNC_START_US "600000" CACHE STRING "Diagnostic-only short-window start after trajectory observations begin")
option(FOC_STARTUP_TIMESTAMPS_DIAG "A-only five distinct passive startup timestamps" OFF)
option(FOC_ACCEL_FF_ENABLED_DEFAULT "Boot default for candidate FF, idle-only RAM toggle also supported" ON)
set(FOC_ACCEL_FF_KA_A_PER_RPM_S "0.0001875" CACHE STRING "Acceleration FF A/(rpm/s); no persistent write")
option(FOC_SPEED_FRICTION_CANDIDATE "A-only Coulomb term combined with existing acceleration FF" OFF)
if(FOC_STARTUP_TIMESTAMPS_DIAG AND (NOT FOC_ACCEL_FF_AUDIT OR NOT FOC_SPEED_FRICTION_CANDIDATE OR NOT AS5047P_SPI_DMA))
    message(FATAL_ERROR "Startup timestamps require acceleration audit, friction evidence and encoder DMA")
endif()
option(FOC_CURRENT_STEP_AB_DIAG "A-only manual one-batch current PI step comparison; no normal START" OFF)
option(FOC_OUTPUT_GATE_EVIDENCE "A-only step diagnostic: first pre-closure failed gate predicate" OFF)
option(FOC_CURRENT_STEP_IDENT_POLICY "A-only step diagnostic: reuse identification encoder arbitration/timing policy" OFF)
if(FOC_OUTPUT_GATE_EVIDENCE AND NOT FOC_CURRENT_STEP_AB_DIAG)
    message(FATAL_ERROR "Output gate evidence requires the exclusive manual current-step diagnostic")
endif()
option(FOC_CURRENT_PI_IDENTIFIED_ENABLE "A-only unqualified Rs/Ld/Lq current PI comparison; manual use only" OFF)
option(FOC_DQ_DECOUPLING_CANDIDATE "A-only inductive dq cross-coupling voltage feedforward" OFF)
option(FOC_DQ_DECOUPLING_ENABLED_DEFAULT "A candidate runtime default; idle-only console toggle" OFF)
option(FOC_BEMF_CANDIDATE "A-only PM back-EMF voltage feedforward; calibrated flux required" OFF)
option(FOC_BEMF_GAIN_DIAG "A-only idle-selected 0/25/50/75/100 percent BEMF test" OFF)
if(FOC_BEMF_GAIN_DIAG AND (NOT FOC_BEMF_CANDIDATE OR FOC_BEMF_ENABLED_DEFAULT))
    message(FATAL_ERROR "BEMF gain diagnostic requires BEMF candidate default OFF")
endif()
option(FOC_PSI_IDENT_DIAG "A-only manual steady dq PM-flux estimation; never auto-applies result" OFF)
option(FOC_PSI_IDENT_TRIP500 "A-only PSI diagnostic: explicitly requested 500rpm overspeed trip" OFF)
option(FOC_PSI_IDENT_API400 "A-only PSI 300/400rpm supervised identification command range" OFF)
if(FOC_PSI_IDENT_API400 AND (NOT FOC_PSI_IDENT_TRIP500 OR NOT FOC_PSI_IDENT_DIAG))
    message(FATAL_ERROR "400rpm API requires the exclusive PSI diagnostic and explicit 500rpm trip")
endif()
if(FOC_PSI_IDENT_TRIP500 AND (NOT FOC_PSI_IDENT_DIAG OR NOT FOC_RUNDOWN240_CANDIDATE))
    message(FATAL_ERROR "500rpm trip is restricted to the exclusive protected PSI identification candidate")
endif()
option(FOC_BEMF_ENABLED_DEFAULT "A-only back-EMF boot default; idle-only toggle" OFF)
set(FOC_BEMF_PSI_WB "0.0" CACHE STRING "Phase-peak PM flux Wb, zero=uncalibrated; NOT line-line RMS Ke/Kv")
if(FOC_BEMF_CANDIDATE)
    if(NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_ONE_CYCLE_PWM_PIPELINE OR
       FOC_DQ_DECOUPLING_CANDIDATE OR FOC_CURRENT_STEP_AB_DIAG OR
       FOC_MOTOR_IDENTIFICATION_DIAG OR FOC_IDENT_VOLTAGE_STEP_DIAG)
        message(FATAL_ERROR "BEMF requires protected PI/pipeline and excludes dq/step/identification modes")
    endif()
    if(NOT FOC_BEMF_PSI_WB MATCHES "^[0-9]+(\\.[0-9]+)?$" OR
       FOC_BEMF_PSI_WB GREATER 1)
        message(FATAL_ERROR "PSI must be decimal Wb in [0,1]; zero means uncalibrated")
    endif()
    if(FOC_BEMF_ENABLED_DEFAULT AND FOC_BEMF_PSI_WB LESS_EQUAL 0)
        message(FATAL_ERROR "Cannot enable BEMF without a calibrated positive PSI")
    endif()
    set(FOC_BEMF_PSI_LITERAL "${FOC_BEMF_PSI_WB}")
    if(NOT FOC_BEMF_PSI_LITERAL MATCHES "\\.")
        string(APPEND FOC_BEMF_PSI_LITERAL ".0")
    endif()
endif()
option(FOC_DQ_AUDIT_ENABLE "A-only coherent dq audit frames and full accepted-frame maxima; no control effect" OFF)
option(DECOUPLING_SIGN_TEST "A-only diagnostic compile-time sign experiments; NEVER automatic excitation" OFF)
set(DECOUPLING_SIGN_MODE "0" CACHE STRING "Diagnostic 0=current 1=reverse d 2=reverse q 3=reverse both")
if(NOT DECOUPLING_SIGN_MODE MATCHES "^[0-3]$")
    message(FATAL_ERROR "DECOUPLING_SIGN_MODE must be 0..3")
endif()
if(DECOUPLING_SIGN_TEST AND (NOT FOC_DQ_DECOUPLING_CANDIDATE OR NOT FOC_DQ_AUDIT_ENABLE))
    message(FATAL_ERROR "Sign tests require the A dq audit candidate")
endif()
if(NOT DECOUPLING_SIGN_TEST AND NOT DECOUPLING_SIGN_MODE STREQUAL "0")
    message(FATAL_ERROR "Non-nominal dq signs require DECOUPLING_SIGN_TEST")
endif()
if(FOC_DQ_AUDIT_ENABLE AND (NOT FOC_DQ_DECOUPLING_CANDIDATE OR NOT FOC_SPEED_SCURVE_CANDIDATE OR
   NOT FOC_ACCEL_FEEDFORWARD_CANDIDATE))
    message(FATAL_ERROR "DQ audit requires the unchanged dq/S-curve/tokenized FF candidate")
endif()
set(FOC_DQ_LD_H "0.00002003" CACHE STRING "Provisional Ld H; not a qualified identification result")
set(FOC_DQ_LQ_H "0.00001118" CACHE STRING "Provisional Lq H; not a qualified identification result")
if(FOC_DQ_DECOUPLING_CANDIDATE)
    if(NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_ONE_CYCLE_PWM_PIPELINE OR
       FOC_CURRENT_STEP_AB_DIAG OR FOC_MOTOR_IDENTIFICATION_DIAG OR FOC_IDENT_VOLTAGE_STEP_DIAG)
        message(FATAL_ERROR "DQ requires protected PI/pipeline, not exclusive step/identification diagnostics")
    endif()
    foreach(dq_l IN ITEMS FOC_DQ_LD_H FOC_DQ_LQ_H)
        if(NOT "${${dq_l}}" MATCHES "^[0-9]+(\\.[0-9]+)?$" OR
           ${${dq_l}} LESS_EQUAL 0 OR ${${dq_l}} GREATER 0.001)
            message(FATAL_ERROR "${dq_l} must be finite positive decimal H <= 0.001")
        endif()
    endforeach()
endif()
set(CURRENT_PI_CANDIDATE_BANDWIDTH_HZ "300.0" CACHE STRING "Candidate current PI bandwidth Hz; not a protection threshold")
if(FOC_CURRENT_PI_IDENTIFIED_ENABLE)
    if(NOT FOC_PROTECTED_CLOSED_LOOP OR FOC_IDENT_VOLTAGE_STEP_DIAG)
        message(FATAL_ERROR "Identified PI requires protected current control, not PI-bypassed voltage diagnostic")
    endif()
    if(NOT CURRENT_PI_CANDIDATE_BANDWIDTH_HZ MATCHES "^[0-9]+(\\.[0-9]+)?$" OR
       CURRENT_PI_CANDIDATE_BANDWIDTH_HZ LESS_EQUAL 0 OR CURRENT_PI_CANDIDATE_BANDWIDTH_HZ GREATER 300)
        message(FATAL_ERROR "Candidate bandwidth must be positive and <= original intended 300 Hz")
    endif()
endif()
option(FOC_MOTOR_IDENTIFICATION_DIAG "A-only locked-rotor manual Rs/Ld/Lq current-step diagnostic" OFF)
option(FOC_IDENT_CURRENT_REJECT_ENABLE "Identification-only bounded current-sample admission instead of single-point abort" OFF)
option(FOC_IDENT_TRAVEL_EXIT_ENABLE "Identification-only 0.10deg displacement exit; other safety/quality gates unchanged" ON)
option(FOC_IDENT_TIMING_TRACE_ENABLE "Identification-only first failed seq/dt snapshot" OFF)
option(FOC_IDENT_RS_GAP_ADMISSION_ENABLE "Rs-only bounded discriminator-held pair gaps; Ld/Lq remain strict" OFF)
option(FOC_IDENT_RS_GAP_COUNT_ONLY "Rs-only explained gaps: total is diagnostic, per-gap/duration bounds unchanged" OFF)
if(FOC_IDENT_RS_GAP_COUNT_ONLY AND
   (NOT FOC_MOTOR_IDENTIFICATION_DIAG OR NOT FOC_IDENT_RS_GAP_ADMISSION_ENABLE))
    message(FATAL_ERROR "Rs gap count-only requires exclusive identification and explained-gap admission")
endif()
option(FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT "Rs estimator-only total reject counter; continuous reject stop unchanged" OFF)
option(FOC_IDENT_RS_REJECT_COUNT_ONLY "Rs estimator rejects never stop by count; unchanged finite lease and independent protection" OFF)
option(FOC_IDENT_L_RS_ADMISSION_ENABLE "A-only Ld/Lq diagnostic: same estimator admission as Rs, fixed 104ms lease" OFF)
option(FOC_IDENT_VOLTAGE_STEP_DIAG "Exclusive A manual 50mV voltage-step identification, current PI bypassed" OFF)
if(FOC_IDENT_VOLTAGE_STEP_DIAG AND
   (NOT FOC_MOTOR_IDENTIFICATION_DIAG OR NOT FOC_IDENT_L_RS_ADMISSION_ENABLE))
    message(FATAL_ERROR "Voltage-step diagnostic requires exclusive identification and tested L admission")
endif()
if(FOC_IDENT_L_RS_ADMISSION_ENABLE AND
   (NOT FOC_MOTOR_IDENTIFICATION_DIAG OR NOT FOC_IDENT_RS_REJECT_COUNT_ONLY OR NOT FOC_IDENT_RS_GAP_COUNT_ONLY))
    message(FATAL_ERROR "L admission adaptation requires exclusive identification and full Rs count-only policies")
endif()
if(FOC_IDENT_RS_REJECT_COUNT_ONLY AND
   (NOT FOC_MOTOR_IDENTIFICATION_DIAG OR NOT FOC_IDENT_CURRENT_REJECT_ENABLE OR NOT FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT))
    message(FATAL_ERROR "Rs reject count-only requires exclusive identification, sample rejection and no-total-reject policy")
endif()
if(FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT AND
   (NOT FOC_MOTOR_IDENTIFICATION_DIAG OR NOT FOC_IDENT_CURRENT_REJECT_ENABLE))
    message(FATAL_ERROR "Rs total-reject override requires exclusive identification and sample rejection")
endif()
set(FOC_IDENT_RS_SOFT_DT_MAX_US "55" CACHE STRING "Rs-only software timestamp upper bound, 55 or 100 us")
if(NOT FOC_IDENT_RS_SOFT_DT_MAX_US MATCHES "^(55|100)$")
    message(FATAL_ERROR "Rs software dt limit must be 55 or 100 us")
endif()
if(NOT FOC_IDENT_RS_SOFT_DT_MAX_US STREQUAL "55" AND NOT FOC_MOTOR_IDENTIFICATION_DIAG)
    message(FATAL_ERROR "Rs software dt override requires exclusive motor identification diagnostic")
endif()
if(FOC_IDENT_RS_GAP_ADMISSION_ENABLE AND
   (NOT FOC_IDENT_TIMING_TRACE_ENABLE OR NOT FOC_IDENT_CURRENT_REJECT_ENABLE))
    message(FATAL_ERROR "Rs gap admission requires timing trace and bounded current admission")
endif()
if(FOC_IDENT_TIMING_TRACE_ENABLE AND NOT FOC_MOTOR_IDENTIFICATION_DIAG)
    message(FATAL_ERROR "Timing snapshot requires exclusive motor identification diagnostic")
endif()
if(NOT FOC_IDENT_TRAVEL_EXIT_ENABLE AND NOT FOC_MOTOR_IDENTIFICATION_DIAG)
    message(FATAL_ERROR "Disabling identification travel exit requires exclusive diagnostic mode")
endif()
if(FOC_IDENT_CURRENT_REJECT_ENABLE AND NOT FOC_MOTOR_IDENTIFICATION_DIAG)
    message(FATAL_ERROR "Identification current admission requires exclusive diagnostic mode")
endif()
option(FOC_FRICTION_CALIBRATION_DIAG "A-only one-shot signed speed plateau; never starts on boot" OFF)
if(FOC_PSI_IDENT_DIAG AND (NOT FOC_BEMF_CANDIDATE OR FOC_BEMF_ENABLED_DEFAULT OR
   NOT FOC_CURRENT_PI_IDENTIFIED_ENABLE OR NOT FOC_INTENT_FSM_CANDIDATE OR
   NOT FOC_SPEED_FRICTION_CANDIDATE OR NOT PW_LOG_TOKENIZED_DEFAULT OR
   FOC_CURRENT_STEP_AB_DIAG OR FOC_MOTOR_IDENTIFICATION_DIAG OR
   FOC_FRICTION_CALIBRATION_DIAG OR FOC_TORQUE_CHAIN_DIAG OR FOC_ANGLE_CHAIN_DIAG))
    message(FATAL_ERROR "PSI identification requires exclusive current-parameter protected A, BEMF OFF, existing FR1/tokenized backend")
endif()
option(FOC_FRICTION_HIGH_SPEED_GRID "A-only 200/240/260/280rpm calibration grid; 300rpm trip unchanged" OFF)
if(FOC_FRICTION_HIGH_SPEED_GRID AND NOT FOC_FRICTION_CALIBRATION_DIAG)
    message(FATAL_ERROR "High-speed grid requires the exclusive friction diagnostic")
endif()
option(FOC_FRICTION_ENABLED_DEFAULT "Boot default; RAM-only idle FRIC switch also supported" ON)
if(FOC_MECHANICAL_MOTION_DIAG AND (NOT FOC_MECHANICAL_IDENT_DIAG OR
   NOT FOC_FRICTION_CALIBRATION_DIAG OR NOT FOC_FRICTION_ENABLED_DEFAULT OR
   NOT FOC_BEMF_ENABLED_DEFAULT OR FOC_FRICTION_HIGH_SPEED_GRID))
    message(FATAL_ERROR "Mechanical grid requires passive capture, fixed FRIC/BEMF ON and exclusive FCAL owner")
endif()
if(FOC_MECHANICAL_HIGH_SPEED_DIAG AND (NOT FOC_MECHANICAL_MOTION_DIAG OR
   NOT FOC_RUNDOWN240_CANDIDATE OR NOT FOC_RUNDOWN240_TRAVEL20000 OR
   FOC_PSI_IDENT_DIAG OR FOC_PSI_IDENT_TRIP500 OR FOC_PSI_IDENT_API400))
    message(FATAL_ERROR "1000rpm trip/800rpm API/30000deg travel require the exclusive manual mechanical A diagnostic")
endif()
if(FOC_FRICTION_CALIBRATION_DIAG AND (NOT FOC_SPEED_FRICTION_CANDIDATE OR
    NOT FOC_INTENT_FSM_CANDIDATE OR (FOC_FRICTION_ENABLED_DEFAULT AND NOT FOC_MECHANICAL_MOTION_DIAG)))
    message(FATAL_ERROR "Friction calibration requires FR1 backend with FRIC default OFF")
endif()
set(FOC_FRICTION_I_A "0.20" CACHE STRING "Coulomb current, A; explicitly requested 40% of 0.50A")
set(FOC_FRICTION_DEADBAND_RPM "2.0" CACHE STRING "Coulomb speed-reference deadband, rpm")
if(FOC_MOTOR_IDENTIFICATION_DIAG AND (NOT FOC_SPEED_FRICTION_CANDIDATE OR
    NOT FOC_INTENT_FSM_CANDIDATE OR NOT FOC_PWM_PIPELINE_CLOSED_LOOP OR
    FOC_FRICTION_CALIBRATION_DIAG OR FOC_TORQUE_CHAIN_DIAG OR FOC_ANGLE_CHAIN_DIAG))
    message(FATAL_ERROR "Motor identification requires exclusive A FR1/pipeline owner, not other diagnostics")
endif()
if(FOC_CURRENT_STEP_AB_DIAG AND (NOT FOC_CURRENT_PI_IDENTIFIED_ENABLE OR
   NOT FOC_PWM_PIPELINE_CLOSED_LOOP OR NOT FOC_RUNDOWN240_CANDIDATE OR
   FOC_MOTOR_IDENTIFICATION_DIAG OR FOC_TORQUE_CHAIN_DIAG OR FOC_FRICTION_CALIBRATION_DIAG OR FOC_FAST_REJECT_COMPUTE_ONLY))
    message(FATAL_ERROR "Current step AB requires the exclusive protected new-PI A candidate")
endif()
if(FOC_SPEED_FRICTION_CANDIDATE)
    if(NOT FOC_ACCEL_FEEDFORWARD_CANDIDATE OR NOT FOC_ACCEL_FF_ENABLED_DEFAULT)
        message(FATAL_ERROR "Friction comparison requires the acceleration FF ON candidate")
    endif()
    foreach(param FOC_FRICTION_I_A FOC_FRICTION_DEADBAND_RPM)
        if(NOT ${param} MATCHES "^[0-9]+[.][0-9]+$")
            message(FATAL_ERROR "Friction parameters must be nonnegative finite decimals")
        endif()
    endforeach()
    if(FOC_FRICTION_I_A GREATER 0.50)
        message(FATAL_ERROR "Initial friction candidate cannot exceed existing 0.50A Iq limit")
    endif()
endif()
if(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
    if(NOT FOC_SPEED_SCURVE_CANDIDATE OR NOT PW_LOG_TOKENIZED_DEFAULT OR
       NOT FOC_SPEED_PI_ANTI_WINDUP OR NOT FOC_SPEED_SB3_DISABLE_CANDIDATE)
        message(FATAL_ERROR "Acceleration FF requires tokenized SC1, AW on, SB3 off")
    endif()
    if(NOT FOC_ACCEL_FF_KA_A_PER_RPM_S MATCHES "^[0-9]+[.][0-9]+$")
        message(FATAL_ERROR "Acceleration Ka must be a nonnegative decimal, e.g. 0.0001875")
    endif()
    if(FOC_ACCEL_FF_KA_A_PER_RPM_S GREATER 0.00025)
        message(FATAL_ERROR "Initial FF candidate caps Ka at 0.00025 (50mA at 200rpm/s); no current-limit change")
    endif()
endif()
if(FOC_ACCEL_FF_AUDIT AND (NOT FOC_ACCEL_FEEDFORWARD_CANDIDATE OR
   NOT FOC_SPEED_FRICTION_CANDIDATE OR NOT FOC_BEMF_CANDIDATE OR
   FOC_BEMF_ENABLED_DEFAULT OR FOC_PSI_IDENT_DIAG OR FOC_CURRENT_STEP_AB_DIAG OR
   FOC_MOTOR_IDENTIFICATION_DIAG OR FOC_DQ_DECOUPLING_CANDIDATE))
    message(FATAL_ERROR "Acceleration audit requires exclusive normal A FR1 with BEMF default OFF")
endif()
if(FOC_KA_IDENT_DIAG AND (NOT FOC_ACCEL_FEEDFORWARD_CANDIDATE OR
   NOT FOC_SPEED_FRICTION_CANDIDATE OR NOT AS5047P_SPI_DMA OR
   FOC_ACCEL_FF_AUDIT OR FOC_STARTUP_TIMESTAMPS_DIAG OR FOC_PSI_IDENT_DIAG OR
   FOC_CURRENT_STEP_AB_DIAG OR FOC_MOTOR_IDENTIFICATION_DIAG OR FOC_BEMF_ENABLED_DEFAULT))
    message(FATAL_ERROR "Ka identification requires exclusive normal speed-loop evidence, BEMF OFF and no competing diagnostic ring")
endif()
if(FOC_MECHANICAL_IDENT_DIAG AND (NOT FOC_PROTECTED_CLOSED_LOOP OR
   NOT FOC_PWM_PIPELINE_CLOSED_LOOP OR NOT FOC_SPEED_FRICTION_CANDIDATE OR
   NOT FOC_ACCEL_FEEDFORWARD_CANDIDATE OR NOT AS5047P_SPI_DMA OR NOT FOC_BEMF_CANDIDATE OR
   FOC_BEMF_GAIN_DIAG OR FOC_KA_FULL_DIAG OR FOC_KA_SYNC_DIAG OR FOC_KA_IDENT_DIAG OR
   FOC_ACCEL_FF_AUDIT OR FOC_STARTUP_TIMESTAMPS_DIAG OR FOC_PSI_IDENT_DIAG OR
   FOC_CURRENT_STEP_AB_DIAG OR FOC_MOTOR_IDENTIFICATION_DIAG OR FOC_DQ_DECOUPLING_CANDIDATE OR
   PW_TARGET_UNIT_TESTS OR NOT PW_LOG_STORE_SLOTS STREQUAL "48"))
    message(FATAL_ERROR "Mechanical capture requires isolated protected memory A; no competing diagnostic ring")
endif()
if(FOC_KA_FULL_DIAG AND (FOC_KA_SYNC_DIAG OR FOC_KA_IDENT_DIAG OR FOC_ACCEL_FF_AUDIT OR
   FOC_STARTUP_TIMESTAMPS_DIAG OR NOT FOC_BEMF_CANDIDATE OR FOC_BEMF_ENABLED_DEFAULT OR
   NOT FOC_SPEED_FRICTION_CANDIDATE OR NOT FOC_ACCEL_FEEDFORWARD_CANDIDATE OR
   NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_PWM_PIPELINE_CLOSED_LOOP OR
   NOT FOC_ACCEL_FF_KA_A_PER_RPM_S STREQUAL "0.0000000" OR PW_TARGET_UNIT_TESTS OR
   NOT PW_LOG_STORE_SLOTS STREQUAL "48"))
    message(FATAL_ERROR "Full Ka requires isolated memory A, zero Ka, protected loop, friction/BEMF-OFF")
endif()
if(FOC_KA_SYNC_DIAG)
    if(NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_ACCEL_FEEDFORWARD_CANDIDATE OR
       NOT FOC_SPEED_FRICTION_CANDIDATE OR NOT AS5047P_SPI_DMA OR
       FOC_KA_IDENT_DIAG OR FOC_ACCEL_FF_AUDIT OR FOC_STARTUP_TIMESTAMPS_DIAG OR
       FOC_PSI_IDENT_DIAG OR FOC_CURRENT_STEP_AB_DIAG OR FOC_MOTOR_IDENTIFICATION_DIAG OR
       FOC_BEMF_ENABLED_DEFAULT OR FOC_DQ_DECOUPLING_CANDIDATE)
        message(FATAL_ERROR "Ka sync requires protected normal A, exclusive observer and BEMF OFF")
    endif()
    if(NOT FOC_KA_SYNC_START_US MATCHES "^[0-9]+$" OR FOC_KA_SYNC_START_US GREATER 7000000)
        message(FATAL_ERROR "Ka sync start must be 0..7000000 us; no runtime lease change")
    endif()
endif()
if(FOC_SPEED_SCURVE_CANDIDATE AND (NOT FOC_SPEED_PI_ANTI_WINDUP OR
   NOT FOC_SPEED_SB3_DISABLE_CANDIDATE OR FOC_SPEED_LEGACY_AW_COMPARE OR
   NOT FOC_ADC_COUNTS_100_40_CANDIDATE))
    message(FATAL_ERROR "S-curve requires the separate protected AW0 candidate, AW on and SB3 off")
endif()
if(FOC_SPEED_LEGACY_AW_COMPARE AND (FOC_SPEED_PI_ANTI_WINDUP OR
   NOT FOC_SPEED_SB3_DISABLE_CANDIDATE OR NOT FOC_ADC_COUNTS_100_40_CANDIDATE))
    message(FATAL_ERROR "Legacy-AW comparison requires protected 100/40, SB3 off, new AW1 off")
endif()
if(FOC_SPEED_SB3_DISABLE_CANDIDATE AND ((NOT FOC_SPEED_PI_ANTI_WINDUP AND NOT FOC_SPEED_LEGACY_AW_COMPARE) OR
   NOT FOC_SPEED_BRAKE_TRACK OR NOT FOC_INTENT_FSM_CANDIDATE))
    message(FATAL_ERROR "SB3-off comparison requires the separate protected AW1 intent candidate")
endif()
if(FOC_SPEED_PI_ANTI_WINDUP AND (NOT FOC_ADC_COUNTS_100_40_CANDIDATE OR NOT FOC_SPEED_BRAKE_TRACK))
    message(FATAL_ERROR "Speed anti-windup requires the separate protected SB3 100/40 A candidate")
endif()
if(FOC_ADC_COUNTS_100_40_CANDIDATE AND (NOT FOC_RUNDOWN240_TRAVEL20000 OR
   NOT FOC_PROTECTED_CLOSED_LOOP OR FOC_ENABLE_LEGACY_CURRENT_REPAIR))
    message(FATAL_ERROR "100/40 ADC thresholds require the separate protected 240rpm/20000deg fast-reject candidate")
endif()
if(FOC_RUNDOWN240_TRAVEL20000 AND NOT FOC_RUNDOWN240_CANDIDATE)
    message(FATAL_ERROR "20000deg travel requires the separate protected 240rpm candidate")
endif()
if(FOC_RUNDOWN240_CANDIDATE AND (NOT FOC_INTENT_FSM_CANDIDATE OR NOT FOC_PWM_COMMON_MODE_ENABLE OR
   NOT FOC_LOADED_FSM_TRIAL OR NOT FOC_PWM_PIPELINE_CLOSED_LOOP OR TIGHTEN_SPEED_X2_OFFLINE))
    message(FATAL_ERROR "240rpm requires the separate protected common-mode intent candidate")
endif()
if(FOC_PWM_COMMON_MODE_ENABLE AND (NOT FOC_INTENT_FSM_CANDIDATE OR
   NOT FOC_PWM_PIPELINE_CLOSED_LOOP OR NOT FOC_ADC_RC_PROTECTED_CANDIDATE))
    message(FATAL_ERROR "Common-mode allocation requires the intent FSM protected fixed-trigger candidate")
endif()
if(FOC_INTENT_FSM_CANDIDATE AND (NOT FOC_LATEST_ORIGINAL_FSM OR NOT FOC_LOADED_FSM_TRIAL OR
   NOT FOC_SPEED_BRAKE_TRACK OR NOT FOC_ZERO_VALID_ADMISSION OR
   FOC_TORQUE_CHAIN_DIAG OR FOC_TORQUE450_150RPM OR FOC_TORQUE450_FIVE_SECOND OR
   FOC_SPEED_DYNAMIC_DIAG OR FOC_BREAKAWAY_CURRENT_TEST OR FOC_ANGLE_CHAIN_DIAG))
    message(FATAL_ERROR "Intent FSM requires the original protected SB3/zero backend, not a torque/limit experiment")
endif()
option(FOC_TORQUE_CHAIN_DIAG "Manual one-shot 200ms torque diagnostic; explicit fixed-current profiles only" OFF)
option(FOC_BREAKAWAY_CURRENT_TEST "Manual one-grade signed breakaway current diagnostic; never automatic" OFF)
option(FOC_BREAKAWAY_FIVE_SECOND "Five-second breakaway session, supervised host batch capable" OFF)
option(FOC_SPEED_DYNAMIC_DIAG "Manual 20rpm SPEED-only 5s trial; dynamic Iq limited to 500mA" OFF)
option(FOC_TORQUE350_FIVE_SECOND "Manual positive 350mA IQ-only diagnostic, five-second lease" OFF)
option(FOC_TORQUE450_FIVE_SECOND "Manual positive 450mA IQ-only diagnostic, five-second lease" OFF)
option(FOC_TORQUE450_150RPM "450mA manual comparison ONLY: 150rpm overspeed trip" OFF)
if(FOC_TORQUE450_150RPM AND NOT FOC_TORQUE450_FIVE_SECOND)
    message(FATAL_ERROR "150rpm comparison requires exclusive 450mA manual profile")
endif()
if(FOC_TORQUE450_FIVE_SECOND AND (NOT FOC_TORQUE_CHAIN_DIAG OR FOC_TORQUE350_FIVE_SECOND OR FOC_ANGLE_CHAIN_DIAG OR FOC_SPEED_DYNAMIC_DIAG OR FOC_BREAKAWAY_CURRENT_TEST OR NOT FOC_TORQUE_CHAIN_IQ_MA STREQUAL "450"))
    message(FATAL_ERROR "450mA diagnostic requires its exclusive protected manual IQ profile")
endif()
option(FOC_ANGLE_CHAIN_DIAG "Manual output-off angle audit and one 400ms electrical offset trial" OFF)
option(FOC_ANGLE_HAND_ONLY "Compile out angle diagnostic power admission" OFF)
if(FOC_ANGLE_HAND_ONLY AND NOT FOC_ANGLE_CHAIN_DIAG)
    message(FATAL_ERROR "Hand-only requires angle-chain diagnostic")
endif()
if(FOC_ANGLE_CHAIN_DIAG AND (NOT FOC_TORQUE_CHAIN_DIAG OR FOC_TORQUE350_FIVE_SECOND OR FOC_BREAKAWAY_CURRENT_TEST OR FOC_SPEED_DYNAMIC_DIAG))
    message(FATAL_ERROR "Angle diagnostic needs its exclusive protected manual owner")
endif()
if(FOC_ANGLE_CHAIN_DIAG AND NOT FOC_ANGLE_HAND_ONLY AND NOT FOC_TORQUE_CHAIN_IQ_MA STREQUAL "350")
    message(FATAL_ERROR "Offset trials require exactly +350mA")
endif()
if(FOC_TORQUE350_FIVE_SECOND AND (NOT FOC_TORQUE_CHAIN_DIAG OR FOC_BREAKAWAY_CURRENT_TEST OR FOC_SPEED_DYNAMIC_DIAG OR NOT FOC_TORQUE_CHAIN_IQ_MA STREQUAL "350"))
    message(FATAL_ERROR "350mA diagnostic requires its exclusive protected manual IQ profile")
endif()
if(FOC_SPEED_DYNAMIC_DIAG AND (NOT FOC_TORQUE_CHAIN_DIAG OR FOC_BREAKAWAY_CURRENT_TEST))
    message(FATAL_ERROR "Dynamic SPEED trial needs the protected manual owner, not breakaway")
endif()
if(FOC_BREAKAWAY_FIVE_SECOND AND NOT FOC_BREAKAWAY_CURRENT_TEST)
    message(FATAL_ERROR "Five-second test requires Breakaway diagnostic")
endif()
if(FOC_BREAKAWAY_CURRENT_TEST AND NOT FOC_TORQUE_CHAIN_DIAG)
    message(FATAL_ERROR "Breakaway test requires the complete protected manual torque diagnostic")
endif()
set(FOC_TORQUE_CHAIN_IQ_MA "100" CACHE STRING "Fixed diagnostic magnitude; 50 is historical only")
set_property(CACHE FOC_TORQUE_CHAIN_IQ_MA PROPERTY STRINGS 50 100 200)
if(FOC_TORQUE_CHAIN_DIAG AND NOT FOC_ANGLE_CHAIN_DIAG AND NOT FOC_TORQUE350_FIVE_SECOND AND NOT FOC_TORQUE450_FIVE_SECOND AND NOT FOC_TORQUE_CHAIN_IQ_MA MATCHES "^(50|100|200)$")
    message(FATAL_ERROR "Torque current must be an explicit 50/100/200mA profile; no automatic increase")
endif()
if(FOC_TORQUE_CHAIN_DIAG AND (NOT FOC_RUNDOWN_DIAGNOSTIC OR NOT FOC_PWM_PIPELINE_CLOSED_LOOP OR NOT FOC_SPEED_BRAKE_TRACK))
    message(FATAL_ERROR "Torque diagnostic requires the complete protected SB3 pipeline and binary evidence")
endif()
if(FOC_RUNDOWN_DIAGNOSTIC AND NOT FOC_SPEED_BRAKE_TRACK)
    message(FATAL_ERROR "Rundown evidence requires the complete unchanged SB3 candidate")
endif()
if(FOC_SPEED_BRAKE_TRACK AND NOT FOC_VOLTAGE_X2_TRIAL)
    message(FATAL_ERROR "SB3 requires the separate protected 1.6V SB2 trial")
endif()
if(FOC_VOLTAGE_X2_TRIAL AND NOT FOC_SPEED_BUMPLESS)
    message(FATAL_ERROR "Voltage X2 requires the complete protected SB2 trial")
endif()
option(FOC_ZERO_VALID_ADMISSION "Collect 4000 admitted zero pairs with finite reject/collection budgets" OFF)
if(FOC_SPEED_BUMPLESS AND (NOT FOC_SPEED_STARTUP_BRAKE OR NOT FOC_ZERO_VALID_ADMISSION))
    message(FATAL_ERROR "SB2 requires protected startup/brake and robust zero admission")
endif()
if(FOC_ZERO_VALID_ADMISSION AND NOT FOC_SPEED_STARTUP_BRAKE)
    message(FATAL_ERROR "Valid zero admission requires the unchanged SB1 protected trial")
endif()
if(FOC_SPEED_STARTUP_BRAKE AND NOT FOC_LOADED_FSM_TRIAL)
    message(FATAL_ERROR "Speed startup/brake requires the protected loaded-FSM trial")
endif()
if(FOC_LOADED_FSM_TRIAL AND NOT FOC_PWM_PIPELINE_CLOSED_LOOP)
    message(FATAL_ERROR "Loaded FSM trial requires the protected original-FSM pipeline")
endif()
option(FOC_CURRENT_FAULT_TRACE_ENABLE "16-pair RAM-only current-confirmation diagnostic" OFF)
if(FOC_CURRENT_FAULT_TRACE_ENABLE AND NOT FOC_PWM_PIPELINE_CLOSED_LOOP)
    message(FATAL_ERROR "Current fault trace requires the unchanged protected pipeline candidate")
endif()
option(FOC_ONE_CYCLE_PWM_PIPELINE "Hard-off one-ADC-cycle pending PWM, software guard below ADC" OFF)
option(AS5047P_DMA_FOC_FIRST "Hard-off FOC-first encoder event top halves and deferred service" OFF)
option(AS5047P_DMA_TERMINAL_FIX "A diagnostic candidate: arbitrate completion before cleanup against deadline" OFF)
option(AS5047P_DMA_TIMING_POLICY_V2 "A diagnostic: 200us transaction warning, 400us hard deadline; other timing contracts unchanged" OFF)
if(FOC_CURRENT_STEP_IDENT_POLICY AND (NOT FOC_CURRENT_STEP_AB_DIAG OR NOT FOC_OUTPUT_GATE_EVIDENCE OR
   NOT AS5047P_DMA_TERMINAL_FIX OR NOT AS5047P_DMA_TIMING_POLICY_V2))
    message(FATAL_ERROR "Step identification-policy adaptation requires exclusive step, gate evidence, terminal fix and timing policy V2")
endif()
if(AS5047P_DMA_TIMING_POLICY_V2 AND (NOT AS5047P_DMA_TERMINAL_FIX OR
   (NOT FOC_MOTOR_IDENTIFICATION_DIAG AND NOT FOC_CURRENT_STEP_IDENT_POLICY)))
    message(FATAL_ERROR "Encoder timing policy requires exclusive identification or explicit step adaptation, with terminal arbitration fix")
endif()
if(AS5047P_DMA_TERMINAL_FIX AND (NOT AS5047P_DMA_FOC_FIRST OR NOT FOC_IRQ_COMPACT OR
   (NOT FOC_MOTOR_IDENTIFICATION_DIAG AND NOT FOC_CURRENT_STEP_IDENT_POLICY)))
    message(FATAL_ERROR "Encoder terminal fix requires exclusive identification or explicit step adaptation / compact FOC-first candidate")
endif()
if(AS5047P_DMA_FOC_FIRST AND NOT FOC_ONE_CYCLE_PWM_PIPELINE)
    message(FATAL_ERROR "FOC-first encoder requires the hard-off one-cycle pipeline")
endif()
if(FOC_ONE_CYCLE_PWM_PIPELINE AND NOT FOC_PREEMPT_COMMIT_PROBE)
    message(FATAL_ERROR "One-cycle pipeline requires the separate hard-off preemption profile")
endif()
if(FOC_PWM_PIPELINE_CLOSED_LOOP AND (NOT FOC_ONE_CYCLE_PWM_PIPELINE OR
   NOT AS5047P_DMA_FOC_FIRST OR NOT FOC_PREEMPT_COMMIT_PROBE OR
   NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_LATEST_ORIGINAL_FSM OR
   NOT FOC_ADC_RC_PROTECTED_CANDIDATE OR FOC_FAST_REJECT_COMPUTE_ONLY OR
   FOC_ADAPTIVE_FILTER_EXPERIMENT OR FOC_COMPACT_CLOSED_LOOP))
    message(FATAL_ERROR "Pipeline closed-loop candidate requires complete protected original-FSM backend")
endif()
if(FOC_PREEMPT_COMMIT_PROBE AND ((NOT FOC_FAST_REJECT_COMPUTE_ONLY AND NOT FOC_PWM_PIPELINE_CLOSED_LOOP) OR
   NOT FOC_FAST_MATH OR NOT AS5047P_DMA_IRQ_PREEMPT_ADC OR FOC_FAST_PATH_PROFILE OR
   FOC_IRQ_SOURCE_TRACE OR FOC_PWM_BOUNDARY_TRACE OR FOC_PWM_BOUNDARY_LITE OR
   FOC_RC_DEFERRED_SHADOW OR FOC_ENABLE_LEGACY_CURRENT_REPAIR))
    message(FATAL_ERROR "Preemption commit probe requires separate fast hard-off profile")
endif()
if(FOC_FAST_PATH_PROFILE AND (NOT FOC_FAST_REJECT_COMPUTE_ONLY OR FOC_ENABLE_LEGACY_CURRENT_REPAIR OR NOT FOC_PROTECTED_CLOSED_LOOP))
    message(FATAL_ERROR "Fast-path profiling requires the fast-current power-hard-off candidate")
endif()
option(FOC_IRQ_SOURCE_TRACE "Diagnostic per-source exclusive IRQ body cost and first-late frame" OFF)
option(FOC_ADAPTIVE_FILTER_EXPERIMENT "Robust zero and bounded adaptive Trend4; bridge enable compiled out" OFF)
option(FOC_ZERO_TOTAL_BUDGET_OFF "Hard-off adaptive diagnostic: count all zero outliers without total quota" OFF)
option(FOC_ZERO_ALL_REJECTED_DIAG "Hard-off diagnostic only: burst trip when all five pairs are rejected" OFF)
if(FOC_ZERO_ALL_REJECTED_DIAG AND (NOT FOC_ADAPTIVE_FILTER_EXPERIMENT OR
   NOT FOC_ZERO_TOTAL_BUDGET_OFF OR NOT FOC_PROTECTED_CLOSED_LOOP OR
   FOC_LATEST_ORIGINAL_FSM OR FOC_COMPACT_CLOSED_LOOP))
    message(FATAL_ERROR "All-rejected zero policy requires a power-hard-off no-quota diagnostic")
endif()
option(FOC_RAM_HOT_PATH "Explicit timing profile: execute bounded ISR kernels from initialized SRAM" OFF)
option(FOC_IRQ_COMPACT "Explicit RAM profile: fixed encoder ops and inline live guardian predicates" OFF)
option(FOC_REPAIR_WINDOW_TRACE "Hard-off compact diagnostic: freeze last 32 repair decisions after output closure" OFF)
if(FOC_REPAIR_WINDOW_TRACE AND (NOT FOC_ZERO_ALL_REJECTED_DIAG OR NOT FOC_IRQ_COMPACT OR
   NOT FOC_RAM_HOT_PATH OR NOT FOC_ADAPTIVE_FILTER_EXPERIMENT OR FOC_LATEST_ORIGINAL_FSM OR FOC_COMPACT_CLOSED_LOOP))
    message(FATAL_ERROR "Repair window trace requires the compact all-rejected hard-off diagnostic")
endif()
option(FOC_COMPACT_CLOSED_LOOP "Separate protected fixed-filter compact 20rpm/400ms local motor trial" OFF)
option(FOC_LATEST_ORIGINAL_FSM "Latest adaptive protected backend with original START/tightening FSM; qualification candidate" OFF)
option(FOC_LATEST_ZERO_COUNT_ONLY "Latest/original FSM: zero outlier total is diagnostic-only; retain all other checks" OFF)
option(FOC_STARTUP_TRACE "Frozen startup evidence and first-fault classification fix; latest/original profile only" OFF)
if(FOC_STARTUP_TRACE AND NOT FOC_LATEST_ORIGINAL_FSM)
    message(FATAL_ERROR "Startup evidence requires latest/original protected integration")
endif()
if(FOC_LATEST_ZERO_COUNT_ONLY AND NOT FOC_LATEST_ORIGINAL_FSM)
    message(FATAL_ERROR "Count-only latest zero policy requires latest/original FSM")
endif()
if(FOC_LATEST_ORIGINAL_FSM AND (NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_RAM_HOT_PATH OR
   NOT FOC_IRQ_COMPACT OR NOT FOC_GATE_REUSE OR FOC_COMPACT_CLOSED_LOOP OR
   FOC_ADAPTIVE_FILTER_EXPERIMENT OR FOC_ZERO_TOTAL_BUDGET_OFF OR FOC_IRQ_SOURCE_TRACE))
    message(FATAL_ERROR "Latest/original FSM requires complete protected RAM/IRQ profile without diagnostic bypasses")
endif()
if(FOC_COMPACT_CLOSED_LOOP AND (NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_RAM_HOT_PATH OR
   NOT FOC_IRQ_COMPACT OR NOT FOC_GATE_REUSE OR FOC_ADAPTIVE_FILTER_EXPERIMENT OR
   FOC_ZERO_TOTAL_BUDGET_OFF OR FOC_IRQ_SOURCE_TRACE))
    message(FATAL_ERROR "Compact motor trial requires protected fixed-filter RAM/IRQ profile without experiment bypasses")
endif()
if(FOC_IRQ_COMPACT AND NOT FOC_RAM_HOT_PATH)
    message(FATAL_ERROR "Compact IRQ candidate requires an explicit RAM profile")
endif()
if(FOC_RAM_HOT_PATH AND (NOT FOC_GATE_REUSE OR
   (NOT FOC_ADAPTIVE_FILTER_EXPERIMENT AND NOT FOC_COMPACT_CLOSED_LOOP AND NOT FOC_LATEST_ORIGINAL_FSM)))
    message(FATAL_ERROR "RAM hot path requires hard-off adaptive or separate protected compact trial")
endif()
if(FOC_ZERO_TOTAL_BUDGET_OFF AND NOT FOC_ADAPTIVE_FILTER_EXPERIMENT)
    message(FATAL_ERROR "No-quota zero calibration requires the hard-off adaptive experiment")
endif()
if(FOC_ADAPTIVE_FILTER_EXPERIMENT AND (NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_CURRENT_TREND4 OR
   NOT FOC_GATE_REUSE OR FOC_IRQ_SOURCE_TRACE))
    message(FATAL_ERROR "Adaptive filter is a separate hard-off GateReuse candidate without trace probes")
endif()
if((FOC_GATE_REUSE OR FOC_IRQ_SOURCE_TRACE) AND NOT FOC_FEEDBACK_FAST_PATH)
    message(FATAL_ERROR "Gate reuse/IRQ source trace require feedback-fast candidate")
endif()
if(FOC_FEEDBACK_FAST_PATH AND NOT FOC_GUARD_FAST_PATH)
    message(FATAL_ERROR "Feedback fast path requires integer-guard candidate")
endif()
if(FOC_GUARD_FAST_PATH AND NOT FOC_PAIR_FAST_PATH)
    message(FATAL_ERROR "Guard fast path requires protected pair fast path")
endif()
if(FOC_PAIR_FAST_PATH AND NOT FOC_FAST_MATH)
    message(FATAL_ERROR "Pair fast path requires protected fast math")
endif()
if(FOC_FAST_MATH AND (NOT FOC_PROTECTED_CLOSED_LOOP OR NOT AS5047P_DMA_IRQ_PREEMPT_ADC))
    message(FATAL_ERROR "Fast FOC math requires the protected encoder-priority profile")
endif()
if(AS5047P_DMA_IRQ_PREEMPT_ADC AND (NOT AS5047P_SPI_DMA OR NOT FOC_PROTECTED_CLOSED_LOOP))
    message(FATAL_ERROR "Encoder IRQ preemption requires the protected closed-loop DMA profile")
endif()
if(FOC_PROTECTED_CLOSED_LOOP AND (NOT FOC_ADC_WINDOW OR NOT AS5047P_SPI_DMA OR
   NOT FOC_CURRENT_TREND4 OR NOT FOC_CURRENT_SPIKE_ONLY OR FOC_ISOLATED_CONCURRENCY OR
   FOC_FEEDBACK_SAFETY_BINDING OR FOC_CONTROL_CHAIN_RECONNECT OR FOC_RAW_OBSERVE_ONLY OR
   FOC_FILTERED_OBSERVE_ONLY OR ZERO_RETEST_BOOT OR SWITCH_FEEDBACK_DIAGNOSTIC OR
   SAFETY_LOCKED_BOOT OR CAN_LINK_PROBE_ONLY OR CAN_FD_EXPERIMENT OR CAN_MOTOR_CONTROL_SERVICE OR
   TIGHTEN_SYNTHETIC_BENCH OR FOC_ZERO_FAILURE_TRACE OR FOC_OC_LAYERED_SELFTEST))
    message(FATAL_ERROR "Protected motor trial is a separate low-side profile, no diagnostic bypasses")
endif()
if(FOC_CURRENT_TREND4 AND NOT FOC_PROTECTED_CLOSED_LOOP AND (NOT FOC_CURRENT_SPIKE_ONLY OR NOT FOC_ISOLATED_CONCURRENCY OR
   NOT FOC_ZERO_MEDIAN_COMPUTE_ONLY OR FOC_ZERO_FAILURE_TRACE OR SWITCH_FEEDBACK_DIAGNOSTIC))
    message(FATAL_ERROR "Trend4 requires hard-off filtered-zero FOC compute; no bridge or legacy trace")
endif()
option(FOC_ZERO_FAILURE_TRACE "Fixed pre/post failure raw trace; locked spike zero diagnosis ONLY" OFF)
option(FOC_RAW_OBSERVE_ONLY "Raw overrange is observe-only in hard-off Trend4 compute; NEVER motor control" OFF)
option(FOC_FILTERED_OBSERVE_ONLY "Filtered overrange is observe-only in hard-off raw observation; NEVER motor control" OFF)
option(FOC_FEEDBACK_SAFETY_BINDING "Filtered confirmation and TIM7 shutdown in hard-off FOC fixture ONLY" OFF)
option(FOC_CONTROL_CHAIN_RECONNECT "Original speed/current/tightening tasks with filtered feedback; HARD-OFF ONLY" OFF)
if(FOC_CONTROL_CHAIN_RECONNECT AND (NOT FOC_FEEDBACK_SAFETY_BINDING OR CAN_FD_EXPERIMENT OR CAN_MOTOR_CONTROL_SERVICE))
    message(FATAL_ERROR "Control chain reconnect requires hard-off feedback binding and read-only classic CAN")
endif()
if(FOC_FEEDBACK_SAFETY_BINDING AND (NOT FOC_CURRENT_TREND4 OR NOT FOC_CURRENT_SPIKE_ONLY OR
   NOT FOC_ISOLATED_CONCURRENCY OR NOT FOC_ZERO_MEDIAN_COMPUTE_ONLY OR NOT FOC_ADC_WINDOW OR
   NOT AS5047P_SPI_DMA OR FOC_RAW_OBSERVE_ONLY OR FOC_FILTERED_OBSERVE_ONLY OR
   ZERO_RETEST_BOOT OR SWITCH_FEEDBACK_DIAGNOSTIC OR FOC_ZERO_FAILURE_TRACE OR
   FOC_OC_LAYERED_SELFTEST OR TIGHTEN_SYNTHETIC_BENCH))
    message(FATAL_ERROR "Feedback binding requires standalone hard-off compute, without observation bypasses")
endif()
if(FOC_FILTERED_OBSERVE_ONLY AND NOT FOC_RAW_OBSERVE_ONLY)
    message(FATAL_ERROR "Filtered observe-only requires hard-off raw observation; NEVER motor control")
endif()
if(FOC_RAW_OBSERVE_ONLY AND (NOT FOC_CURRENT_TREND4 OR NOT FOC_CURRENT_SPIKE_ONLY OR
   NOT FOC_ISOLATED_CONCURRENCY OR NOT FOC_ZERO_MEDIAN_COMPUTE_ONLY OR
   ZERO_RETEST_BOOT OR FOC_ZERO_FAILURE_TRACE OR SWITCH_FEEDBACK_DIAGNOSTIC OR
   FOC_OC_LAYERED_SELFTEST OR TIGHTEN_SYNTHETIC_BENCH))
    message(FATAL_ERROR "Raw observe-only requires standalone hard-off Trend4 compute; NEVER bridge or motor control")
endif()
if(FOC_OC_LAYERED_SELFTEST AND (NOT ZERO_RETEST_BOOT OR ZERO_MEDIAN_DIAGNOSTIC OR
   SWITCH_FEEDBACK_DIAGNOSTIC OR ADC_DMA_RAW_DIAGNOSTIC OR FOC_CURRENT_SPIKE_ONLY OR
   FOC_ISOLATED_CONCURRENCY OR FOC_ZERO_FAILURE_TRACE))
    message(FATAL_ERROR "Layered selftest requires standalone synthetic output-locked service")
endif()
if(FOC_ZERO_FAILURE_TRACE AND (NOT ZERO_RETEST_BOOT OR NOT ZERO_MEDIAN_DIAGNOSTIC OR
   NOT FOC_CURRENT_SPIKE_ONLY OR ADC_DMA_RAW_DIAGNOSTIC OR SWITCH_FEEDBACK_DIAGNOSTIC))
    message(FATAL_ERROR "Failure trace requires the standalone output-locked spike zero profile")
endif()
if(FOC_CURRENT_SPIKE_ONLY AND NOT ZERO_RETEST_BOOT AND NOT FOC_ISOLATED_CONCURRENCY AND NOT FOC_PROTECTED_CLOSED_LOOP)
    message(FATAL_ERROR "Isolated-spike filter requires a power-output-locked diagnostic/compute profile")
endif()
if(FOC_CURRENT_SPIKE_ONLY AND SWITCH_FEEDBACK_DIAGNOSTIC)
    message(FATAL_ERROR "Isolated-spike prototype excludes bridge-switching profiles")
endif()
if(FOC_ZERO_MEDIAN_COMPUTE_ONLY AND NOT FOC_ISOLATED_CONCURRENCY)
    message(FATAL_ERROR "Median compute acceptance requires the hard-locked isolated profile")
endif()
option(TIGHTEN_SYNTHETIC_BENCH "Local CPU-only tightening model; isolated firmware ONLY" OFF)
if(TIGHTEN_SYNTHETIC_BENCH AND NOT FOC_ISOLATED_CONCURRENCY)
    message(FATAL_ERROR "Synthetic tightening requires hard-locked isolated firmware")
endif()
option(TIGHTEN_SPEED_X2_OFFLINE "Double rundown defaults/range for output-locked offline experiments ONLY" OFF)
if(TIGHTEN_SPEED_X2_OFFLINE AND (NOT TIGHTEN_SYNTHETIC_BENCH OR NOT FOC_ISOLATED_CONCURRENCY))
    message(FATAL_ERROR "Double-speed experiment requires the hard-locked synthetic profile")
endif()
option(CAN_FD_EXPERIMENT "Opt-in ISO CAN FD on the isolated read-only firmware" OFF)
option(CAN_FD_BIT_RATE_SWITCH "Opt-in 500k/2M BRS; prove FD interoperability first" OFF)
option(CAN_FD_ECHO_ONLY "Isolated FD echo only; suppress background CAN traffic" OFF)
if(CAN_FD_ECHO_ONLY AND NOT CAN_FD_EXPERIMENT)
    message(FATAL_ERROR "CAN_FD_ECHO_ONLY requires CAN_FD_EXPERIMENT")
endif()
if(CAN_FD_BIT_RATE_SWITCH AND NOT CAN_FD_EXPERIMENT)
    message(FATAL_ERROR "CAN FD BRS requires CAN_FD_EXPERIMENT")
endif()
if(CAN_FD_EXPERIMENT AND (NOT CAN_STATUS_TELEMETRY OR NOT FOC_ISOLATED_CONCURRENCY OR CAN_LINK_PROBE_ONLY))
    message(FATAL_ERROR "CAN FD experiment requires the hard-locked isolated firmware")
endif()
if(FOC_ISOLATED_CONCURRENCY AND (NOT FOC_ADC_WINDOW OR NOT ROUTER_READ_ONLY_RPC OR NOT AS5047P_SPI_DMA))
    message(FATAL_ERROR "Isolated concurrency requires the encoder/ADC/read-only Router profile")
endif()
set(FOC_ADC_SENSE_TOPOLOGY "UNCONFIRMED" CACHE STRING "UNCONFIRMED, INLINE or LOW_SIDE_UV; confirm circuit before enabling")
set_property(CACHE FOC_ADC_SENSE_TOPOLOGY PROPERTY STRINGS UNCONFIRMED INLINE LOW_SIDE_UV)
if(FOC_PROTECTED_CLOSED_LOOP AND NOT FOC_ADC_SENSE_TOPOLOGY STREQUAL "LOW_SIDE_UV")
    message(FATAL_ERROR "Genbotter protected motor trial requires LOW_SIDE_UV; no fake INLINE fixture")
endif()
set(FOC_ADC_SETTLE_TICKS "85" CACHE STRING "Provisional analog settling margin at 170MHz; measure before deployment")
option(FOC_ADC_RC_DIAGNOSTIC "Late low-side sampling experiment; power-hard-off ONLY" OFF)
option(FOC_ADC_RC_PROTECTED_CANDIDATE "Separate RC sampling/original FSM candidate; preserve deadline admission and fault closure" OFF)
option(FOC_PWM_BOUNDARY_TRACE "Evidence-only outer ADC IRQ/source timing; RC motion admission disabled" OFF)
option(FOC_PWM_BOUNDARY_LITE "Low-perturbation PWM-boundary snapshots; RC motion admission disabled" OFF)
option(FOC_RC_DEFERRED_SHADOW "Observe one-sample-deferred FOC plans without publishing duty or admitting motion" OFF)
if(FOC_RC_DEFERRED_SHADOW AND NOT FOC_PWM_BOUNDARY_LITE)
    message(FATAL_ERROR "Deferred plan shadow requires the output-locked boundary-lite observer")
endif()
if(FOC_PWM_BOUNDARY_TRACE)
    if(NOT FOC_ADC_RC_PROTECTED_CANDIDATE OR NOT FOC_FEEDBACK_FAST_PATH OR
       NOT FOC_FAST_MATH OR FOC_IRQ_SOURCE_TRACE)
        message(FATAL_ERROR "PWM boundary trace requires RC protected fast candidate and one frame owner")
    endif()
endif()
if(FOC_PWM_BOUNDARY_LITE)
    if(NOT FOC_ADC_RC_PROTECTED_CANDIDATE OR NOT FOC_FEEDBACK_FAST_PATH OR
       NOT FOC_FAST_MATH OR FOC_IRQ_SOURCE_TRACE OR FOC_PWM_BOUNDARY_TRACE)
        message(FATAL_ERROR "PWM boundary lite requires RC protected fast candidate without source trace")
    endif()
endif()
set(FOC_ADC_RC_MIN_LOW_ON_TICKS "1700" CACHE STRING "Provisional RC observation budget, 170MHz ticks; not settled-current qualification")
if(FOC_ADC_RC_DIAGNOSTIC)
    if(NOT FOC_ADC_WINDOW OR NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_ADAPTIVE_FILTER_EXPERIMENT OR
       NOT FOC_IRQ_COMPACT OR FOC_LATEST_ORIGINAL_FSM OR FOC_COMPACT_CLOSED_LOOP OR
       NOT FOC_ADC_SENSE_TOPOLOGY STREQUAL "LOW_SIDE_UV")
        message(FATAL_ERROR "RC sampling diagnostic requires compact protected power-hard-off LOW_SIDE_UV")
    endif()
    if(NOT FOC_ADC_RC_MIN_LOW_ON_TICKS MATCHES "^[0-9]+$" OR
       FOC_ADC_RC_MIN_LOW_ON_TICKS LESS 1700 OR FOC_ADC_RC_MIN_LOW_ON_TICKS GREATER 4249)
        message(FATAL_ERROR "FOC_ADC_RC_MIN_LOW_ON_TICKS must be in 1700..4249")
    endif()
endif()
if(FOC_ADC_RC_PROTECTED_CANDIDATE)
    if(FOC_ADC_RC_DIAGNOSTIC OR FOC_ADAPTIVE_FILTER_EXPERIMENT OR FOC_COMPACT_CLOSED_LOOP OR
       NOT FOC_ADC_WINDOW OR NOT FOC_PROTECTED_CLOSED_LOOP OR NOT FOC_LATEST_ORIGINAL_FSM OR
       NOT FOC_STARTUP_TRACE OR NOT FOC_IRQ_COMPACT OR NOT FOC_GATE_REUSE OR
       NOT FOC_ADC_SENSE_TOPOLOGY STREQUAL "LOW_SIDE_UV")
        message(FATAL_ERROR "RC protected candidate requires full original FSM/trace/deadline protection; no diagnostic bypass")
    endif()
    if(NOT FOC_ADC_RC_MIN_LOW_ON_TICKS MATCHES "^[0-9]+$" OR
       FOC_ADC_RC_MIN_LOW_ON_TICKS LESS 1700 OR FOC_ADC_RC_MIN_LOW_ON_TICKS GREATER 4249)
        message(FATAL_ERROR "RC protected candidate observation must be 1700..4249 ticks")
    endif()
endif()
if(FOC_ADC_WINDOW)
    if(NOT AS5047P_SPI_DMA OR SAFETY_LOCKED_BOOT OR CAN_LINK_PROBE_ONLY)
        message(FATAL_ERROR "FOC ADC window requires the normal encoder-DMA APP")
    endif()
    if(FOC_ADC_SENSE_TOPOLOGY STREQUAL "UNCONFIRMED")
        set(taskSenseId 0)
        if(FOC_ISOLATED_CONCURRENCY)
            # A digital geometry fixture, NOT confirmation of the physical sense circuit.
            set(taskSenseId 1)
        endif()
    elseif(FOC_ADC_SENSE_TOPOLOGY STREQUAL "INLINE")
        set(taskSenseId 1)
    elseif(FOC_ADC_SENSE_TOPOLOGY STREQUAL "LOW_SIDE_UV")
        set(taskSenseId 2)
    else()
        message(FATAL_ERROR "Unknown current-sense topology")
    endif()
    if(NOT FOC_ADC_SETTLE_TICKS MATCHES "^[0-9]+$" OR FOC_ADC_SETTLE_TICKS GREATER 4249)
        message(FATAL_ERROR "FOC_ADC_SETTLE_TICKS must be in 0..4249")
    endif()
endif()
if(AS5047P_SPI_DMA AND (CAN_LINK_PROBE_ONLY OR SAFETY_LOCKED_BOOT))
    message(FATAL_ERROR "Encoder DMA is a normal APP profile only")
endif()
if(ROUTER_READ_ONLY_RPC AND (NOT ROUTER_READ_ONLY_NETWORK OR NOT CAN_RPC_READ_ONLY))
    message(FATAL_ERROR "Router RPC needs the normal Router/CAN read-only profile")
endif()
if(ROUTER_READ_ONLY_NETWORK AND (CAN_LINK_PROBE_ONLY OR SAFETY_LOCKED_BOOT))
    message(FATAL_ERROR "Router network is a normal APP communication profile only")
endif()
if(CAN_RPC_READ_ONLY AND (NOT CAN_STATUS_TELEMETRY OR CAN_LINK_PROBE_ONLY OR
   SAFETY_LOCKED_BOOT OR CAN_SHADOW_DIAG OR NOT CAN_CONTROL_REJECT_ONLY))
    message(FATAL_ERROR "CAN RPC needs normal telemetry, reject-only control, no safety/probe/shadow profile")
endif()
if(ESP_NETWORK_OBSERVER AND (SAFETY_LOCKED_BOOT OR CAN_LINK_PROBE_ONLY))
    message(FATAL_ERROR "Network observations are a normal APP profile only")
endif()
if(SAFETY_LOCKED_BOOT AND (NOT CAN_STATUS_TELEMETRY OR CAN_LINK_PROBE_ONLY OR CAN_LOG_STREAM OR CAN_SHADOW_DIAG))
    message(FATAL_ERROR "SAFETY_LOCKED_BOOT needs telemetry, no link probe/log/shadow traffic")
endif()
if(SAFETY_LOCKED_BOOT AND NOT CAN_CONTROL_REJECT_ONLY)
    message(FATAL_ERROR "SAFETY_LOCKED_BOOT requires fail-closed control replies")
endif()
if(CAN_LOG_STREAM AND (NOT CAN_STATUS_TELEMETRY OR CAN_LINK_PROBE_ONLY))
    message(FATAL_ERROR "CAN_LOG_STREAM requires normal telemetry")
endif()

if(CAN_SHADOW_DIAG AND (NOT CAN_STATUS_TELEMETRY OR CAN_LINK_PROBE_ONLY))
    message(FATAL_ERROR "CAN_SHADOW_DIAG requires normal CAN_STATUS_TELEMETRY")
endif()
if(CAN_CONTROL_REJECT_ONLY AND (NOT CAN_STATUS_TELEMETRY OR CAN_LINK_PROBE_ONLY))
    message(FATAL_ERROR "CAN_CONTROL_REJECT_ONLY requires normal CAN_STATUS_TELEMETRY")
endif()

add_executable(${CMAKE_PROJECT_NAME})
if(FOC_MOTOR_IDENTIFICATION_DIAG)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_MOTOR_IDENTIFICATION_DIAG=1)
endif()
if(FOC_IDENT_CURRENT_REJECT_ENABLE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_IDENT_CURRENT_REJECT_ENABLE=1)
endif()
if(FOC_IDENT_TIMING_TRACE_ENABLE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_IDENT_TIMING_TRACE_ENABLE=1)
endif()
if(FOC_IDENT_RS_GAP_ADMISSION_ENABLE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_IDENT_RS_GAP_ADMISSION_ENABLE=1)
endif()
if(FOC_IDENT_RS_GAP_COUNT_ONLY)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_IDENT_RS_GAP_COUNT_ONLY=1)
endif()
if(FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT=1)
endif()
if(FOC_IDENT_RS_REJECT_COUNT_ONLY)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_IDENT_RS_REJECT_COUNT_ONLY=1)
endif()
if(FOC_IDENT_L_RS_ADMISSION_ENABLE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_IDENT_L_RS_ADMISSION_ENABLE=1)
endif()
if(FOC_IDENT_VOLTAGE_STEP_DIAG)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_IDENT_VOLTAGE_STEP_DIAG=1)
endif()
if(NOT FOC_IDENT_RS_SOFT_DT_MAX_US STREQUAL "55")
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE MID_RS_SOFT_DT_MAX_US=${FOC_IDENT_RS_SOFT_DT_MAX_US}U)
endif()
if(NOT FOC_IDENT_TRAVEL_EXIT_ENABLE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE MID_TRAVEL_EXIT_ENABLE=0)
endif()
if(FOC_FRICTION_CALIBRATION_DIAG)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_FRICTION_CALIBRATION_DIAG=1)
endif()
if(FOC_FRICTION_HIGH_SPEED_GRID)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_FRICTION_HIGH_SPEED_GRID=1)
endif()
if(FOC_SPEED_FRICTION_CANDIDATE)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../firmware_common/speed_friction_compensation.c
        ../firmware_common/speed_friction_compensation_log.cc)
    set_source_files_properties(../firmware_common/speed_friction_compensation.c
        ../firmware_common/speed_friction_compensation_log.cc PROPERTIES COMPILE_OPTIONS "-Os")
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_SPEED_FRICTION_CANDIDATE=1
        FOC_FRICTION_ENABLED_DEFAULT=$<BOOL:${FOC_FRICTION_ENABLED_DEFAULT}>
        SPEED_FRICTION_I_A=${FOC_FRICTION_I_A}f
        SPEED_FRICTION_DEADBAND_RPM=${FOC_FRICTION_DEADBAND_RPM}f)
endif()
if(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../firmware_common/speed_accel_feedforward.c
        ../firmware_common/speed_accel_feedforward_log.cc)
    set_source_files_properties(../firmware_common/speed_accel_feedforward.c
        ../firmware_common/speed_accel_feedforward_log.cc PROPERTIES COMPILE_OPTIONS "-Os")
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_ACCEL_FEEDFORWARD_CANDIDATE=1
        FOC_ACCEL_FF_ENABLED_DEFAULT=$<BOOL:${FOC_ACCEL_FF_ENABLED_DEFAULT}>
        SPEED_ACCEL_FF_KA_A_PER_RPM_S=${FOC_ACCEL_FF_KA_A_PER_RPM_S}f)
    if(FOC_ACCEL_FF_AUDIT)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/speed_accel_audit.c
            ../firmware_common/speed_accel_audit_log.cc)
        set_source_files_properties(../firmware_common/speed_accel_audit.c
            ../firmware_common/speed_accel_audit_log.cc PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_ACCEL_FF_AUDIT=1)
    endif()
    if(FOC_KA_IDENT_DIAG)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/ka_identification.c
            ../firmware_common/ka_identification_log.cc)
        set_source_files_properties(../firmware_common/ka_identification.c
            ../firmware_common/ka_identification_log.cc PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_KA_IDENT_DIAG=1)
    endif()
    if(FOC_KA_FULL_DIAG)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/ka_full_diagnostic.c)
        set_source_files_properties(../firmware_common/ka_full_diagnostic.c PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_KA_FULL_DIAG=1)
    endif()
    if(FOC_MECHANICAL_IDENT_DIAG)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/mechanical_identification.c)
        set_source_files_properties(../firmware_common/mechanical_identification.c PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_MECHANICAL_IDENT_DIAG=1)
    endif()
    if(FOC_MECHANICAL_MOTION_DIAG)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_MECHANICAL_MOTION_DIAG=1)
    endif()
    if(FOC_MECHANICAL_HIGH_SPEED_DIAG)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_MECHANICAL_HIGH_SPEED_DIAG=1)
    endif()
    if(FOC_ENCODER_CONTROL_ADMISSION_FIX)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_ENCODER_CONTROL_ADMISSION_FIX=1)
    endif()
    if(FOC_OUTER_OBSERVE_AFTER_ACK)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_OUTER_OBSERVE_AFTER_ACK=1)
    endif()
    if(FOC_READY_TIMESTAMP_SNAPSHOT)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_READY_TIMESTAMP_SNAPSHOT=1)
    endif()
    if(FOC_MECHANICAL_REVERSE_IDENT_DIAG)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_MECHANICAL_REVERSE_IDENT_DIAG=1)
    endif()
    if(FOC_DOB_SHORT_LOW_RECOVERY)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_SHORT_LOW_RECOVERY=1)
        if(FOC_DOB_LOW_AUDIT)
            target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_LOW_AUDIT=1)
            target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/dob_low_recovery_audit.c)
            set_source_files_properties(../firmware_common/dob_low_recovery_audit.c PROPERTIES COMPILE_OPTIONS "-Os")
        endif()
    endif()
    if(FOC_MECHANICAL_DOB_SHADOW)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/mechanical_dob_monitor.c)
        set_source_files_properties(../firmware_common/mechanical_dob_monitor.c PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_MECHANICAL_DOB_SHADOW=1)
    endif()
    if(FOC_ID_STEADY_STATS)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/id_steady_stats.c)
        set_source_files_properties(../firmware_common/id_steady_stats.c PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_ID_STEADY_STATS=1)
    endif()
    if(FOC_DOB_ID_TRACE)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/dob_id_trace.c)
        set_source_files_properties(../firmware_common/dob_id_trace.c PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_ID_TRACE=1)
    endif()
    if(FOC_DOB_TREND_SHADOW)
        if(FOC_DOB_LOAD_SPEED)
            target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/dob_load_speed_candidate.c)
            set_source_files_properties(../firmware_common/dob_load_speed_candidate.c PROPERTIES COMPILE_OPTIONS "-Os")
            target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_LOAD_SPEED=1)
            if(FOC_DOB_LOAD_SPEED_CONTACT_HOLD)
                target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_LOAD_SPEED_CONTACT_HOLD=1)
            endif()
        endif()
        if(FOC_DOB_RECOVERY_TIMING)
            target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/dob_recovery_timing.c)
            set_source_files_properties(../firmware_common/dob_recovery_timing.c PROPERTIES COMPILE_OPTIONS "-Os")
            target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_RECOVERY_TIMING=1)
        endif()
        if(FOC_DOB_TREND_WINDOW75)
            target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_TREND_WINDOW75=1)
        endif()
        if(FOC_DOB_SATURATION_CONTINUE)
            target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_SATURATION_CONTINUE=1)
        endif()
        if(FOC_DOB_WARMUP_AB)
            target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_WARMUP_AB=1
                DOB_WARMUP_DEFAULT_TAU=${FOC_DOB_WARMUP_DEFAULT_TAU}U)
        endif()
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/dob_trend_shadow.c)
        set_source_files_properties(../firmware_common/dob_trend_shadow.c PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_TREND_SHADOW=1)
        if(FOC_DOB_TREND_CONTINUOUS)
            target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/dob_trend_continuous.c)
            set_source_files_properties(../firmware_common/dob_trend_continuous.c PROPERTIES COMPILE_OPTIONS "-Os")
            target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_TREND_CONTINUOUS=1)
        endif()
    endif()
    if(FOC_DOB_REAL_TRACE)
        if(FOC_DOB_GAIN_AB_DIAG)
            target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_GAIN_AB_DIAG=1)
        endif()
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/dob_real_trace.c)
        set_source_files_properties(../firmware_common/dob_real_trace.c PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_REAL_TRACE=1)
    endif()
    if(FOC_DOB_SPIKE_ADMISSION)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_SPIKE_ADMISSION=1)
    endif()
    if(FOC_DOB_ADMISSION_START_GUARD)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_ADMISSION_START_GUARD=1)
    endif()
    if(FOC_DOB_DIRECT_JUMP_REJECT)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_DIRECT_JUMP_REJECT=1)
    endif()
    if(FOC_DOB_RECOVERABLE_ADMISSION)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_RECOVERABLE_ADMISSION=1)
    endif()
    if(FOC_DOB_PERSISTENT_QUALITY)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_PERSISTENT_QUALITY=1)
    endif()
    if(FOC_DOB_ID_PRE_LPF_QUALITY)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_ID_PRE_LPF_QUALITY=1)
    endif()
    if(FOC_DOB_PRE_LPF_JUMP_200MA)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE DOB_ADMIT_JUMP_A=.200f)
    endif()
    if(FOC_DOB_FEEDBACK_CANDIDATE)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_FEEDBACK_CANDIDATE=1)
    endif()
    if(FOC_DOB_NORMAL_CONTROL)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_NORMAL_CONTROL=1 DOB_FB_GAIN=0.25f)
    endif()
    if(FOC_DOB_CONTACT20_OBSERVE10)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_DOB_CONTACT20_OBSERVE10=1)
    endif()
    if(FOC_DOB_FB_GAIN_ONE)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE DOB_FB_GAIN=1.0f)
    endif()
    if(FOC_DOB_FB_GAIN_HALF)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE DOB_FB_GAIN=0.5f)
    endif()
    if(FOC_DOB_FB_GAIN_015)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE DOB_FB_GAIN=0.15f)
    endif()
    if(FOC_KA_SYNC_DIAG)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/ka_sync_diagnostic.c)
        set_source_files_properties(../firmware_common/ka_sync_diagnostic.c PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_KA_SYNC_DIAG=1
            KA_SYNC_START_US=${FOC_KA_SYNC_START_US}U)
    endif()
    if(FOC_STARTUP_TIMESTAMPS_DIAG)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/startup_timestamps.c
            ../firmware_common/startup_timestamps_log.cc)
        set_source_files_properties(../firmware_common/startup_timestamps.c
            ../firmware_common/startup_timestamps_log.cc PROPERTIES COMPILE_OPTIONS "-Os")
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_STARTUP_TIMESTAMPS_DIAG=1)
    endif()
endif()
if(FOC_SPEED_SCURVE_CANDIDATE)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/speed_scurve.c)
    set_source_files_properties(../firmware_common/speed_scurve.c PROPERTIES COMPILE_OPTIONS "-Os")
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_SPEED_SCURVE_CANDIDATE=1)
endif()
if(FOC_PWM_COMMON_MODE_ENABLE)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_pwm_common_mode.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_PWM_COMMON_MODE_ENABLE=1)
endif()
if(FOC_INTENT_FSM_CANDIDATE)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/tightening_intent_fsm.c)
    set_source_files_properties(../firmware_common/tightening_intent_fsm.c PROPERTIES COMPILE_OPTIONS "-Oz")
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE FOC_INTENT_FSM_CANDIDATE=1)
endif()
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    ../firmware_common/tighten_params.cpp
    ../firmware_common/tighten_params_storage.cpp
    ../firmware_common/uart_tx_pool.c
    ../firmware_common/uart_rx_cursor.c
    ../firmware_common/uart_line_parser.c)
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common)
if(FOC_CURRENT_STEP_AB_DIAG)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/current_step_ab.c)
    set_source_files_properties(../firmware_common/current_step_ab.c PROPERTIES COMPILE_OPTIONS "-Os")
endif()
add_subdirectory(cmake/stm32cubemx)
if(FOC_PSI_IDENT_DIAG)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/psi_ke_identification.c
        ../firmware_common/psi_ke_identification_log.cc)
    set_source_files_properties(../firmware_common/psi_ke_identification.c
        ../firmware_common/psi_ke_identification_log.cc PROPERTIES COMPILE_OPTIONS "-Os")
    target_compile_definitions(stm32cubemx INTERFACE FOC_PSI_IDENT_DIAG=1)
    if(FOC_PSI_IDENT_TRIP500)
        target_compile_definitions(stm32cubemx INTERFACE FOC_PSI_IDENT_TRIP500=1)
    endif()
    if(FOC_PSI_IDENT_API400)
        target_compile_definitions(stm32cubemx INTERFACE FOC_PSI_IDENT_API400=1)
    endif()
endif()
if(FOC_DQ_AUDIT_ENABLE)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_dq_audit.c
        ../firmware_common/foc_dq_audit_log.cc)
    set_source_files_properties(../firmware_common/foc_dq_audit.c
        ../firmware_common/foc_dq_audit_log.cc PROPERTIES COMPILE_OPTIONS "-Os")
    target_compile_definitions(stm32cubemx INTERFACE FOC_DQ_AUDIT_ENABLE=1
        DECOUPLING_SIGN_TEST=$<BOOL:${DECOUPLING_SIGN_TEST}> DECOUPLING_SIGN_MODE=${DECOUPLING_SIGN_MODE})
endif()
if(FOC_OUTPUT_GATE_EVIDENCE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_OUTPUT_GATE_EVIDENCE=1)
endif()
if(FOC_CURRENT_STEP_IDENT_POLICY)
    target_compile_definitions(stm32cubemx INTERFACE FOC_CURRENT_STEP_IDENT_POLICY=1)
endif()
if(FOC_CURRENT_STEP_AB_DIAG)
    target_compile_definitions(stm32cubemx INTERFACE FOC_CURRENT_STEP_AB_DIAG=1)
endif()
if(FOC_CURRENT_PI_IDENTIFIED_ENABLE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_CURRENT_PI_IDENTIFIED_ENABLE=1
        CURRENT_PI_CANDIDATE_BANDWIDTH_HZ=${CURRENT_PI_CANDIDATE_BANDWIDTH_HZ}f)
endif()
if(FOC_DQ_DECOUPLING_CANDIDATE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_DQ_DECOUPLING_CANDIDATE=1
        FOC_DQ_DECOUPLING_ENABLED_DEFAULT=$<BOOL:${FOC_DQ_DECOUPLING_ENABLED_DEFAULT}>
        FOC_DQ_LD_H=${FOC_DQ_LD_H}f FOC_DQ_LQ_H=${FOC_DQ_LQ_H}f)
endif()
if(FOC_BEMF_CANDIDATE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_BEMF_CANDIDATE=1
        FOC_BEMF_ENABLED_DEFAULT=$<BOOL:${FOC_BEMF_ENABLED_DEFAULT}>
        FOC_BEMF_PSI_WB=${FOC_BEMF_PSI_LITERAL}f)
endif()
if(FOC_BEMF_GAIN_DIAG)
    target_compile_definitions(stm32cubemx INTERFACE FOC_BEMF_GAIN_DIAG=1)
endif()
target_compile_definitions(stm32cubemx INTERFACE FOC_CURRENT_FAULT_TRACE_ENABLE=$<BOOL:${FOC_CURRENT_FAULT_TRACE_ENABLE}>)
target_compile_definitions(stm32cubemx INTERFACE FOC_CURRENT_FEEDBACK_SIGN=${FOC_CURRENT_FEEDBACK_SIGN})
if(FOC_RUNDOWN240_CANDIDATE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_RUNDOWN240_CANDIDATE=1)
endif()
if(FOC_NORMAL_RUN_TRIP500)
    target_compile_definitions(stm32cubemx INTERFACE FOC_NORMAL_RUN_TRIP500=1)
endif()
if(FOC_RUNDOWN240_TRAVEL20000)
    target_compile_definitions(stm32cubemx INTERFACE FOC_RUNDOWN240_TRAVEL20000=1)
endif()
if(FOC_ADC_COUNTS_100_40_CANDIDATE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_ADC_COUNTS_100_40_CANDIDATE=1
        FOC_CURRENT_JUMP_THRESHOLD_COUNTS=100U FOC_CURRENT_RETURN_TOL_COUNTS=40U)
endif()
if(FOC_SPEED_PI_ANTI_WINDUP)
    target_compile_definitions(stm32cubemx INTERFACE FOC_SPEED_PI_ANTI_WINDUP=1)
endif()
if(FOC_SPEED_SB3_DISABLE_CANDIDATE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_SPEED_SB3_DISABLE_CANDIDATE=1)
endif()
if(FOC_SPEED_LEGACY_AW_COMPARE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_SPEED_LEGACY_AW_COMPARE=1)
endif()
if(FOC_CURRENT_FAULT_TRACE_ENABLE)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_current_fault_trace.c)
    set_source_files_properties(../firmware_common/foc_current_fault_trace.c PROPERTIES COMPILE_OPTIONS "-Os")
endif()
if(FOC_PREEMPT_COMMIT_PROBE)
    if(AS5047P_DMA_FOC_FIRST)
        target_compile_definitions(stm32cubemx INTERFACE AS5047P_DMA_FOC_FIRST=1)
    endif()
    if(AS5047P_DMA_TERMINAL_FIX)
        target_compile_definitions(stm32cubemx INTERFACE AS5047P_DMA_TERMINAL_FIX=1)
    endif()
    if(AS5047P_DMA_TIMING_POLICY_V2)
        target_compile_definitions(stm32cubemx INTERFACE AS5047P_DMA_TIMING_POLICY_V2=1 AS_DMA_TRANSACTION_US=400U)
    endif()
    target_compile_definitions(stm32cubemx INTERFACE FOC_PREEMPT_COMMIT_PROBE=1)
    if(FOC_PWM_PIPELINE_CLOSED_LOOP)
        target_compile_definitions(stm32cubemx INTERFACE FOC_PWM_PIPELINE_CLOSED_LOOP=1)
    endif()
    if(FOC_LOADED_FSM_TRIAL)
        target_compile_definitions(stm32cubemx INTERFACE FOC_LOADED_FSM_TRIAL=1)
    endif()
    if(FOC_SPEED_STARTUP_BRAKE)
        target_compile_definitions(stm32cubemx INTERFACE FOC_SPEED_STARTUP_BRAKE=1)
    endif()
    if(FOC_SPEED_BUMPLESS)
        target_compile_definitions(stm32cubemx INTERFACE FOC_SPEED_BUMPLESS=1)
    endif()
    if(FOC_VOLTAGE_X2_TRIAL)
        target_compile_definitions(stm32cubemx INTERFACE FOC_VOLTAGE_X2_TRIAL=1)
    endif()
    if(FOC_SPEED_BRAKE_TRACK)
        target_compile_definitions(stm32cubemx INTERFACE FOC_SPEED_BRAKE_TRACK=1)
    endif()
    if(FOC_ZERO_VALID_ADMISSION)
        target_compile_definitions(stm32cubemx INTERFACE FOC_ZERO_VALID_ADMISSION=1)
    endif()
    target_compile_definitions(stm32cubemx INTERFACE FOC_HEAVY_PROFILE_ENABLE=$<BOOL:${FOC_HEAVY_PROFILE_ENABLE}>)
    if(FOC_ONE_CYCLE_PWM_PIPELINE)
        target_compile_definitions(stm32cubemx INTERFACE FOC_ONE_CYCLE_PWM_PIPELINE=1)
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_preempt_probe_stm32.c)
    set_source_files_properties(../firmware_common/foc_preempt_probe_stm32.c PROPERTIES COMPILE_OPTIONS "-Os")
endif()
include(../firmware_common/original_closed_loop_updated.cmake)
if(TIGHTEN_SPEED_X2_OFFLINE)
    target_compile_definitions(stm32cubemx INTERFACE TIGHTEN_SPEED_X2_OFFLINE=1)
endif()
if(ZERO_RETEST_BOOT)
    if(SAFETY_LOCKED_BOOT OR CAN_LINK_PROBE_ONLY OR FOC_ISOLATED_CONCURRENCY OR
       AS5047P_SPI_DMA OR FOC_ADC_WINDOW OR CAN_RPC_READ_ONLY OR ROUTER_READ_ONLY_NETWORK)
        message(FATAL_ERROR "ZERO_RETEST_BOOT is a standalone, non-actuating service profile")
    endif()
    target_compile_definitions(stm32cubemx INTERFACE ZERO_RETEST_BOOT=1)
    if(FOC_OC_LAYERED_SELFTEST)
        target_compile_definitions(stm32cubemx INTERFACE FOC_OC_LAYERED_SELFTEST=1)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_protection_selftest.c)
    endif()
    if(SWITCH_FEEDBACK_DIAGNOSTIC)
        target_compile_definitions(stm32cubemx INTERFACE SWITCH_FEEDBACK_DIAGNOSTIC=1)
        if(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
            target_compile_definitions(stm32cubemx INTERFACE SWITCH_FILTERED_BRIDGE_DIAGNOSTIC=1)
        endif()
        if(SWITCH_SIGNAL_ONLY_DIAGNOSTIC)
            target_compile_definitions(stm32cubemx INTERFACE SWITCH_SIGNAL_ONLY_DIAGNOSTIC=1)
        endif()
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_current_zero.c)
    if(ZERO_MEDIAN_DIAGNOSTIC)
        target_compile_definitions(stm32cubemx INTERFACE ZERO_MEDIAN_DIAGNOSTIC=1)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_zero_median.c)
    endif()
    if(ADC_DMA_RAW_DIAGNOSTIC)
        target_compile_definitions(stm32cubemx INTERFACE ADC_DMA_RAW_DIAGNOSTIC=1)
        if(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
            target_compile_definitions(stm32cubemx INTERFACE ADC_DMA_THREE_PHASE_DIAGNOSTIC=1)
        endif()
        if(ADC_DMA_PARALLEL_DIAGNOSTIC)
            target_compile_definitions(stm32cubemx INTERFACE ADC_DMA_PARALLEL_DIAGNOSTIC=1)
            if(ADC_DMA_PARALLEL_LONG_SAMPLE)
                target_compile_definitions(stm32cubemx INTERFACE ADC_DMA_PARALLEL_LONG_SAMPLE=1)
            endif()
            if(ADC_DMA_PA1_ONLY_DIAGNOSTIC)
                target_compile_definitions(stm32cubemx INTERFACE ADC_DMA_PA1_ONLY_DIAGNOSTIC=1)
            endif()
            if(ADC_DMA_ADC12_ONLY_DIAGNOSTIC)
                target_compile_definitions(stm32cubemx INTERFACE ADC_DMA_ADC12_ONLY_DIAGNOSTIC=1)
            endif()
            if(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
                target_compile_definitions(stm32cubemx INTERFACE ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC=1)
            endif()
            if(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
                target_compile_definitions(stm32cubemx INTERFACE ADC_CONTROL_PINS_LOW_DIAGNOSTIC=1)
            endif()
            if(ADC_DMA_REFERENCE_DOUBLE_CAPTURE)
                target_compile_definitions(stm32cubemx INTERFACE ADC_DMA_REFERENCE_DOUBLE_CAPTURE=1)
            endif()
            target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/adc_parallel_diag.c)
        else()
            target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/adc_dma_diag.c)
        endif()
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/adc_raw_report.c)
    endif()
endif()
if(TIGHTEN_SYNTHETIC_BENCH)
    target_compile_definitions(stm32cubemx INTERFACE TIGHTEN_SYNTHETIC_BENCH=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/tighten_synthetic_bench.cpp)
endif()
if(CAN_FD_EXPERIMENT)
    target_compile_definitions(stm32cubemx INTERFACE CAN_WIRE_FD_ENABLED=1)
    if(CAN_FD_ECHO_ONLY)
        target_compile_definitions(stm32cubemx INTERFACE CAN_WIRE_FD_ECHO_ONLY=1)
    endif()
    if(CAN_FD_BIT_RATE_SWITCH)
        target_compile_definitions(stm32cubemx INTERFACE CAN_WIRE_BRS_ENABLED=1)
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/can_fd_probe.c)
endif()
if(FOC_ISOLATED_CONCURRENCY)
    if(NOT ROUTER_READ_ONLY_TRANSFER OR NOT FOC_ADC_SENSE_TOPOLOGY STREQUAL "UNCONFIRMED")
        message(FATAL_ERROR "Isolated fixture requires Transfer and unconfirmed hardware topology")
    endif()
    target_compile_definitions(stm32cubemx INTERFACE FOC_ISOLATED_CONCURRENCY=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_current_zero.c)
endif()
if(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE FOC_ZERO_MEDIAN_COMPUTE_ONLY=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_zero_median.c)
endif()
if(FOC_CURRENT_SPIKE_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE FOC_CURRENT_SPIKE_ONLY=1)
endif()
if(FOC_CURRENT_TREND4)
    target_compile_definitions(stm32cubemx INTERFACE FOC_CURRENT_TREND4=1)
endif()
if(FOC_RAW_OBSERVE_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE FOC_RAW_OBSERVE_ONLY=1)
endif()
if(FOC_FILTERED_OBSERVE_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE FOC_FILTERED_OBSERVE_ONLY=1)
endif()
if(FOC_ZERO_FAILURE_TRACE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_ZERO_FAILURE_TRACE=1)
endif()
if(FOC_FEEDBACK_SAFETY_BINDING)
    target_compile_definitions(stm32cubemx INTERFACE FOC_FEEDBACK_SAFETY_BINDING=1)
endif()
if(FOC_CONTROL_CHAIN_RECONNECT)
    target_compile_definitions(stm32cubemx INTERFACE FOC_CONTROL_CHAIN_RECONNECT=1)
endif()
if(FOC_PROTECTED_CLOSED_LOOP)
    target_compile_definitions(stm32cubemx INTERFACE FOC_PROTECTED_CLOSED_LOOP=1)
    if(FOC_ENABLE_LEGACY_CURRENT_REPAIR)
        target_compile_definitions(stm32cubemx INTERFACE FOC_ENABLE_LEGACY_CURRENT_REPAIR=1)
    else()
        target_compile_definitions(stm32cubemx INTERFACE FOC_FAST_CURRENT_REJECT=1 FOC_ENABLE_LEGACY_CURRENT_REPAIR=0)
    endif()
    if(FOC_FAST_REJECT_COMPUTE_ONLY)
        target_compile_definitions(stm32cubemx INTERFACE FOC_FAST_REJECT_COMPUTE_ONLY=1)
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_current_zero.c ../firmware_common/foc_zero_median.c)
endif()
if(FOC_FAST_MATH)
    target_compile_definitions(stm32cubemx INTERFACE FOC_FAST_MATH=1)
    if(FOC_FAST_PATH_PROFILE)
        target_compile_definitions(stm32cubemx INTERFACE FOC_FAST_PATH_PROFILE=1)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_fast_path_profile_stm32.c)
        set_source_files_properties(../firmware_common/foc_fast_path_profile_stm32.c PROPERTIES COMPILE_OPTIONS "-O2")
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_fast_trig.c ../firmware_common/foc_irq_load_stm32.c)
    set_source_files_properties(../firmware_common/foc_fast_trig.c ../firmware_common/foc_irq_load_stm32.c PROPERTIES COMPILE_OPTIONS "-O2")
endif()
if(FOC_PAIR_FAST_PATH)
    target_compile_definitions(stm32cubemx INTERFACE FOC_PAIR_FAST_PATH=1)
    # Optimize bounded ADC/raw-buffer and encoder state-machine code only.
    # main.c stays -Os except explicitly marked control/guardian functions.
    # Do not enable fast-math or change ISR priorities/deadlines.
    set_source_files_properties(
        ../firmware_common/foc_adc_timing_stm32.c
        ../firmware_common/foc_adc_raw_buffer.c
        ../firmware_common/as5047p_dma_engine.c
        ../firmware_common/as5047p_dma_stm32.c
        PROPERTIES COMPILE_OPTIONS "-O2")
endif()
if(FOC_GUARD_FAST_PATH)
    target_compile_definitions(stm32cubemx INTERFACE FOC_GUARD_FAST_PATH=1)
endif()
if(FOC_FEEDBACK_FAST_PATH)
    target_compile_definitions(stm32cubemx INTERFACE FOC_FEEDBACK_FAST_PATH=1)
endif()
if(FOC_GATE_REUSE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_GATE_REUSE=1)
endif()
if(FOC_IRQ_SOURCE_TRACE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_IRQ_SOURCE_TRACE=1)
    set_source_files_properties(../firmware_common/foc_irq_load_stm32.c PROPERTIES COMPILE_OPTIONS "-O2")
endif()
if(FOC_PWM_BOUNDARY_TRACE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_PWM_BOUNDARY_TRACE=1)
    set_source_files_properties(../firmware_common/foc_irq_load_stm32.c PROPERTIES COMPILE_OPTIONS "-O2")
endif()
if(FOC_PWM_BOUNDARY_LITE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_PWM_BOUNDARY_LITE=1)
endif()
if(FOC_RC_DEFERRED_SHADOW)
    target_compile_definitions(stm32cubemx INTERFACE FOC_RC_DEFERRED_SHADOW=1)
endif()
if(FOC_LATEST_ORIGINAL_FSM)
    target_compile_definitions(stm32cubemx INTERFACE FOC_LATEST_ORIGINAL_FSM=1)
endif()
if(FOC_LATEST_ZERO_COUNT_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE FOC_LATEST_ZERO_COUNT_ONLY=1)
endif()
if(FOC_STARTUP_TRACE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_STARTUP_TRACE=1)
endif()
if(FOC_RUNDOWN_DIAGNOSTIC)
    target_compile_definitions(stm32cubemx INTERFACE FOC_RUNDOWN_DIAGNOSTIC=1)
endif()
if(FOC_TORQUE_CHAIN_DIAG)
    target_compile_definitions(stm32cubemx INTERFACE FOC_TORQUE_CHAIN_DIAG=1 FOC_TORQUE_CHAIN_IQ_MA=${FOC_TORQUE_CHAIN_IQ_MA})
endif()
if(FOC_SPEED_DYNAMIC_DIAG)
    target_compile_definitions(stm32cubemx INTERFACE FOC_SPEED_DYNAMIC_DIAG=1)
endif()
if(FOC_TORQUE350_FIVE_SECOND)
    target_compile_definitions(stm32cubemx INTERFACE FOC_TORQUE350_FIVE_SECOND=1 MOTOR_DIRECT_IQ_LIMIT_A=0.35f)
endif()
if(FOC_TORQUE450_FIVE_SECOND)
    target_compile_definitions(stm32cubemx INTERFACE FOC_TORQUE450_FIVE_SECOND=1 MOTOR_DIRECT_IQ_LIMIT_A=0.45f)
endif()
if(FOC_TORQUE450_150RPM)
    target_compile_definitions(stm32cubemx INTERFACE FOC_TORQUE450_150RPM=1)
endif()
if(FOC_ANGLE_CHAIN_DIAG)
    target_compile_definitions(stm32cubemx INTERFACE FOC_ANGLE_CHAIN_DIAG=1)
    if(FOC_ANGLE_HAND_ONLY)
        target_compile_definitions(stm32cubemx INTERFACE FOC_ANGLE_HAND_ONLY=1)
    else()
        target_compile_definitions(stm32cubemx INTERFACE MOTOR_DIRECT_IQ_LIMIT_A=0.35f)
    endif()
endif()
if(FOC_BREAKAWAY_CURRENT_TEST)
    target_compile_definitions(stm32cubemx INTERFACE FOC_BREAKAWAY_CURRENT_TEST=1)
endif()
if(FOC_BREAKAWAY_FIVE_SECOND)
    target_compile_definitions(stm32cubemx INTERFACE FOC_BREAKAWAY_FIVE_SECOND=1)
endif()
if(FOC_ADAPTIVE_FILTER_EXPERIMENT OR FOC_LATEST_ORIGINAL_FSM)
    if(FOC_ADAPTIVE_FILTER_EXPERIMENT)
        target_compile_definitions(stm32cubemx INTERFACE FOC_ADAPTIVE_FILTER_EXPERIMENT=1)
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_zero_robust.c)
    if(FOC_ZERO_VALID_ADMISSION)
        set_source_files_properties(../firmware_common/foc_zero_robust.c PROPERTIES COMPILE_OPTIONS "-Os")
    else()
        set_source_files_properties(../firmware_common/foc_zero_robust.c PROPERTIES COMPILE_OPTIONS "-O2")
    endif()
endif()
if(FOC_ZERO_TOTAL_BUDGET_OFF)
    target_compile_definitions(stm32cubemx INTERFACE FOC_ZERO_TOTAL_BUDGET_OFF=1)
endif()
if(FOC_ZERO_ALL_REJECTED_DIAG)
    target_compile_definitions(stm32cubemx INTERFACE FOC_ZERO_ALL_REJECTED_DIAG=1)
endif()
if(FOC_RAM_HOT_PATH)
    target_compile_definitions(stm32cubemx INTERFACE FOC_RAM_HOT_PATH=1)
endif()
if(FOC_IRQ_COMPACT)
    target_compile_definitions(stm32cubemx INTERFACE FOC_IRQ_COMPACT=1)
endif()
if(FOC_REPAIR_WINDOW_TRACE)
    target_compile_definitions(stm32cubemx INTERFACE FOC_REPAIR_WINDOW_TRACE=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/foc_repair_trace.c)
    set_source_files_properties(../firmware_common/foc_repair_trace.c PROPERTIES COMPILE_OPTIONS "-Os")
endif()
if(FOC_COMPACT_CLOSED_LOOP)
    target_compile_definitions(stm32cubemx INTERFACE FOC_COMPACT_CLOSED_LOOP=1)
endif()
if(FOC_ADC_WINDOW)
    target_compile_definitions(stm32cubemx INTERFACE FOC_ADC_WINDOW=1
        FOC_ADC_SENSE_TOPOLOGY=${taskSenseId} FOC_ADC_SETTLE_TICKS=${FOC_ADC_SETTLE_TICKS})
    if(FOC_ADC_RC_DIAGNOSTIC)
        target_compile_definitions(stm32cubemx INTERFACE FOC_ADC_RC_DIAGNOSTIC=1
            FOC_ADC_RC_MIN_LOW_ON_TICKS=${FOC_ADC_RC_MIN_LOW_ON_TICKS})
    endif()
    if(FOC_ADC_RC_PROTECTED_CANDIDATE)
        target_compile_definitions(stm32cubemx INTERFACE FOC_ADC_RC_PROTECTED_CANDIDATE=1
            FOC_ADC_RC_MIN_LOW_ON_TICKS=${FOC_ADC_RC_MIN_LOW_ON_TICKS})
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../firmware_common/foc_adc_window.c ../firmware_common/foc_adc_timing_stm32.c
        ../firmware_common/foc_adc_raw_buffer.c ../firmware_common/foc_adc_statistics_task.c)
endif()
if(AS5047P_SPI_DMA)
    target_compile_definitions(stm32cubemx INTERFACE AS5047P_SPI_DMA=1)
    if(AS5047P_DMA_IRQ_PREEMPT_ADC)
        target_compile_definitions(stm32cubemx INTERFACE AS5047P_DMA_IRQ_PREEMPT_ADC=1)
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/as5047p_dma_stm32.c)
    if(AS5047P_DMA_FOC_FIRST)
        set_source_files_properties(../firmware_common/as5047p_dma_stm32.c PROPERTIES COMPILE_OPTIONS "-Os")
    endif()
    if(NOT FOC_IRQ_COMPACT)
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/as5047p_dma_engine.c)
    endif()
endif()
if(ROUTER_READ_ONLY_NETWORK)
    target_compile_definitions(stm32cubemx INTERFACE ROUTER_READ_ONLY_NETWORK=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/router_network.c)
    set_source_files_properties(../firmware_common/router_network.c PROPERTIES COMPILE_OPTIONS "-Os")
endif()
if(CAN_RPC_READ_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE CAN_RPC_READ_ONLY=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/can_rpc_transport.c
        ../firmware_common/pw_can_rpc.c)
endif()
if(CAN_MOTOR_CONTROL_SERVICE)
    target_compile_definitions(stm32cubemx INTERFACE CAN_MOTOR_CONTROL_SERVICE=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/motor_control.c)
endif()

option(ROUTER_READ_ONLY_TRANSFER "Generic Router binary transport, read-only Transfer endpoint" OFF)
if(ROUTER_READ_ONLY_TRANSFER AND NOT ROUTER_READ_ONLY_RPC)
    message(FATAL_ERROR "Router Transfer requires the normal read-only Router RPC profile")
endif()
if(ROUTER_READ_ONLY_TRANSFER)
    target_compile_definitions(stm32cubemx INTERFACE ROUTER_READ_ONLY_TRANSFER=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/router_transfer_wire.c
        ../firmware_common/pw_router_transfer.cc)
    set_source_files_properties(../firmware_common/router_transfer_wire.c
        ../firmware_common/pw_router_transfer.cc PROPERTIES COMPILE_OPTIONS "-Os")
endif()
if(ROUTER_READ_ONLY_RPC)
    target_compile_definitions(stm32cubemx INTERFACE ROUTER_READ_ONLY_RPC=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/router_rpc_wire.c
        ../firmware_common/pw_router_rpc.cc)
    set_source_files_properties(../firmware_common/router_rpc_wire.c ../firmware_common/pw_router_rpc.cc
        PROPERTIES COMPILE_OPTIONS "-Os")
endif()
target_compile_definitions(stm32cubemx INTERFACE UART_LOG_BAUD=${UART_LOG_BAUD})
if(ESP_NETWORK_OBSERVER)
    target_compile_definitions(stm32cubemx INTERFACE ESP_NETWORK_OBSERVER=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/network_v1.c)
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common)
    set_source_files_properties(../firmware_common/network_v1.c PROPERTIES COMPILE_OPTIONS "-Os")
endif()

if(SAFETY_LOCKED_BOOT)
    target_compile_definitions(stm32cubemx INTERFACE SAFETY_LOCKED_BOOT=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/safety_guard.c)
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common)
endif()

if(CAN_LINK_PROBE_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE CAN_LINK_PROBE_ONLY=1)
    target_sources(STM32_Drivers PRIVATE
        Drivers/STM32G4xx_HAL_Driver/Src/stm32g4xx_hal_fdcan.c
    )
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE Core/Src/can_link_probe.c)
endif()

if(CAN_STATUS_TELEMETRY AND NOT CAN_LINK_PROBE_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE CAN_STATUS_TELEMETRY=1)
    target_sources(STM32_Drivers PRIVATE
        Drivers/STM32G4xx_HAL_Driver/Src/stm32g4xx_hal_fdcan.c
    )
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../firmware_common/can_status_tx.c
    )
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
        ../firmware_common
    )
endif()

if(CAN_SHADOW_DIAG)
    target_compile_definitions(stm32cubemx INTERFACE CAN_SHADOW_DIAG=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../firmware_common/can_shadow_diag.c
    )
endif()

if(CAN_LOG_STREAM)
    target_compile_definitions(stm32cubemx INTERFACE CAN_LOG_STREAM=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../firmware_common/can_log_v1.c ../firmware_common/pw_can_log.c)
    set_source_files_properties(../firmware_common/can_log_v1.c
        ../firmware_common/pw_can_log.c PROPERTIES COMPILE_OPTIONS "-Os")
endif()

if(CAN_CONTROL_REJECT_ONLY)
    target_compile_definitions(stm32cubemx INTERFACE CAN_CONTROL_REJECT_ONLY=1)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../firmware_common/can_control_v0.c
    )
endif()

set(FREERTOS_KERNEL_PATH
    ${CMAKE_CURRENT_SOURCE_DIR}/Middlewares/FreeRTOS-Kernel
)

target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Src/router.c
    Core/Src/esp_link.c
    Core/Src/ring_buffer.c
    Core/Src/uart_async.c
    Core/Src/uart_rx_dma.c
    Core/Src/modbus_probe.c
    ${FREERTOS_KERNEL_PATH}/tasks.c
    ${FREERTOS_KERNEL_PATH}/queue.c
    ${FREERTOS_KERNEL_PATH}/list.c
    ${FREERTOS_KERNEL_PATH}/event_groups.c
    ${FREERTOS_KERNEL_PATH}/stream_buffer.c
    ${FREERTOS_KERNEL_PATH}/portable/GCC/ARM_CM4F/port.c
    ${FREERTOS_KERNEL_PATH}/portable/MemMang/heap_4.c
    Middleware/pigweed/pw_smoke_test.cc
    Middleware/pigweed/pw_thread_smoke_test.cc
    Middleware/pigweed/pw_unit_tests.cc
    Middleware/pigweed/pw_kvs_params.cc
    Middleware/pigweed/pw_rpc_service.cc
    Middleware/pigweed/pw_allocator_port.cc
    Middleware/pigweed/pw_log_router_bridge.c
)
if(NOT PW_TARGET_UNIT_TESTS)
    # Exclude the test registration constructor too; dead-code elimination
    # alone cannot discard a constructor retained by .init_array.
    get_target_property(production_sources ${CMAKE_PROJECT_NAME} SOURCES)
    list(FILTER production_sources EXCLUDE REGEX "^Middleware/pigweed/pw_unit_tests\\.cc$")
    set_property(TARGET ${CMAKE_PROJECT_NAME} PROPERTY SOURCES "${production_sources}")
    target_compile_definitions(stm32cubemx INTERFACE PW_TARGET_UNIT_TESTS_DISABLED=1)
endif()
if(SAFETY_LOCKED_BOOT)
    # App-level C++ constructors otherwise retain RPC/KVS Flash-write vtables,
    # even when their tasks are never started. Exclude them from this profile.
    get_target_property(locked_sources ${CMAKE_PROJECT_NAME} SOURCES)
    list(FILTER locked_sources EXCLUDE REGEX "^Middleware/pigweed/")
    set_property(TARGET ${CMAKE_PROJECT_NAME} PROPERTY SOURCES "${locked_sources}")
endif()

# Router and ESP discovery run in FreeRTOS tasks, outside the 20 kHz FOC ISR.
# Optimize only these communication modules to preserve the motor-control
# compilation settings while recovering space in the 224 KiB app slot.
set_source_files_properties(Core/Src/router.c PROPERTIES COMPILE_OPTIONS "-Os")
set_source_files_properties(Core/Src/esp_link.c PROPERTIES COMPILE_OPTIONS "-Os")
set_source_files_properties(Core/Src/modbus_probe.c PROPERTIES COMPILE_OPTIONS "-Os")
set_source_files_properties(Middleware/pigweed/pw_log_router_bridge.c PROPERTIES COMPILE_OPTIONS "-Os")
set_source_files_properties(Middleware/pigweed/pw_unit_tests.cc PROPERTIES COMPILE_OPTIONS "-Os")

target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    ${FREERTOS_KERNEL_PATH}/include
    ${FREERTOS_KERNEL_PATH}/portable/GCC/ARM_CM4F
    ${CMAKE_CURRENT_SOURCE_DIR}/Middleware/pigweed
)

# Pigweed platform subset through Stage 5.9.3:
# pw_log, assertions, pw_thread/FreeRTOS, pw_unit_test light, pw_kvs,
# pw_rpc, pw_transfer, pw_allocator backed by FreeRTOS heap_4, and buffered
# pw_log with a static queue/history backend plus opt-in official tokenized
# logging, an ELF-resident detokenization dictionary, and best-effort Router
# subscriptions drained by ProtocolTask.
#
# Build only the required upstream source and headers. Adding Pigweed's entire
# root project would configure unrelated modules/tests and requires Windows
# symlink privileges; later stages will add their own modules deliberately.
set(PW_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/pigweed")
add_library(pigweed_platform STATIC
    ${PW_ROOT}/pw_base64/base64.cc
    ${PW_ROOT}/pw_log_string/handler.cc
    ${PW_ROOT}/pw_log_tokenized/log_tokenized.cc
    ${PW_ROOT}/pw_tokenizer/base64.cc
    ${PW_ROOT}/pw_tokenizer/encode_args.cc
    ${PW_ROOT}/pw_tokenizer/tokenize.cc
    ${PW_ROOT}/pw_thread/yield.cc
    ${PW_ROOT}/pw_thread_freertos/thread.cc
    ${PW_ROOT}/pw_unit_test/ffi_test_runner.cc
    ${PW_ROOT}/pw_unit_test/framework_light.cc
    ${PW_ROOT}/pw_unit_test/logging_event_handler.cc
    ${PW_ROOT}/pw_string/string_builder.cc
    ${PW_ROOT}/pw_string/format.cc
    ${PW_ROOT}/pw_string/type_to_string.cc
    ${PW_ROOT}/pw_status/status.cc
    ${PW_ROOT}/pw_checksum/crc16_ccitt.cc
    ${PW_ROOT}/pw_checksum/crc32.cc
    ${PW_ROOT}/pw_kvs/alignment.cc
    ${PW_ROOT}/pw_kvs/checksum.cc
    ${PW_ROOT}/pw_kvs/entry.cc
    ${PW_ROOT}/pw_kvs/entry_cache.cc
    ${PW_ROOT}/pw_kvs/flash_memory.cc
    ${PW_ROOT}/pw_kvs/format.cc
    ${PW_ROOT}/pw_kvs/key_value_store.cc
    ${PW_ROOT}/pw_kvs/sectors.cc
    ${PW_ROOT}/pw_containers/intrusive_item.cc
    ${PW_ROOT}/pw_varint/varint.cc
    ${PW_ROOT}/pw_varint/stream.cc
    ${PW_ROOT}/pw_protobuf/decoder.cc
    ${PW_ROOT}/pw_protobuf/encoder.cc
    ${PW_ROOT}/pw_protobuf/find.cc
    ${PW_ROOT}/pw_stream/memory_stream.cc
    ${PW_ROOT}/pw_rpc/call.cc
    ${PW_ROOT}/pw_rpc/channel.cc
    ${PW_ROOT}/pw_rpc/channel_list.cc
    ${PW_ROOT}/pw_rpc/endpoint.cc
    ${PW_ROOT}/pw_rpc/packet.cc
    ${PW_ROOT}/pw_rpc/packet_meta.cc
    ${PW_ROOT}/pw_rpc/server.cc
    ${PW_ROOT}/pw_rpc/server_call.cc
    ${PW_ROOT}/pw_rpc/service.cc
    ${PW_ROOT}/pw_rpc/raw/method.cc
    ${PW_ROOT}/pw_transfer/chunk.cc
    ${PW_ROOT}/pw_allocator/allocator.cc
    ${PW_ROOT}/pw_allocator/freertos_allocator.cc
    Middleware/pigweed/pw_log_backend.c
    ../firmware_common/pw_log_store.c
    ../firmware_common/pw_log_snapshot.c
    Middleware/pigweed/pw_log_tokenized_port.cc
)

target_compile_definitions(pigweed_platform PUBLIC
    PW_LOG_STORE_CAPACITY=${PW_LOG_STORE_SLOTS}
    PW_THREAD_FREERTOS_CONFIG_DYNAMIC_ALLOCATION_ENABLED=0
    PW_UNIT_TEST_CONFIG_MEMORY_POOL_SIZE=2048
    PW_RPC_USE_GLOBAL_MUTEX=$<OR:$<BOOL:${CAN_RPC_READ_ONLY}>,$<BOOL:${UART_FIRMWARE_TRANSFER}>>
    PW_RPC_ENCODING_BUFFER_SIZE_BYTES=128
    PW_RPC_COMPLETION_REQUEST_CALLBACK=1
    PW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32
)

if(CAN_RPC_READ_ONLY OR UART_FIRMWARE_TRANSFER)
    include(../firmware_common/pigweed_transfer.cmake)
    project_add_transfer_engine(pigweed_platform freertos)
endif()
if(UART_FIRMWARE_TRANSFER)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE ../firmware_common/uart_firmware_transfer.cc
        ../firmware_common/uart_firmware_transfer_hex.c)
    target_compile_definitions(stm32cubemx INTERFACE UART_FIRMWARE_TRANSFER=1)
    set_source_files_properties(../firmware_common/uart_firmware_transfer.cc PROPERTIES COMPILE_OPTIONS "-Os")
endif()

# The application remains a debug build, but upstream middleware is optimized
# for size so the fixed 224 KiB A/B slot boundary is never changed.
target_compile_options(pigweed_platform PRIVATE -Os)
if(FOC_PROTECTED_CLOSED_LOOP AND NOT FOC_ENABLE_LEGACY_CURRENT_REPAIR)
    # Keep the vendor drivers at their historical size optimization so the
    # fixed 224 KiB slot still fits. main/ADC vector/encoder current hot chain
    # remain O2; the normal injected path does not call HAL_ADC_IRQHandler.
    target_compile_options(STM32_Drivers PRIVATE -Os)
endif()
if(PW_ALLOCATOR_HYBRID)
    target_sources(pigweed_platform PRIVATE ../firmware_common/pw_managed_buffer.cc)
    target_compile_definitions(pigweed_platform PUBLIC PW_ALLOCATOR_HYBRID=1)
endif()
set_source_files_properties(
    Middleware/pigweed/pw_rpc_service.cc
    PROPERTIES COMPILE_OPTIONS "-Os"
)

set(PW_LOG_BACKEND_INCLUDES ${PW_ROOT}/pw_log_string/public_overrides)
if(PW_LOG_TOKENIZED_DEFAULT)
    # C++ constexpr-compatible official metadata backend + tokenizer indicator.
    # Do not keep the string
    # override in this list: PW_LOG_* must not silently select the old facade.
    set(PW_LOG_BACKEND_INCLUDES
        ${CMAKE_CURRENT_SOURCE_DIR}/../firmware_common/pw_log_tokenized_override
        ${PW_ROOT}/pw_log_tokenized/public_overrides)
endif()
target_include_directories(pigweed_platform PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/../firmware_common
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Inc
    ${CMAKE_CURRENT_SOURCE_DIR}/Middleware/pigweed
    ${FREERTOS_KERNEL_PATH}/include
    ${FREERTOS_KERNEL_PATH}/portable/GCC/ARM_CM4F
    ${PW_ROOT}/pw_assert/public
    ${PW_ROOT}/pw_assert_log/assert_backend_public_overrides
    ${PW_ROOT}/pw_assert_log/check_backend_public_overrides
    ${PW_ROOT}/pw_assert_log/public
    ${PW_ROOT}/pw_allocator/public
    ${PW_ROOT}/pw_base64/public
    ${PW_ROOT}/pw_bytes/public
    ${PW_ROOT}/pw_checksum/public
    ${PW_ROOT}/pw_chrono/public
    ${PW_ROOT}/pw_chrono_freertos/public
    ${PW_ROOT}/pw_chrono_freertos/public_overrides
    ${PW_ROOT}/pw_containers/public
    ${PW_ROOT}/pw_function/public
    ${PW_ROOT}/pw_interrupt/public
    ${PW_ROOT}/pw_interrupt_cortex_m/public
    ${PW_ROOT}/pw_interrupt_cortex_m/public_overrides
    ${PW_ROOT}/pw_kvs
    ${PW_ROOT}/pw_kvs/public
    ${PW_ROOT}/pw_log/public
    ${PW_ROOT}/pw_log_string/public
    ${PW_LOG_BACKEND_INCLUDES}
    ${PW_ROOT}/pw_log_tokenized/public
    ${PW_ROOT}/pw_memory/public
    ${PW_ROOT}/pw_numeric/public
    ${PW_ROOT}/pw_polyfill/public
    ${PW_ROOT}/pw_polyfill/standard_library_public
    ${PW_ROOT}/pw_preprocessor/public
    ${PW_ROOT}/pw_protobuf/public
    ${PW_ROOT}/pw_result/public
    ${PW_ROOT}/pw_rpc/public
    ${PW_ROOT}/pw_rpc/raw/public
    ${PW_ROOT}/pw_span/public
    ${PW_ROOT}/pw_status/public
    ${PW_ROOT}/pw_stream/public
    ${PW_ROOT}/pw_string/public
    ${PW_ROOT}/pw_sync/public
    ${PW_ROOT}/pw_thread/public
    ${PW_ROOT}/pw_thread_freertos/id_public_overrides
    ${PW_ROOT}/pw_thread_freertos/public
    ${PW_ROOT}/pw_thread_freertos/thread_creation_public_overrides
    ${PW_ROOT}/pw_thread_freertos/thread_public_overrides
    ${PW_ROOT}/pw_thread_freertos/yield_public_overrides
    ${PW_ROOT}/pw_toolchain/public
    ${PW_ROOT}/pw_tokenizer/public
    ${PW_ROOT}/pw_transfer/public
    ${PW_ROOT}/pw_varint/public
    ${PW_ROOT}/pw_unit_test/light_public_overrides
    ${PW_ROOT}/pw_unit_test/public
    ${PW_ROOT}/pw_unit_test/public_overrides
    ${PW_ROOT}/third_party/fuchsia/repo/sdk/lib/fit/include
    ${PW_ROOT}/third_party/fuchsia/repo/sdk/lib/stdcompat/include
)

target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx
    pigweed_platform
)

# Token strings stay in the ELF for host-side decoding and are excluded from
# the flashable BIN/HEX payload.
target_link_options(${CMAKE_PROJECT_NAME} PRIVATE
    "-T${PW_ROOT}/pw_tokenizer/pw_tokenizer_linker_sections.ld"
)

# Keep the IAP payloads synchronized with every successful ELF link.
add_custom_command(TARGET ${CMAKE_PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex
            $<TARGET_FILE:${CMAKE_PROJECT_NAME}>
            $<TARGET_FILE_DIR:${CMAKE_PROJECT_NAME}>/${CMAKE_PROJECT_NAME}.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary
            $<TARGET_FILE:${CMAKE_PROJECT_NAME}>
            $<TARGET_FILE_DIR:${CMAKE_PROJECT_NAME}>/${CMAKE_PROJECT_NAME}.bin
    COMMENT "Generating current HEX and BIN images"
)

list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)
