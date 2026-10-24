/* Readonly diagnostic replies; actual owner has 192 bytes. */
static uint8_t IdSteady_Command(const char *cmd,char *out,size_t size){
    if (!strcmp(cmd,"MOTOR TEST MECH IDSTATS CFG")){
        snprintf(out,size,"OK IDSTATS V=1 TARGET_RPM=600 CONFIRM_US=500000 WINDOW_US=1000000 THRESH_UA=50000 TOL_RPM=12 ACCEL_TOL_RPM_S=1 FEEDBACK=0");return 1;
    }
    if (strcmp(cmd,"MOTOR TEST MECH IDSTATS")) return 0;
    IdSteadyView v;
    if(!IdSteady_Read(&id_steady_stats,&v)){snprintf(out,size,"OK IDSTATS V=1 BUSY=1 FEEDBACK=0");return 1;}
    snprintf(out,size,"OK IDSTATS V=1 STATE=%lu N=%lu GOOD_US=%lu BAD_US=%lu RAW_US=%lu LP_US=%lu MAX_US=%lu FEEDBACK=0",
        (unsigned long)v.state,(unsigned long)v.good_n,(unsigned long)v.good_us,
        (unsigned long)v.bad_us,(unsigned long)v.raw_us,(unsigned long)v.filtered_us,(unsigned long)v.max_compute_us);
    return 1;
}
