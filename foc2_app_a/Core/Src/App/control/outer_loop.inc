/* App A control/outer_loop.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s)
{
    uint16_t raw = 0U;
    float theta_e;
    static MotorControlMode_t previous_mode = MOTOR_MODE_IDLE;

#if defined(AS5047P_SPI_DMA)
    AsDmaSample sample;
    uint32_t dt_us;
    if (!AS5047P_DmaGetSample(&sample)) return HAL_BUSY;
    uint32_t consume_now=AS5047P_DmaNowUs();
    int consumed = AsDma_Consume(&encoder_dma_cursor, &sample,consume_now,&dt_us);
#if defined(FOC_OUTER_OBSERVE_AFTER_ACK)
    outer_observation.pending=0U;
    if (consumed>0) OuterTrace_Consume(&outer_completion_trace,consume_now,sample.sample_us,sample.sequence);
#endif
    if (consumed == 0) return HAL_BUSY;
    if (consumed < 0)
    {
        encoder_error_count++;
        encoder_timeout_reason=FocEncoder_TimeoutReason(&encoder_dma_cursor,&sample,consume_now);
        EncoderDma_FaultFromISR();
        return HAL_ERROR;
    }
    raw = sample.raw;
    if (sample.errfl_valid) as5047p_last_errfl = sample.errfl;
    dt_s = (float)dt_us * 0.000001f;
    encoder_speed_dt_accum_s += dt_s;
#else
    if ((dt_s <= 0.0f) || (dt_s > 0.100f))
        dt_s = 0.001f;

    encoder_speed_dt_accum_s += dt_s;

    if (AS5047P_ReadAngle(&raw) != HAL_OK)
    {
        encoder_error_count++;
        encoder_valid = 0U;
        foc_fault_reason = 2U;
        foc_fault = 1U;
        PowerStage_Disable();
        FaultDiag_Motor(2U);
        return HAL_ERROR;
    }
#endif

    theta_e = Encoder_ElectricalAngleRad(raw);

    if (encoder_prev_valid != 0U)
    {
        int32_t d_raw = (int32_t)raw - (int32_t)encoder_prev_raw;
        float dt_meas = encoder_speed_dt_accum_s;
        float rpm_inst;
        float alpha;
        float mech_rad_s;

        MotorControlMode_t mode = motor_control_mode;

        float speed_err = 0.0f;
        float p_term = 0.0f;
        float i_candidate = speed_integrator_A;
        float iq_unsat = 0.0f;
        float iq_cmd = 0.0f;

        float speed_iq_limit_A = SPEED_IQ_LIMIT_A;
        float stall_iq_min_A = STALL_IQ_MIN_A;
        float stall_ref_min_rpm = STALL_REF_MIN_RPM;
        float stall_timeout_s = STALL_TIMEOUT_S;

        uint8_t run_speed_pi = 0U;
        uint8_t allow_stall_check = 0U;

        d_raw = AS5047P_Delta14(raw, encoder_prev_raw);

        if (dt_meas <= 0.0f)
            dt_meas = 0.001f;

        rpm_inst = AS5047P_InstantRpm(d_raw, ENCODER_DIRECTION, dt_meas);

        encoder_rpm_instant = rpm_inst;

        /*
         * Reject one impossible encoder jump without publishing it into the
         * control angle or speed estimator.
         */
        if (fabsf(rpm_inst) > SPEED_INSTANT_PLAUSIBLE_RPM)
        {
#if defined(FOC_SPEED_BRAKE_TRACK)
            SpeedBrakeTrack_Reset(&speed_brake_track);
#endif
            encoder_speed_glitch_count++;
            encoder_speed_glitch_streak++;

            if (encoder_speed_glitch_streak >= SPEED_GLITCH_STREAK_LIMIT)
            {
                foc_fault_reason = 2U;
                foc_fault = 1U;
                encoder_valid = 0U;
                PowerStage_Disable();
                FaultDiag_Motor(2U);
                return HAL_ERROR;
            }

            /* Rejected data did not publish angle/speed or acknowledge the
             * encoder watchdog. Do not tell TaskService it was a fresh update.
             * No ACK here: a genuinely invalid stream must still trip. */
#if defined(FOC_ENCODER_CONTROL_ADMISSION_FIX)
            return HAL_BUSY;
#else
            return HAL_OK;
#endif
        }

        encoder_speed_glitch_streak = 0U;

        encoder_position_deg +=
            (float)ENCODER_DIRECTION *
            (float)d_raw *
            360.0f /
            (float)AS5047P_CPR;

        /*
         * -------------------------------------------------------------
         * CONTROL SPEED
         * -------------------------------------------------------------
         *
         * Restore the previously proven controller feedback path:
         *
         *     1 ms instantaneous rpm -> 20 ms first-order LPF
         *
         * This filtered value is used by the Speed PI and existing protection
         * logic.  Do not put the 50 ms detector into this feedback path.
         */
        alpha = dt_meas / (SPEED_FILTER_TAU_S + dt_meas);
        alpha = ClampFloat(alpha, 0.0f, 1.0f);

        encoder_speed_rpm +=
            alpha * (rpm_inst - encoder_speed_rpm);

        /*
         * -------------------------------------------------------------
         * DETECTION SPEED
         * -------------------------------------------------------------
         *
         * Independently accumulate accepted mechanical angle for about 50 ms.
         * This gives a slower average speed for future seating/contact
         * detection and is intentionally NOT used by the Speed PI.
         */
        encoder_speed_detect_counts +=
            (int32_t)ENCODER_DIRECTION * d_raw;
        encoder_speed_detect_dt_s += dt_meas;
        encoder_speed_detect_samples++;

        if ((encoder_speed_detect_dt_s >= SPEED_DETECT_WINDOW_S) &&
            (encoder_speed_detect_samples >= SPEED_DETECT_MIN_SAMPLES))
        {
            encoder_speed_detect_rpm =
                ((float)encoder_speed_detect_counts * 60.0f) /
                ((float)AS5047P_CPR * encoder_speed_detect_dt_s);

            encoder_speed_detect_counts = 0;
            encoder_speed_detect_dt_s = 0.0f;
            encoder_speed_detect_samples = 0U;
        }

        mech_rad_s = encoder_speed_rpm * TWO_PI_F / 60.0f;

        /*
         * Electrical prediction uses the fast CONTROL speed, not the slow
         * detection speed.  Measured theta_e is still refreshed every 1 ms.
         */
        encoder_omega_e_rad_s =
            (float)POLE_PAIRS * mech_rad_s;

        if (fabsf(encoder_speed_rpm) > SPEED_OVERSPEED_RPM)
        {
            foc_fault_reason = 3U;
            foc_fault = 1U;
            foc_enable = 0U;
            PowerStage_Disable();
            FaultDiag_Motor(3U);
            PWM_SetDuty(0.5f, 0.5f, 0.5f);
            return HAL_ERROR;
        }

        /*
         * Every mode transition clears state that must never leak from one
         * controller into another.  This is the key boundary between the
         * application-level command API and the reusable 1 kHz control layer.
         */
        if (mode != previous_mode)
        {
#if defined(FOC_SPEED_BRAKE_TRACK)
            SpeedBrakeTrack_Reset(&speed_brake_track);
#endif
            speed_target_rpm = 0.0f;
            speed_ref_rpm = 0.0f;
#if defined(FOC_SPEED_SCURVE_CANDIDATE)
            SpeedScurve_Reset(&speed_scurve, speed_ref_rpm);
#endif
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
            if (mode==MOTOR_MODE_SPEED) SpeedAccelFf_Reset();
#endif
            speed_integrator_A = 0.0f;
            speed_integrator_bleed_active = 0U;
            speed_overspeed_bleed_active = 0U;
            speed_error_rpm = 0.0f;
            speed_p_term_A = 0.0f;

            stall_timer_s = 0.0f;

            active_hold_enable = 0U;
            active_hold_iq_cmd_A = 0.0f;

            position_error_sign_prev = 0;
            position_deadband_active = 1U;

            previous_mode = mode;
        }

        /*
         * Always keep position diagnostics meaningful, even when the active
         * controller is SPEED or IQ mode.
         */
        position_target_deg = motor_position_command_deg;
#if defined(FOC_SPEED_BRAKE_TRACK)
        if (mode != MOTOR_MODE_SPEED) SpeedBrakeTrack_Reset(&speed_brake_track);
#endif
        position_error_deg =
            position_target_deg - encoder_position_deg;

        /*
         * -------------------------------------------------------------
         * MODE SELECTION
         * -------------------------------------------------------------
         */
        if (mode == MOTOR_MODE_IDLE)
        {
            position_speed_cmd_rpm = 0.0f;
            speed_target_rpm = 0.0f;
            speed_ref_rpm = 0.0f;

            speed_integrator_A = 0.0f;
            speed_integrator_bleed_active = 0U;
            speed_overspeed_bleed_active = 0U;

            active_hold_enable = 0U;
            active_hold_iq_cmd_A = 0.0f;
            position_deadband_active = 1U;

            speed_error_rpm = 0.0f;
            speed_p_term_A = 0.0f;
            stall_timer_s = 0.0f;

            foc_iq_ref_A = 0.0f;
        }
        else if (mode == MOTOR_MODE_IQ)
        {
            /*
             * Direct torque/current command.
             *
             * This bypasses Position P and Speed PI, but still uses the proven
             * 20 kHz Id/Iq current controller.  The 2 A phase-current trip and
             * 300 rpm overspeed protection remain active.
             *
             * The position-test stall detector is intentionally disabled in
             * this mode because "speed near zero + current high" can be a
             * legitimate tightening condition.
             */
            position_speed_cmd_rpm = 0.0f;
            speed_target_rpm = 0.0f;
            speed_ref_rpm = 0.0f;

            speed_integrator_A = 0.0f;
            speed_integrator_bleed_active = 0U;
            speed_overspeed_bleed_active = 0U;

            active_hold_enable = 0U;
            active_hold_iq_cmd_A = 0.0f;
            position_deadband_active = 0U;

            speed_error_rpm = 0.0f;
            speed_p_term_A = 0.0f;
            stall_timer_s = 0.0f;

            foc_iq_ref_A =
                ClampFloat(motor_iq_command_A,
                           -MOTOR_DIRECT_IQ_LIMIT_A,
                            MOTOR_DIRECT_IQ_LIMIT_A);
        }
        else
        {
            /*
             * POSITION and SPEED modes both feed the same proven speed PI.
             * Only the source of speed_target_rpm is different.
             */
            run_speed_pi = 1U;
            allow_stall_check = 1U;

            if (mode == MOTOR_MODE_SPEED)
            {
                active_hold_enable = 0U;
                active_hold_iq_cmd_A = 0.0f;
                position_deadband_active = 0U;
                position_speed_cmd_rpm = 0.0f;

                speed_target_rpm =
                    ClampFloat(motor_speed_command_rpm,
                               -MOTOR_SPEED_API_LIMIT_RPM,
                                MOTOR_SPEED_API_LIMIT_RPM);

                speed_iq_limit_A = MOTOR_SPEED_IQ_LIMIT_A;
                stall_iq_min_A = MOTOR_SPEED_STALL_IQ_MIN_A;
                stall_ref_min_rpm = MOTOR_SPEED_STALL_REF_MIN_RPM;
                stall_timeout_s = MOTOR_SPEED_STALL_TIMEOUT_S;
            }
            else
            {
                float position_speed_limit_rpm =
                    POSITION_SPEED_LIMIT_RPM;

                /*
                 * Optional hybrid active hold for a position command.
                 * This preserves the already validated STG5 behavior, but it
                 * is now a property of a POSITION command instead of being
                 * hard-coded to profile stage 5.
                 */
                if (motor_position_active_hold != 0U)
                {
                    float hold_abs_err = fabsf(position_error_deg);

                    if (active_hold_enable != 0U)
                    {
                        if (hold_abs_err >= ACTIVE_HOLD_EXIT_DEG)
                        {
                            active_hold_enable = 0U;
                            active_hold_iq_cmd_A = 0.0f;
                            speed_integrator_A = 0.0f;
                            speed_ref_rpm = 0.0f;
                            stall_timer_s = 0.0f;
                        }
                    }
                    else
                    {
                        if (hold_abs_err <= ACTIVE_HOLD_ENTER_DEG)
                        {
                            active_hold_enable = 1U;
                            active_hold_iq_cmd_A = 0.0f;
                            speed_integrator_A = 0.0f;
                            speed_ref_rpm = 0.0f;
                            stall_timer_s = 0.0f;
                        }
                    }
                }
                else
                {
                    active_hold_enable = 0U;
                    active_hold_iq_cmd_A = 0.0f;
                }

                /*
                 * Position deadband hysteresis.
                 */
                if (position_deadband_active != 0U)
                {
                    if (fabsf(position_error_deg) >=
                        POSITION_DEADBAND_EXIT_DEG)
                    {
                        position_deadband_active = 0U;
                    }
                }
                else
                {
                    if (fabsf(position_error_deg) <=
                        POSITION_DEADBAND_ENTER_DEG)
                    {
                        position_deadband_active = 1U;
                    }
                }

                /*
                 * Position-error sign reversal -> remove stale speed-I history.
                 */
                {
                    int8_t position_sign_now = 0;

                    if (position_error_deg >
                        POSITION_DEADBAND_ENTER_DEG)
                    {
                        position_sign_now = 1;
                    }
                    else if (position_error_deg <
                             -POSITION_DEADBAND_ENTER_DEG)
                    {
                        position_sign_now = -1;
                    }

                    if (position_sign_now != 0)
                    {
                        if ((position_error_sign_prev != 0) &&
                            (position_sign_now !=
                             position_error_sign_prev))
                        {
                            speed_integrator_A = 0.0f;
                            speed_integrator_bleed_active = 0U;
                            speed_overspeed_bleed_active = 0U;
                            stall_timer_s = 0.0f;
                            position_direction_reset_count++;
                        }

                        position_error_sign_prev =
                            position_sign_now;
                    }
                }

                if ((motor_position_active_hold != 0U) &&
                    (active_hold_enable == 0U))
                {
                    position_speed_limit_rpm =
                        STG5_RETURN_SPEED_LIMIT_RPM;

                    speed_iq_limit_A =
                        STG5_RETURN_IQ_LIMIT_A;

                    stall_iq_min_A =
                        STG5_RETURN_STALL_IQ_MIN_A;
                }

                if (active_hold_enable != 0U)
                {
                    position_speed_cmd_rpm = 0.0f;
                    speed_target_rpm = 0.0f;
                    speed_ref_rpm = 0.0f;
                }
                else if (position_deadband_active != 0U)
                {
                    position_speed_cmd_rpm = 0.0f;
                    speed_target_rpm = 0.0f;
                }
                else
                {
                    position_speed_cmd_rpm =
                        POSITION_KP_RPM_PER_DEG *
                        position_error_deg;

                    position_speed_cmd_rpm =
                        ClampFloat(position_speed_cmd_rpm,
                                   -position_speed_limit_rpm,
                                    position_speed_limit_rpm);

                    speed_target_rpm =
                        position_speed_cmd_rpm;
                }
            }
        }

        /*
         * -------------------------------------------------------------
         * Shared SPEED PI for POSITION and SPEED modes
         * -------------------------------------------------------------
         */
        if (run_speed_pi != 0U)
        {
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
            SpeedAccelFfResult aff;
#endif
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
            SpeedFrictionResult friction;
#endif
#if defined(FOC_SPEED_SCURVE_CANDIDATE)
            if (mode == MOTOR_MODE_SPEED) {
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
                StartupTimes_Begin(&startup_timestamps,AS5047P_DmaNowUs(),speed_target_rpm);
#endif
#if defined(FOC_DOB_LOAD_SPEED)
                speed_target_rpm=DobLoadSpeed_Select(sample.sample_us,(uint32_t)intent_fsm.state,
                    speed_target_rpm,(float)intent_fsm.cfg.recipe.contact_rpm,
                    speed_scurve.speed_rpm,speed_scurve.acceleration_rpm_s);
#endif
                speed_ref_rpm = SpeedScurve_Step(&speed_scurve, speed_target_rpm, dt_meas);
#if defined(FOC_ACCEL_FF_AUDIT)
                ++speed_accel_audit.meta.trajectory_updates;
#endif
            } else {
#endif
            if (speed_ref_rpm < speed_target_rpm)
            {
                float step =
                    SPEED_RAMP_UP_RPM_PER_S * dt_meas;

                speed_ref_rpm += step;

                if (speed_ref_rpm > speed_target_rpm)
                    speed_ref_rpm = speed_target_rpm;
            }
            else if (speed_ref_rpm > speed_target_rpm)
            {
                float step =
                    SPEED_RAMP_DOWN_RPM_PER_S * dt_meas;

                speed_ref_rpm -= step;

                if (speed_ref_rpm < speed_target_rpm)
                    speed_ref_rpm = speed_target_rpm;
            }
#if defined(FOC_SPEED_SCURVE_CANDIDATE)
            } /* POSITION retains the original linear reference ramp. */
#endif

            speed_err =
                speed_ref_rpm - encoder_speed_rpm;

            p_term =
                SPEED_KP_A_PER_RPM * speed_err;

            speed_error_rpm = speed_err;
            speed_p_term_A = p_term;

            speed_diag_time_s += dt_meas;
            speed_diag_speed_integral +=
                encoder_speed_rpm * dt_meas;
            speed_diag_error_integral +=
                speed_err * dt_meas;

            if (speed_diag_valid == 0U)
            {
                speed_diag_min_rpm = encoder_speed_rpm;
                speed_diag_max_rpm = encoder_speed_rpm;
                speed_diag_valid = 1U;
            }
            else
            {
                if (encoder_speed_rpm < speed_diag_min_rpm)
                    speed_diag_min_rpm = encoder_speed_rpm;

                if (encoder_speed_rpm > speed_diag_max_rpm)
                    speed_diag_max_rpm = encoder_speed_rpm;
            }

            /*
             * IBLD only belongs to position settling.  OBLD is useful in both
             * POSITION and SPEED modes.
             */
#if defined(FOC_SPEED_BUMPLESS)
            /* Capture AFTER mode-change reset, BEFORE the legacy bleed can
             * mutate speed_integrator_A. SB2 must not subtract both bleeds. */
            float sb2_previous_A=speed_integrator_A;
#endif
            if ((mode == MOTOR_MODE_POSITION) &&
                (position_deadband_active != 0U) &&
                (fabsf(speed_ref_rpm) <=
                 SPEED_INT_BLEED_REF_MAX_RPM) &&
                (fabsf(encoder_speed_rpm) <=
                 SPEED_INT_BLEED_SPD_MAX_RPM))
            {
                float bleed_step =
                    SPEED_INT_BLEED_A_PER_S * dt_meas;

                speed_integrator_bleed_active = 1U;
                speed_overspeed_bleed_active = 0U;

                if (speed_integrator_A > bleed_step)
                    speed_integrator_A -= bleed_step;
                else if (speed_integrator_A < -bleed_step)
                    speed_integrator_A += bleed_step;
                else
                    speed_integrator_A = 0.0f;

                i_candidate = speed_integrator_A;
            }
            else if ((fabsf(encoder_speed_rpm) >=
                      SPEED_OVERSPEED_BLEED_MIN_SPD_RPM) &&
                     (fabsf(speed_err) >=
                      SPEED_OVERSPEED_BLEED_ERR_RPM) &&
                     ((speed_err * encoder_speed_rpm) < 0.0f) &&
                     ((speed_integrator_A *
                       encoder_speed_rpm) > 0.0f))
            {
                float bleed_step =
                    SPEED_OVERSPEED_I_BLEED_A_PER_S *
                    dt_meas;

                speed_integrator_bleed_active = 0U;
                speed_overspeed_bleed_active = 1U;

                if (speed_integrator_A > bleed_step)
                    speed_integrator_A -= bleed_step;
                else if (speed_integrator_A < -bleed_step)
                    speed_integrator_A += bleed_step;
                else
                    speed_integrator_A = 0.0f;

                i_candidate = speed_integrator_A;
            }
            else
            {
                speed_integrator_bleed_active = 0U;
                speed_overspeed_bleed_active = 0U;

                i_candidate =
                    speed_integrator_A +
                    SPEED_KI_A_PER_RPM_S *
                    speed_err *
                    dt_meas;
            }

#if defined(FOC_SPEED_STARTUP_BRAKE)
            if (mode == MOTOR_MODE_SPEED)
            {
#if defined(FOC_SPEED_BUMPLESS)
                SpeedStartupBrakeResult guarded=SpeedBumpless_Apply(
                    sb2_previous_A,i_candidate,speed_ref_rpm,encoder_speed_rpm,
                    dt_meas,SPEED_OVERSPEED_BLEED_ERR_RPM,SPEED_OVERSPEED_BLEED_MIN_SPD_RPM);
                i_candidate=guarded.integral_A;
                if (guarded.flags & SPEED_BUMPLESS_UNLOAD)
                    speed_overspeed_bleed_active=1U;
#else
                SpeedStartupBrakeResult guarded=SpeedStartupBrake_Apply(
                    speed_integrator_A,i_candidate,speed_ref_rpm,encoder_speed_rpm,
                    dt_meas,SPEED_OVERSPEED_BLEED_ERR_RPM,SPEED_OVERSPEED_BLEED_MIN_SPD_RPM);
                i_candidate=guarded.integral_A;
                if (guarded.flags & SPEED_STARTUP_I_BRAKE_RESET)
                    speed_overspeed_bleed_active=1U;
#endif
            }
#endif
            i_candidate =
                ClampFloat(i_candidate,
                           -SPEED_INT_LIMIT_A,
                            SPEED_INT_LIMIT_A);

#if defined(FOC_SPEED_PI_ANTI_WINDUP)
            if (mode == MOTOR_MODE_SPEED) {
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
#if defined(FOC_DOB_SATURATION_CONTINUE)
                if(mechanical_dob_monitor.current.status&DOB_MONITOR_SATURATED)
                    ++dob_saturation_audit.feedback_blocks;
#endif
                float iq_dob=DobFeedback_Update(&dob_feedback,AS5047P_DmaNowUs(),
                    (uint32_t)(dt_meas*1e6f+.5f),mechanical_dob_monitor.current.sample_us,
                    mechanical_dob_monitor.current.disturbance_a,
                    (uint8_t)(mechanical_dob_monitor.current.valid&&mechanical_dob_monitor.running&&!mechanical_dob_monitor.frozen
#if defined(FOC_DOB_SATURATION_CONTINUE)
                        &&!(mechanical_dob_monitor.current.status&DOB_MONITOR_SATURATED)
#endif
#if defined(FOC_DOB_CONTACT20_OBSERVE10)
                        &&DobObserve10_FeedbackSpeedQualified(mechanical_dob_monitor.current.omega_rad_s)
#endif
                        ),
                    (uint8_t)(cl_armed&&cl_session.state==CL_RUNNING&&!adc_fault&&!foc_fault),speed_iq_limit_A);
                friction=SpeedFrictionDob_Apply(sb2_previous_A,i_candidate,p_term,
#else
                friction=SpeedFriction_Apply(sb2_previous_A,i_candidate,p_term,
#endif
                    speed_scurve.acceleration_rpm_s,SPEED_ACCEL_EFFECTIVE_KA,
                    speed_ref_rpm,SPEED_FRICTION_I_A,SPEED_FRICTION_DEADBAND_RPM,
                    speed_iq_limit_A,SPEED_INT_LIMIT_A,
                    (uint8_t)(speed_integrator_bleed_active || speed_overspeed_bleed_active),
                    speed_accel_ff_enabled,speed_friction_enabled
#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
                    ,iq_dob
#endif
                    );
                aff=friction.speed;
#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
                dob_feedback.iq_pi_a=aff.iq_pi_a;dob_feedback.iq_raw_a=aff.iq_raw_a;
                dob_feedback.iq_ref_a=aff.iq_ref_a;dob_feedback.integral_a=aff.integral_a;
                dob_feedback.saturation=aff.saturated;
#endif
#else
                aff=SpeedAccelFf_Apply(sb2_previous_A,i_candidate,p_term,
                    speed_scurve.acceleration_rpm_s,SPEED_ACCEL_EFFECTIVE_KA,
                    speed_iq_limit_A,SPEED_INT_LIMIT_A,
                    (uint8_t)(speed_integrator_bleed_active || speed_overspeed_bleed_active),
                    speed_accel_ff_enabled);
#endif
                speed_integrator_A=aff.integral_a;
                iq_cmd=aff.iq_ref_a;
#else
                SpeedPiAntiWindupResult aw=SpeedPiAntiWindup_Apply(
                    sb2_previous_A,i_candidate,p_term,speed_iq_limit_A,SPEED_INT_LIMIT_A,
                    (uint8_t)(speed_integrator_bleed_active || speed_overspeed_bleed_active));
                speed_integrator_A=aw.integral_A;
                iq_cmd=aw.current_A;
#endif
            } else
            {
#endif
            iq_unsat = p_term + i_candidate;

            iq_cmd =
                ClampFloat(iq_unsat,
                           -speed_iq_limit_A,
                            speed_iq_limit_A);

            if ((speed_integrator_bleed_active != 0U) ||
                (speed_overspeed_bleed_active != 0U))
            {
                speed_integrator_A = i_candidate;
            }
            else if ((iq_unsat == iq_cmd) ||
                     ((iq_cmd >= speed_iq_limit_A) &&
                      (speed_err < 0.0f)) ||
                     ((iq_cmd <= -speed_iq_limit_A) &&
                      (speed_err > 0.0f)))
            {
                speed_integrator_A = i_candidate;
            }

#if defined(FOC_SPEED_PI_ANTI_WINDUP)
            }
#endif
#if defined(FOC_SPEED_BRAKE_TRACK) && !defined(FOC_SPEED_SB3_DISABLE_CANDIDATE)
            if (mode == MOTOR_MODE_SPEED) {
                SpeedBrakeTrackResult brake=SpeedBrakeTrack_Apply(&speed_brake_track,
                    speed_ref_rpm,encoder_speed_rpm,rpm_inst,p_term,speed_integrator_A,
                    iq_cmd,SPEED_KP_A_PER_RPM,SPEED_OVERSPEED_BLEED_ERR_RPM,
                    SPEED_OVERSPEED_BLEED_MIN_SPD_RPM,speed_iq_limit_A,SPEED_INT_LIMIT_A);
                if (brake.limited) {
                    speed_integrator_A=brake.integral_A;
                    speed_overspeed_bleed_active=1U;
                }
                iq_cmd=brake.current_A;
            }
#endif
            /* Publish once, after the SPEED-only ceiling, so an ADC IRQ
             * cannot consume the pre-limiter driving command in between. */
            foc_iq_ref_A = iq_cmd;
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
            if (mode==MOTOR_MODE_SPEED)
                StartupTimes_Observe(&startup_timestamps,AS5047P_DmaNowUs(),sample.sample_us,
                    (int32_t)ENCODER_DIRECTION*d_raw,encoder_speed_rpm,iq_cmd);
#endif
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
            if (mode==MOTOR_MODE_SPEED) {
                speed_accel_ff_frame=(SpeedAccelFfFrame){
                    .seq=speed_accel_ff_frame.seq+1U,.ms=HAL_GetTick(),
                    .command_rpm=speed_target_rpm,.speed_ref_rpm=speed_ref_rpm,
                    .speed_meas_rpm=encoder_speed_rpm,.accel_ref_rpm_s=speed_scurve.acceleration_rpm_s,
                    .iq_pi_a=aff.iq_pi_a,.iq_ff_a=aff.iq_ff_a,.iq_raw_a=aff.iq_raw_a,
                    .iq_ref_a=aff.iq_ref_a,.speed_integrator_a=aff.integral_a,.iq_meas_a=foc_iq_A,
                    .enabled=speed_accel_ff_enabled,.saturated=aff.saturated,.valid=1U};
#if defined(FOC_KA_SYNC_DIAG) || defined(FOC_KA_FULL_DIAG)
                KaSyncCurrent sync_current;
                uint8_t sync_valid=KaSync_TryRead(&ka_sync_current,&sync_current);
#if defined(FOC_KA_FULL_DIAG)
                KaFull_Observe(&ka_full_diagnostic,AS5047P_DmaNowUs(),sample.sample_us,
                    (uint32_t)(dt_meas*1000000.0f+.5f),raw,d_raw,encoder_speed_rpm,
                    speed_ref_rpm,speed_scurve.acceleration_rpm_s,friction.iq_fric_a,
                    aff.saturated,&sync_current,sync_valid);
#else
                KaSync_Observe(&ka_sync_diagnostic,AS5047P_DmaNowUs(),sample.sample_us,
                    (uint32_t)(dt_meas*1000000.0f+.5f),raw,d_raw,encoder_speed_rpm,
                    friction.iq_fric_a,aff.saturated,&sync_current,sync_valid);
#endif
#endif
#if defined(FOC_KA_IDENT_DIAG)
                KaIdent_Observe(&ka_identification,&speed_accel_ff_frame,friction.iq_fric_a,
                    AS5047P_DmaNowUs(),sample.sample_us,current_valid_count);
#endif
#if defined(FOC_ACCEL_FF_AUDIT)
                SpeedAccelAudit_Push(&speed_accel_audit,&speed_accel_ff_frame,friction.iq_fric_a,
                    speed_scurve.phase,dt_meas,SPEED_ACCEL_EFFECTIVE_KA,speed_iq_limit_A,
                    aff.aw_limited,(uint8_t)(speed_integrator_bleed_active || speed_overspeed_bleed_active),
                    sb2_previous_A,i_candidate);
#endif
#if defined(FOC_OUTER_OBSERVE_AFTER_ACK)
                /* Capture SAME-session inputs now; only the non-control
                 * statistics run later, after angle publication and real ACK.
                 * No early heartbeat on BUSY/reject/fault or unfinished PI. */
                outer_observation.valid=Mechanical_TryRead(&mechanical_current,&outer_observation.current);
                outer_observation.observed_us=AS5047P_DmaNowUs();
                outer_observation.sample_us=sample.sample_us;
                outer_observation.dt_us=(uint32_t)(dt_meas*1e6f+.5f);
                outer_observation.delta=(int32_t)ENCODER_DIRECTION*d_raw;
                outer_observation.omega_rad_s=encoder_speed_rpm*.10471975512f;
                outer_observation.dt_s=dt_meas;outer_observation.saturated=aff.saturated;
                outer_observation.friction_a=friction.iq_fric_a;
                outer_observation.pending=1U;
#else
                SpeedAccelFf_Observe(&speed_accel_ff_stats,&speed_accel_ff_frame,dt_meas);
#if defined(FOC_MECHANICAL_IDENT_DIAG)
                MechanicalCurrent mechanical_sample;
                uint8_t mechanical_valid=Mechanical_TryRead(&mechanical_current,&mechanical_sample);
                Mechanical_Observe(&mechanical_capture,AS5047P_DmaNowUs(),sample.sample_us,
                    (uint32_t)(dt_meas*1e6f+.5f),(int32_t)ENCODER_DIRECTION*d_raw,
                    encoder_speed_rpm*.10471975512f,aff.saturated,&mechanical_sample,mechanical_valid);
#endif
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
                speed_friction_frame=(SpeedFrictionFrame){.control=speed_accel_ff_frame,
                    .iq_fric_a=friction.iq_fric_a,.enabled=speed_friction_enabled};
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
                uint8_t startup_was_moving=speed_friction_stats.moving;
#endif
                SpeedFriction_Observe(&speed_friction_stats,&speed_friction_frame,dt_meas);
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
                if (!startup_was_moving && speed_friction_stats.moving)
                    StartupTimes_Stable(&startup_timestamps,AS5047P_DmaNowUs());
#endif
#if defined(FOC_FRICTION_CALIBRATION_DIAG)
                FrictionCalibration_Observe(dt_meas);
#endif
#endif
#endif /* FOC_OUTER_OBSERVE_AFTER_ACK: observations only, no control math. */
            }
#endif

            /*
             * POSITION active hold overrides the speed PI only inside the
             * small-error hold region.
             */
            if ((mode == MOTOR_MODE_POSITION) &&
                (active_hold_enable != 0U))
            {
                float hold_iq =
                    ACTIVE_HOLD_KP_A_PER_DEG *
                    position_error_deg -
                    ACTIVE_HOLD_KD_A_PER_RPM *
                    encoder_speed_rpm;

                hold_iq =
                    ClampFloat(hold_iq,
                               -ACTIVE_HOLD_IQ_LIMIT_A,
                                ACTIVE_HOLD_IQ_LIMIT_A);

                active_hold_iq_cmd_A = hold_iq;
                foc_iq_ref_A = hold_iq;

                speed_integrator_A = 0.0f;
                speed_integrator_bleed_active = 0U;
                speed_overspeed_bleed_active = 0U;
                stall_timer_s = 0.0f;
                allow_stall_check = 0U;
            }
            else
            {
                active_hold_iq_cmd_A = 0.0f;
            }

            /*
             * Mode-aware stall protection.
             *
             * SPEED mode uses a lower current threshold because its first
             * validation test is intentionally limited to +/-0.25 A.
             * IQ mode has no "requested speed", so this position-test stall
             * detector is not applicable there.
             */
            if ((allow_stall_check != 0U) &&
                (fabsf(speed_ref_rpm) > stall_ref_min_rpm) &&
                (fabsf(encoder_speed_rpm) <
                 STALL_SPEED_MAX_RPM) &&
                (fabsf(foc_iq_ref_A) >= stall_iq_min_A))
            {
                stall_timer_s += dt_meas;

                if (stall_timer_s >= stall_timeout_s)
                {
                    PowerStage_Disable(); /* Closure before diagnostic copies. */
                    FaultDiag_Capture(FOC_DIAG_MOTOR,4U,
                        mode==MOTOR_MODE_SPEED ? FOC_TO_STALL_SPEED : FOC_TO_STALL_POSITION,
                        tightening_test_elapsed_ms,0U);
                    stall_trip_position_deg =
                        encoder_position_deg;
                    stall_trip_target_deg =
                        position_target_deg;
                    stall_trip_ref_rpm =
                        speed_ref_rpm;
                    stall_trip_speed_rpm =
                        encoder_speed_rpm;

                    foc_fault_reason = 4U;
                    foc_fault = 1U;
                    foc_enable = 0U;

                    foc_iq_ref_A = 0.0f;
                    speed_integrator_A = 0.0f;

                    PowerStage_Disable();
                    PWM_SetDuty(0.5f, 0.5f, 0.5f);
                    return HAL_ERROR;
                }
            }
            else
            {
                stall_timer_s = 0.0f;
            }
        }
    }

    /*
     * Publish only an ACCEPTED encoder sample.
     */
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
    rundown_encoder_delta=encoder_prev_valid ? AS5047P_Delta14(raw,encoder_prev_raw) : 0;
    rundown_encoder_dt_us=(uint32_t)(encoder_speed_dt_accum_s*1000000.0f);
#endif
    encoder_prev_raw = raw;
    encoder_prev_valid = 1U;
    encoder_speed_dt_accum_s = 0.0f;

    encoder_raw = raw;
    encoder_theta_e = theta_e;
#if defined(AS5047P_SPI_DMA)
    /* A timer fault can preempt publication. Never resurrect a failed sample. */
    if (foc_fault != 0U) { encoder_valid = 0U; return HAL_ERROR; }
    uint32_t sample_age_us = AS5047P_DmaNowUs() - sample.sample_us;
    if (sample_age_us > AS_DMA_SAMPLE_MAX_AGE_US)
    {
        EncoderDma_FaultFromISR();
        return HAL_ERROR;
    }
    /* Background DMA samples can be one task period old. Compensate their
     * age instead of resetting the 20 kHz predictor to a stale angle.
     * Existing 600 rpm / 10 pole-pair limit makes at most one wrap sufficient. */
    float predicted = theta_e + encoder_omega_e_rad_s * (float)sample_age_us * 0.000001f;
    if (!isfinite(predicted)) { EncoderDma_FaultFromISR(); return HAL_ERROR; }
    if (predicted >= TWO_PI_F) predicted -= TWO_PI_F;
    if (predicted < 0.0f) predicted += TWO_PI_F;
    encoder_theta_e_pred = predicted;
    encoder_valid = 1U;
    AS5047P_DmaAcknowledgeControl();
#else
    encoder_theta_e_pred = theta_e;
    encoder_valid = 1U;

#endif
    return HAL_OK;
}

#if defined(FOC_OUTER_OBSERVE_AFTER_ACK)
/* Sole MotorControlTask writer. This has no PI/setpoint/angle/PWM writes and
 * never acknowledges any watchdog; failed/unfinished epochs are discarded. */
static void OuterObservation_Flush(void)
{
    if (!outer_observation.pending) return;
    outer_observation.pending=0U;
    SpeedAccelFf_Observe(&speed_accel_ff_stats,&speed_accel_ff_frame,outer_observation.dt_s);
#if !defined(FOC_DOB_ID_TRACE) && !defined(FOC_DOB_REAL_TRACE) && !defined(FOC_DOB_TREND_SHADOW)
    Mechanical_Observe(&mechanical_capture,outer_observation.observed_us,outer_observation.sample_us,
        outer_observation.dt_us,outer_observation.delta,outer_observation.omega_rad_s,
        outer_observation.saturated,&outer_observation.current,outer_observation.valid);
#endif
    speed_friction_frame=(SpeedFrictionFrame){.control=speed_accel_ff_frame,
        .iq_fric_a=outer_observation.friction_a,.enabled=speed_friction_enabled};
    SpeedFriction_Observe(&speed_friction_stats,&speed_friction_frame,outer_observation.dt_s);
#if defined(FOC_FRICTION_CALIBRATION_DIAG)
    FrictionCalibration_Observe(outer_observation.dt_s);
#endif
#if defined(FOC_MECHANICAL_DOB_SHADOW)
    uint32_t dob_begin=AS5047P_DmaNowUs();
#if defined(FOC_DOB_ID_TRACE)
    DobIdTrace_Begin((uint8_t)mechanical_dob_monitor.have_sample);
#endif
    MechanicalDobMonitor_Observe(&mechanical_dob_monitor,outer_observation.observed_us,
        outer_observation.sample_us,outer_observation.dt_us,outer_observation.omega_rad_s,
        outer_observation.saturated,&outer_observation.current,outer_observation.valid);
    uint32_t dob_elapsed=AS5047P_DmaNowUs()-dob_begin;
    if (dob_elapsed>mechanical_dob_monitor.max_compute_us) mechanical_dob_monitor.max_compute_us=dob_elapsed;
#if defined(FOC_DOB_TREND_SHADOW)
    /* Task only, after the original control acknowledgement and DOB update.
     * The capture owns mechanical_capture.points exclusively in this build. */
    uint32_t trend_begin=DWT->CYCCNT;
#if defined(FOC_DOB_TREND_CONTINUOUS)
    DobTrendContinuous_Bind(mechanical_capture.points,sizeof mechanical_capture.points);
#else
    DobTrendShadow_Bind(mechanical_capture.points,sizeof mechanical_capture.points);
#endif
    DobTrendInput trend_in={.encoder_us=outer_observation.sample_us,
        .observed_us=outer_observation.observed_us,
        .source_us=mechanical_dob_monitor.current.adc_source_us,
        .disturbance_a=mechanical_dob_monitor.current.disturbance_a,
        .direction=speed_accel_ff_frame.speed_ref_rpm>0?1:-1,
        .running=(uint8_t)mechanical_dob_monitor.running,
        .fault=(uint8_t)(adc_fault||foc_fault),
        .valid=(uint8_t)mechanical_dob_monitor.current.valid,
        .filter_updated=(uint8_t)dob_current_admission.filter_updated};
#if defined(FOC_DOB_TREND_CONTINUOUS)
    DobTrendContinuous_Observe(trend_in,speed_accel_ff_frame.speed_ref_rpm,
#else
    DobTrendShadow_Observe(trend_in,speed_accel_ff_frame.speed_ref_rpm,
#endif
        speed_scurve.acceleration_rpm_s,outer_observation.omega_rad_s*9.5492965855f,
        outer_observation.current.iq,mechanical_dob_monitor.current.status);
#if defined(FOC_DOB_RECOVERY_TIMING)
    if(dob_trend_continuous_arena)DobRecovery_Observe(&dob_trend_continuous_arena->classifier,&trend_in,
        mechanical_dob_monitor.current.status,outer_observation.omega_rad_s,
        dob_current_admission.armed,mechanical_dob_monitor.observer.elapsed_s);
#endif
    uint32_t trend_cycles=DWT->CYCCNT-trend_begin;
#if defined(FOC_DOB_TREND_CONTINUOUS)
    if(trend_cycles>dob_trend_continuous.max_cycles)dob_trend_continuous.max_cycles=trend_cycles;
#else
    if(trend_cycles>dob_trend_shadow.max_cycles)dob_trend_shadow.max_cycles=trend_cycles;
#endif
#endif
#if defined(FOC_DOB_REAL_TRACE)
    uint32_t raw_begin=DWT->CYCCNT;
    DobRealTrace_Bind(mechanical_capture.points,sizeof mechanical_capture.points);
    DobRealTrace_Observe((uint8_t)mechanical_dob_monitor.running,
        outer_observation.observed_us,outer_observation.sample_us,outer_observation.current.seq,
        outer_observation.current.id,outer_observation.current.iq,outer_observation.omega_rad_s,
        outer_observation.valid,outer_observation.saturated,mechanical_dob_monitor.current.status,
        (uint8_t)mechanical_dob_monitor.current.valid,(uint8_t)dob_current_admission.filter_updated,
        speed_accel_ff_frame.speed_ref_rpm,speed_scurve.acceleration_rpm_s,foc_iq_ref_A);
    uint32_t raw_cycles=DWT->CYCCNT-raw_begin;
    if(raw_cycles>dob_real_trace.max_cycles)dob_real_trace.max_cycles=raw_cycles;
#endif
#if defined(FOC_DOB_ID_TRACE)
    uint32_t dit_begin=AS5047P_DmaNowUs();
    DobIdTrace_After(outer_observation.sample_us,mechanical_dob_monitor.current.adc_seq,
        outer_observation.dt_us,mechanical_dob_monitor.current.id_a,mechanical_dob_monitor.abs_id_lpf,
        mechanical_dob_monitor.observer.elapsed_s,mechanical_dob_monitor.current.status,
        (uint8_t)mechanical_dob_monitor.current.valid,(uint8_t)mechanical_dob_monitor.observer.initialized,
        (uint8_t)mechanical_dob_monitor.have_sample,speed_accel_ff_frame.speed_ref_rpm,
        speed_scurve.acceleration_rpm_s,outer_observation.omega_rad_s*9.5492965855f
#if defined(FOC_DOB_SPIKE_ADMISSION)
        ,mechanical_dob_monitor.current.iq_a
#endif
#if defined(FOC_DOB_ADMISSION_START_GUARD)
        ,mechanical_dob_monitor.current.adc_source_us,mechanical_dob_monitor.current.adc_published_us
#endif
        );
    uint32_t dit_elapsed=AS5047P_DmaNowUs()-dit_begin;
    if(dit_elapsed>dob_id_trace.max_compute_us) dob_id_trace.max_compute_us=dit_elapsed;
#endif
#if defined(FOC_ID_STEADY_STATS)
    uint32_t ids_begin=AS5047P_DmaNowUs();
    IdSteady_Observe(&id_steady_stats,outer_observation.observed_us,outer_observation.sample_us,
        outer_observation.dt_us,speed_accel_ff_frame.speed_ref_rpm,speed_scurve.acceleration_rpm_s,
        outer_observation.omega_rad_s*9.5492965855f,foc_id_ref_A,outer_observation.saturated,
        &outer_observation.current,outer_observation.valid,mechanical_dob_monitor.abs_id_lpf,
        mechanical_dob_monitor.current.status,(uint8_t)mechanical_dob_monitor.current.valid);
    uint32_t ids_elapsed=AS5047P_DmaNowUs()-ids_begin;
    if(ids_elapsed>id_steady_stats.max_compute_us) id_steady_stats.max_compute_us=ids_elapsed;
#endif
#endif
}
#endif


