/* Same R1 wire encoder for STM32/ESP and focused host tests. The including
 * translation unit supplies router.h and stdio.h. No queue/heap access here. */
size_t Router_EncodeAsciiFrame(const RouterPacket_t *packet, char *out, size_t out_size) {
    if (packet == NULL || out == NULL || out_size == 0U)
        return 0U;
    const int written =
        snprintf(out, out_size, "@R1 %u %u %u %u %u %u %s", (unsigned int)packet->src,
                 (unsigned int)packet->dst, (unsigned int)packet->type, (unsigned int)packet->seq,
                 (unsigned int)packet->ttl, (unsigned int)packet->length, packet->payload);
    if (written < 0 || (size_t)written >= out_size) {
        out[0] = '\0';
        return 0U;
    }
    return (size_t)written;
}
