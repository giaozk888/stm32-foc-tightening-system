/* Temporary Thumb RAM routine; no stack, calls, Flash or motor commands.
 * Host configures only TIM1 CH2/CH2N and forced-low OC4REF/TRGO2.
 * Input r8: microsecond duration; r9: DWT cycle fallback; r10: result address.
 * Both deadlines use wrap-safe unsigned subtraction. SD is forced low before
 * enabling logic outputs and on every loop. A BKPT ends the routine with all
 * TIM1 outputs/counter off. Normal firmware context is restored by the host.
 */
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.global pwm_logic_entry
.type pwm_logic_entry, %function
.thumb_func
pwm_logic_entry:
    ldr r0, =0x48000818      /* GPIOC BSRR, reset SD/PC6 */
    ldr r1, =0x00400000
    str r1, [r0]
    ldr r2, =0x40000024      /* TIM2 CNT, existing 1 MHz free-running timer */
    ldr r3, [r2]
    ldr r4, =0xE0001004      /* DWT CYCCNT, existing 170 MHz counter */
    ldr r5, [r4]
    ldr r6, =0x40012C00      /* TIM1 */
    ldr r7, [r6, #0x44]
    orr r7, r7, #0x8000     /* MOE: logic signals only; gate stays disabled */
    str r7, [r6, #0x44]
    ldr r7, [r6]
    orr r7, r7, #1
    str r7, [r6]
    movs r7, #1
    str r7, [r10]           /* RUNNING */
1:
    str r1, [r0]           /* SD=0, never write a SET value */
    ldr r7, [r2]
    subs r7, r7, r3
    cmp r7, r8
    bhs 2f
    ldr r7, [r4]
    subs r7, r7, r5
    cmp r7, r9
    bhs 2f
    ldr r7, =0x40003000     /* Reload IWDG if already running, never start it */
    ldr r11, =0xAAAA
    str r11, [r7]
    b 1b
2:
    ldr r7, [r6, #0x44]
    bic r7, r7, #0x8000
    str r7, [r6, #0x44]     /* MOE off first */
    movs r7, #0
    str r7, [r6, #0x20]     /* All channel enables off */
    ldr r7, [r6]
    bic r7, r7, #1
    str r7, [r6]            /* CEN off */
    str r1, [r0]
    ldr r7, [r2]
    subs r7, r7, r3
    str r7, [r10, #4]
    ldr r7, [r4]
    subs r7, r7, r5
    str r7, [r10, #8]
    movs r7, #2
    str r7, [r10]           /* STOPPED */
    dsb
    bkpt #0
3:  b 3b                    /* Still safe if debugger does not immediately halt */
.size pwm_logic_entry, .-pwm_logic_entry
.ltorg
