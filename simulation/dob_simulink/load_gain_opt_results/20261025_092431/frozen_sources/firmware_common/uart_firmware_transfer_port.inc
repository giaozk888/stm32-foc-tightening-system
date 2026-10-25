/* Included by A/B main.c after Fw_TargetCrc32. ProtocolTask owns all IAP state. */
int PW_UartFirmwareTransfer_Port(uint32_t operation, uint32_t offset, const uint8_t *data,
                                 size_t size, uint32_t *value) {
    if (!value || !fw_update.active || fw_update.target_address != APP_TARGET_ADDRESS ||
        fw_update.image_size < 8U || fw_update.image_size > FW_SLOT_SIZE || foc_enable ||
        (TIM1->BDTR & TIM_BDTR_MOE) ||
        HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin) != GPIO_PIN_RESET)
        return 0;
    if (operation == UART_FW_PREPARE) {
        if (fw_update.bytes_received != 0U)
            return 0;
        *value = fw_update.image_size;
        return 1;
    }
    if (operation == UART_FW_WRITE)
        return size <= FW_DATA_MAX_BYTES && Fw_ProgramData(offset, data, (uint32_t)size);
    if (operation == UART_FW_COMPARE)
        return data && offset <= fw_update.bytes_received &&
               size <= fw_update.bytes_received - offset &&
               memcmp((const void *)(APP_TARGET_ADDRESS + offset), data, size) == 0;
    if (operation == UART_FW_VERIFY)
        return fw_update.bytes_received == fw_update.image_size && Fw_TargetVectorValid() &&
               Fw_TargetCrc32(fw_update.image_size) == fw_update.expected_crc32;
    return 0;
}
int PW_UartFirmwareTransfer_Send(const uint8_t *data, size_t size) {
    static const char prefix[] = "0 EVT FWTRANSFER RPC ";
    static const char hex[] = "0123456789ABCDEF";
    UART_AsyncTxLease_t lease;
    if (!data || !size || size > UART_FW_PACKET ||
        !UART_Async_Acquire(sizeof(prefix) - 1U + 2U * size + 2U, 250U, &lease))
        return 0;
    size_t n = sizeof(prefix) - 1U;
    memcpy(lease.data, prefix, n);
    for (size_t i = 0; i < size; ++i) {
        lease.data[n++] = (uint8_t)hex[data[i] >> 4];
        lease.data[n++] = (uint8_t)hex[data[i] & 15U];
    }
    lease.data[n++] = '\r';
    lease.data[n++] = '\n';
    if (UART_Async_Commit(&lease, n))
        return 1;
    (void)UART_Async_Cancel(&lease);
    return 0;
}
static void UartFirmwareTransfer_Command(uint32_t request_id, const char *args) {
    char msg[192];
    if (!protocol_esp_ping_uart_local) {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOCAL_UART_ONLY");
        return;
    }
    if (strcmp(args, "STATUS") == 0) {
        UartFirmwareTransferDiagnostics d;
        PW_UartFirmwareTransfer_GetDiagnostics(&d);
        (void)Protocol_SendFormatted(
            msg, sizeof(msg),
            "%lu OK FWTRANSFER ENGINE=OFFICIAL READY=%lu BUSY=%lu PHASE=%lu RESULT=%lu RX=%lu "
            "REJECT=%lu CH=3 RESOURCE=2 MTU=96\r\n",
            (unsigned long)request_id, (unsigned long)d.ready, (unsigned long)d.busy,
            (unsigned long)d.phase, (unsigned long)d.result, (unsigned long)d.received,
            (unsigned long)d.rejected);
    } else if (strcmp(args, "CLOSE") == 0) {
        (void)PW_UartFirmwareTransfer_Close();
        (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK FWTRANSFER CLOSING\r\n",
                                     (unsigned long)request_id);
    } else {
        uint8_t bytes[UART_FW_PACKET];
        const size_t n = PW_UartFirmwareTransfer_Unhex(args, bytes, sizeof(bytes));
        if (!n || !PW_UartFirmwareTransfer_Process(bytes, n, 1U)) {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "FWTRANSFER_REJECTED");
            return;
        }
        (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK FWTRANSFER ACCEPTED\r\n",
                                     (unsigned long)request_id);
    }
}
