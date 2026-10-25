/* App A diagnostics/value_format.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static uint16_t Median3_U16(uint16_t a, uint16_t b, uint16_t c)
{
    return FocMedian3_U16(a, b, c);
}

static void FormatSignedX10(char *buf, size_t n, int32_t x10)
{
    int32_t a = (x10 < 0) ? -x10 : x10;

    snprintf(buf, n,
             "%s%ld.%01ld",
             (x10 < 0) ? "-" : "",
             (long)(a / 10),
             (long)(a % 10));
}

static void FormatSignedX100(char *buf, size_t n, int32_t x100)
{
    int32_t a = (x100 < 0) ? -x100 : x100;

    snprintf(buf, n,
             "%s%ld.%02ld",
             (x100 < 0) ? "-" : "",
             (long)(a / 100),
             (long)(a % 100));
}

