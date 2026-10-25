/* App A storage/boot_update.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static uint8_t BootMeta_ReadV1(BootMetaV1_t *out)
{
    BootMetaV1_t record;
    const BootMetaV1_t *flash_record =
        (const BootMetaV1_t *)BOOT_META_ADDRESS;
    uint32_t crc;

    if (out == NULL)
    {
        return 0U;
    }

    memcpy(&record, flash_record, sizeof(record));

    if ((record.magic != BOOT_META_MAGIC) ||
        (record.version != BOOT_META_VERSION_V1))
    {
        return 0U;
    }

    if ((record.active_slot != BOOT_SLOT_A) &&
        (record.active_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    crc = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(BootMetaV1_t, crc32));

    if (crc != record.crc32)
    {
        return 0U;
    }

    *out = record;
    return 1U;
}


static uint8_t BootMeta_ReadV2Legacy(BootMetaV2_t *out)
{
    BootMetaV2_t record;
    const BootMetaV2_t *flash_record =
        (const BootMetaV2_t *)BOOT_META_COPY0_ADDRESS;
    uint32_t crc;

    if (out == NULL)
    {
        return 0U;
    }

    memcpy(&record, flash_record, sizeof(record));

    if ((record.magic != BOOT_META_MAGIC) ||
        (record.version != BOOT_META_VERSION_V2))
    {
        return 0U;
    }

    if ((record.confirmed_slot != BOOT_SLOT_A) &&
        (record.confirmed_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    if ((record.pending_slot != BOOT_SLOT_NONE) &&
        (record.pending_slot != BOOT_SLOT_A) &&
        (record.pending_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    if ((record.app_a_size > FW_SLOT_SIZE) ||
        (record.app_b_size > FW_SLOT_SIZE))
    {
        return 0U;
    }

    crc = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(BootMetaV2_t, crc32));

    if (crc != record.crc32)
    {
        return 0U;
    }

    *out = record;
    return 1U;
}


static uint8_t BootMeta_GenerationIsNewer(uint32_t a,
                                          uint32_t b)
{
    return (((int32_t)(a - b)) > 0) ? 1U : 0U;
}


static uint8_t BootMeta_ReadV3At(uint32_t address,
                                 BootMetaV3_t *out)
{
    BootMetaV3_t record;
    uint32_t crc;

    if (out == NULL)
    {
        return 0U;
    }

    if ((address != BOOT_META_COPY0_ADDRESS) &&
        (address != BOOT_META_COPY1_ADDRESS))
    {
        return 0U;
    }

    memcpy(
        &record,
        (const void *)address,
        sizeof(record));

    if ((record.magic != BOOT_META_MAGIC) ||
        (record.version != BOOT_META_VERSION_V3))
    {
        return 0U;
    }

    if ((record.confirmed_slot != BOOT_SLOT_A) &&
        (record.confirmed_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    if ((record.pending_slot != BOOT_SLOT_NONE) &&
        (record.pending_slot != BOOT_SLOT_A) &&
        (record.pending_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    if ((record.app_a_size > FW_SLOT_SIZE) ||
        (record.app_b_size > FW_SLOT_SIZE))
    {
        return 0U;
    }

    crc = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(BootMetaV3_t, crc32));

    if (crc != record.crc32)
    {
        return 0U;
    }

    *out = record;
    return 1U;
}


static uint8_t BootMeta_ReadV3(BootMetaV3_t *out)
{
    BootMetaV3_t copy0;
    BootMetaV3_t copy1;
    uint8_t valid0;
    uint8_t valid1;

    if (out == NULL)
    {
        return 0U;
    }

    valid0 = BootMeta_ReadV3At(
        BOOT_META_COPY0_ADDRESS,
        &copy0);

    valid1 = BootMeta_ReadV3At(
        BOOT_META_COPY1_ADDRESS,
        &copy1);

    if ((valid0 == 0U) && (valid1 == 0U))
    {
        return 0U;
    }

    if ((valid0 != 0U) && (valid1 == 0U))
    {
        *out = copy0;
        return 1U;
    }

    if ((valid0 == 0U) && (valid1 != 0U))
    {
        *out = copy1;
        return 1U;
    }

    if (BootMeta_GenerationIsNewer(
            copy1.generation,
            copy0.generation) != 0U)
    {
        *out = copy1;
    }
    else
    {
        *out = copy0;
    }

    return 1U;
}


static uint8_t BootMeta_SaveV3(const BootMetaV3_t *meta)
{
    BootMetaV3_t record;
    BootMetaV3_t copy0;
    BootMetaV3_t copy1;
    BootMetaV3_t latest;
    BootMetaV3_t verify;
    FLASH_EraseInitTypeDef erase_init;
    uint32_t page_error = 0U;
    uint32_t target_address;
    uint32_t target_page;
    uint32_t offset;
    uint8_t valid0;
    uint8_t valid1;
    uint8_t have_latest = 0U;
    HAL_StatusTypeDef status;

    if (meta == NULL)
    {
        return 0U;
    }

    valid0 = BootMeta_ReadV3At(
        BOOT_META_COPY0_ADDRESS,
        &copy0);

    valid1 = BootMeta_ReadV3At(
        BOOT_META_COPY1_ADDRESS,
        &copy1);

    /*
     * Always erase/program the invalid or older page.
     * The newest valid page remains untouched until the replacement has been
     * fully written and CRC-verified.
     */
    if ((valid0 == 0U) && (valid1 == 0U))
    {
        /*
         * First V3 migration writes Page125 first, preserving the legacy V2
         * record at Page126.
         */
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }
    else if ((valid0 != 0U) && (valid1 == 0U))
    {
        latest = copy0;
        have_latest = 1U;
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }
    else if ((valid0 == 0U) && (valid1 != 0U))
    {
        latest = copy1;
        have_latest = 1U;
        target_address = BOOT_META_COPY0_ADDRESS;
        target_page = BOOT_META_COPY0_PAGE;
    }
    else if (BootMeta_GenerationIsNewer(
                 copy1.generation,
                 copy0.generation) != 0U)
    {
        latest = copy1;
        have_latest = 1U;
        target_address = BOOT_META_COPY0_ADDRESS;
        target_page = BOOT_META_COPY0_PAGE;
    }
    else
    {
        latest = copy0;
        have_latest = 1U;
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }

    record = *meta;

    /*
     * Keep generation monotonic even if a caller forgets to increment it.
     */
    if (have_latest != 0U)
    {
        if (BootMeta_GenerationIsNewer(
                record.generation,
                latest.generation) == 0U)
        {
            record.generation =
                latest.generation + 1UL;
        }
    }
    else if (record.generation == 0UL)
    {
        record.generation = 1UL;
    }

    record.magic = BOOT_META_MAGIC;
    record.version = BOOT_META_VERSION_V3;
    record.crc32 = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(BootMetaV3_t, crc32));

    if (HAL_FLASH_Unlock() != HAL_OK)
    {
        return 0U;
    }

    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    memset(&erase_init, 0, sizeof(erase_init));
    erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_init.Banks = BOOT_META_BANK;
    erase_init.Page = target_page;
    erase_init.NbPages = 1U;

    status = HAL_FLASHEx_Erase(
        &erase_init,
        &page_error);

    if (status == HAL_OK)
    {
        for (offset = 0U;
             offset < sizeof(record);
             offset += 8U)
        {
            uint64_t data64;

            memcpy(
                &data64,
                ((const uint8_t *)&record) + offset,
                sizeof(data64));

            status = HAL_FLASH_Program(
                FLASH_TYPEPROGRAM_DOUBLEWORD,
                target_address + offset,
                data64);

            if (status != HAL_OK)
            {
                break;
            }
        }
    }

    (void)HAL_FLASH_Lock();

    if (status != HAL_OK)
    {
        return 0U;
    }

    if (BootMeta_ReadV3At(
            target_address,
            &verify) == 0U)
    {
        return 0U;
    }

    if (memcmp(
            &verify,
            &record,
            sizeof(record)) != 0)
    {
        return 0U;
    }

    return 1U;
}


static uint8_t BootMeta_EnsureV3(BootMetaV3_t *out)
{
    BootMetaV3_t meta;
    BootMetaV2_t old_v2;
    BootMetaV1_t old_v1;

    if (out == NULL)
    {
        return 0U;
    }

    if (BootMeta_ReadV3(&meta) != 0U)
    {
        *out = meta;
        return 1U;
    }

    memset(&meta, 0, sizeof(meta));
    meta.magic = BOOT_META_MAGIC;
    meta.version = BOOT_META_VERSION_V3;

    /*
     * Preferred migration source is the legacy V2 record, because it already
     * contains confirmed/pending/attempt/image CRC state.
     */
    if (BootMeta_ReadV2Legacy(&old_v2) != 0U)
    {
        meta.confirmed_slot = old_v2.confirmed_slot;
        meta.pending_slot = old_v2.pending_slot;
        meta.attempts_left = old_v2.attempts_left;
        meta.generation = old_v2.generation;
        meta.app_a_size = old_v2.app_a_size;
        meta.app_a_crc32 = old_v2.app_a_crc32;
        meta.app_b_size = old_v2.app_b_size;
        meta.app_b_crc32 = old_v2.app_b_crc32;
        meta.flags = old_v2.flags;
    }
    else
    {
        /*
         * V1 contains only one active slot. If even V1 is absent, the slot
         * that is actually executing is the safest confirmed choice.
         */
        meta.confirmed_slot = APP_THIS_SLOT;
        meta.pending_slot = BOOT_SLOT_NONE;
        meta.attempts_left = 0U;
        meta.generation = 1U;
        meta.flags = 0U;

        if (BootMeta_ReadV1(&old_v1) != 0U)
        {
            (void)old_v1;
        }
    }

    if (BootMeta_SaveV3(&meta) == 0U)
    {
        return 0U;
    }

    if (BootMeta_ReadV3(&meta) == 0U)
    {
        return 0U;
    }

    *out = meta;
    return 1U;
}


static uint8_t BootMailbox_WriteRequest(uint32_t command,
                                        uint32_t target_slot,
                                        uint32_t image_size,
                                        uint32_t image_crc32)
{
    BootMailbox_t request;
    BootMailbox_t verify;
    volatile uint32_t *dst =
        (volatile uint32_t *)BOOT_MAILBOX_ADDRESS;
    const uint32_t *src;
    uint32_t i;

    memset(&request, 0, sizeof(request));

    request.magic = BOOT_MAILBOX_MAGIC;
    request.version = BOOT_MAILBOX_VERSION;
    request.command = command;
    request.requester_slot = APP_THIS_SLOT;
    request.target_slot = target_slot;
    request.image_size = image_size;
    request.image_crc32 = image_crc32;
    request.crc32 = TightenParams_Crc32(
        (const uint8_t *)&request,
        offsetof(BootMailbox_t, crc32));

    src = (const uint32_t *)&request;

    /*
     * Make the mailbox invalid while populating it. Write magic LAST so a
     * reset during the copy cannot create a partially valid command.
     */
    dst[0] = 0UL;
    __DSB();

    for (i = 1UL;
         i < (sizeof(BootMailbox_t) / sizeof(uint32_t));
         i++)
    {
        dst[i] = src[i];
    }

    __DSB();

    dst[0] = src[0];

    __DSB();
    __ISB();

    memcpy(
        &verify,
        (const void *)BOOT_MAILBOX_ADDRESS,
        sizeof(verify));

    if (memcmp(&verify, &request, sizeof(request)) != 0)
    {
        dst[0] = 0UL;
        __DSB();
        return 0U;
    }

    return 1U;
}


static uint8_t BootMailbox_RequestConfirmCurrent(void)
{
    return BootMailbox_WriteRequest(
        BOOT_MAILBOX_CMD_CONFIRM_CURRENT,
        BOOT_SLOT_NONE,
        0UL,
        0UL);
}


static uint8_t BootMailbox_RequestStartTrial(uint32_t target_slot,
                                             uint32_t image_size,
                                             uint32_t image_crc32)
{
    return BootMailbox_WriteRequest(
        BOOT_MAILBOX_CMD_START_TRIAL,
        target_slot,
        image_size,
        image_crc32);
}


static uint8_t BootMailbox_RequestSetConfirmedSlot(uint32_t target_slot)
{
    return BootMailbox_WriteRequest(
        BOOT_MAILBOX_CMD_SET_CONFIRMED_SLOT,
        target_slot,
        0UL,
        0UL);
}


static uint8_t BootMeta_ConfirmCurrent(void)
{
    /*
     * V4: do not erase/program Metadata V3 from the application.
     * Ask the bootloader to commit confirmation after reset.
     */
    return BootMailbox_RequestConfirmCurrent();
}


static uint8_t BootMeta_SaveSlot(uint32_t slot)
{
    if ((slot != BOOT_SLOT_A) &&
        (slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    return BootMailbox_RequestSetConfirmedSlot(slot);
}


static uint8_t Fw_HexNibble(char c, uint8_t *value)
{
    if (value == NULL)
    {
        return 0U;
    }

    if ((c >= '0') && (c <= '9'))
    {
        *value = (uint8_t)(c - '0');
        return 1U;
    }

    if ((c >= 'A') && (c <= 'F'))
    {
        *value = (uint8_t)(c - 'A' + 10);
        return 1U;
    }

    if ((c >= 'a') && (c <= 'f'))
    {
        *value = (uint8_t)(c - 'a' + 10);
        return 1U;
    }

    return 0U;
}


static uint8_t Fw_ParseHexBytes(const char *text,
                                uint8_t *out,
                                uint32_t *out_len)
{
    size_t n;
    uint32_t i;

    if ((text == NULL) ||
        (out == NULL) ||
        (out_len == NULL))
    {
        return 0U;
    }

    n = strlen(text);

    if ((n == 0U) ||
        ((n & 1U) != 0U) ||
        (n > (FW_DATA_MAX_BYTES * 2U)))
    {
        return 0U;
    }

    *out_len = (uint32_t)(n / 2U);

    for (i = 0U; i < *out_len; i++)
    {
        uint8_t hi;
        uint8_t lo;

        if ((Fw_HexNibble(text[i * 2U], &hi) == 0U) ||
            (Fw_HexNibble(text[i * 2U + 1U], &lo) == 0U))
        {
            return 0U;
        }

        out[i] = (uint8_t)((hi << 4U) | lo);
    }

    return 1U;
}


static uint8_t Fw_TargetVectorValid(void)
{
    uint32_t app_msp;
    uint32_t app_reset;

    app_msp =
        *(volatile const uint32_t *)APP_TARGET_ADDRESS;

    app_reset =
        *(volatile const uint32_t *)(APP_TARGET_ADDRESS + 4U);

    if ((app_msp < 0x20000000UL) ||
        (app_msp > 0x20020000UL))
    {
        return 0U;
    }

    if ((app_reset & 1UL) == 0U)
    {
        return 0U;
    }

    app_reset &= ~1UL;

    if ((app_reset < APP_TARGET_ADDRESS) ||
        (app_reset >= APP_TARGET_END))
    {
        return 0U;
    }

    return 1U;
}


static uint8_t Fw_EraseTarget(uint32_t image_size)
{
    FLASH_EraseInitTypeDef erase_init;
    uint32_t page_error = 0U;
    uint32_t pages;
    HAL_StatusTypeDef status;
    HAL_StatusTypeDef lock_status;

    if ((image_size < 8U) || (image_size > FW_SLOT_SIZE))
    {
        return 0U;
    }

    pages = (image_size + FW_FLASH_PAGE_SIZE - 1U) / FW_FLASH_PAGE_SIZE;

    if ((pages == 0U) || (pages > 112U))
    {
        return 0U;
    }

    g_fw_diag_erase_bank = (uint32_t)APP_TARGET_BANK;
    g_fw_diag_erase_page = (uint32_t)APP_TARGET_FIRST_PAGE;
    g_fw_diag_erase_pages = pages;
    g_fw_diag_page_error = 0xFFFFFFFFUL;
    g_fw_diag_flash_error = 0U;
    g_fw_diag_hal_status = (uint32_t)HAL_ERROR;
    g_fw_diag_lock_status = (uint32_t)HAL_ERROR;
    g_fw_diag_stage = 50U;
    Fw_DiagSnapshotComms();

    status = HAL_FLASH_Unlock();
    g_fw_diag_hal_status = (uint32_t)status;
    g_fw_diag_flash_sr = FLASH->SR;
    g_fw_diag_flash_cr = FLASH->CR;

    if (status != HAL_OK)
    {
        g_fw_diag_stage = 90U;
        Fw_DiagSnapshotComms();
        return 0U;
    }

    g_fw_diag_stage = 60U;
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    memset(&erase_init, 0, sizeof(erase_init));
    erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_init.Banks = APP_TARGET_BANK;
    erase_init.Page = APP_TARGET_FIRST_PAGE;
    erase_init.NbPages = pages;

    g_fw_diag_stage = 70U;
    Fw_DiagSnapshotComms();

    status = HAL_FLASHEx_Erase(&erase_init, &page_error);

    g_fw_diag_hal_status = (uint32_t)status;
    g_fw_diag_page_error = page_error;
    g_fw_diag_flash_error = HAL_FLASH_GetError();
    g_fw_diag_flash_sr = FLASH->SR;
    g_fw_diag_flash_cr = FLASH->CR;
    g_fw_diag_stage = 80U;

    lock_status = HAL_FLASH_Lock();
    g_fw_diag_lock_status = (uint32_t)lock_status;
    g_fw_diag_flash_sr = FLASH->SR;
    g_fw_diag_flash_cr = FLASH->CR;
    g_fw_diag_stage = 90U;
    Fw_DiagSnapshotComms();

    if ((status != HAL_OK) || (lock_status != HAL_OK))
    {
        return 0U;
    }

    return 1U;
}


static uint8_t Fw_ProgramData(uint32_t offset,
                              const uint8_t *data,
                              uint32_t length)
{
    uint8_t padded[FW_DATA_MAX_BYTES];
    uint32_t programmed_length;
    uint32_t i;
    HAL_StatusTypeDef status = HAL_OK;

    if ((fw_update.active == 0U) ||
        (data == NULL) ||
        (length == 0U) ||
        (length > FW_DATA_MAX_BYTES))
    {
        return 0U;
    }

    if (offset != fw_update.bytes_received)
    {
        return 0U;
    }

    if ((offset + length) > fw_update.image_size)
    {
        return 0U;
    }

    /*
     * Every non-final packet must be exactly 32 bytes. The last packet may be
     * shorter; it is padded with erased-state 0xFF to a double-word boundary.
     */
    if (((offset + length) != fw_update.image_size) &&
        (length != FW_DATA_MAX_BYTES))
    {
        return 0U;
    }

    if ((offset & 7U) != 0U)
    {
        return 0U;
    }

    memset(padded, 0xFF, sizeof(padded));
    memcpy(padded, data, length);

    programmed_length = (length + 7U) & ~7U;

    if (HAL_FLASH_Unlock() != HAL_OK)
    {
        return 0U;
    }

    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    for (i = 0U; i < programmed_length; i += 8U)
    {
        uint64_t data64;

        memcpy(&data64, &padded[i], sizeof(data64));

        status = HAL_FLASH_Program(
            FLASH_TYPEPROGRAM_DOUBLEWORD,
            fw_update.target_address + offset + i,
            data64);

        if (status != HAL_OK)
        {
            break;
        }
    }

    (void)HAL_FLASH_Lock();

    if (status != HAL_OK)
    {
        return 0U;
    }

    if (memcmp((const void *)(fw_update.target_address + offset),
               data,
               length) != 0)
    {
        return 0U;
    }

    fw_update.bytes_received += length;
    return 1U;
}

/* pw_transfer resource 2 reuses the proven inactive-slot writer. */
uint8_t PW_TransferFlash_IsActive(void)
{
    return fw_update.active;
}

uint32_t PW_TransferFlash_ExpectedOffset(void)
{
    return fw_update.bytes_received;
}

uint32_t PW_TransferFlash_ImageSize(void)
{
    return fw_update.image_size;
}

uint8_t PW_TransferFlash_Write(uint32_t offset,
                              const uint8_t *data,
                              uint32_t length)
{
    return Fw_ProgramData(offset, data, length);
}


static uint32_t Fw_TargetCrc32(uint32_t image_size)
{
    return TightenParams_Crc32(
        (const uint8_t *)APP_TARGET_ADDRESS,
        image_size);
}

#if defined(UART_FIRMWARE_TRANSFER)
#include "uart_firmware_transfer_port.inc"
#endif


static void Fw_EnterSafeState(void)
{
    tightening_start_request = 0U;
    tightening_stop_request = 0U;

    MotorControl_SetIdle();

    foc_enable = 0U;
    foc_id_ref_A = 0.0f;
    foc_iq_ref_A = 0.0f;

    PowerStage_Disable();
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
}


static void Fw_DiagSnapshotComms(void)
{
    g_fw_diag_uart_rx_dma_state = UART_RxDma_GetDmaState();
    g_fw_diag_uart_rx_dma_remaining = UART_RxDma_GetDmaRemaining();
    g_fw_diag_uart_rx_state = UART_RxDma_GetUartRxState();
    g_fw_diag_uart_cr3 = UART_RxDma_GetUartCr3();
    g_fw_diag_uart_rx_errors = UART_RxDma_GetErrorCount();
    g_fw_diag_uart_rx_last_error = UART_RxDma_GetLastError();
    g_fw_diag_uart_rx_restarts = UART_RxDma_GetRestartCount();
    g_fw_diag_uart_rx_restart_failures = UART_RxDma_GetRestartFailureCount();
    g_fw_diag_uart_tx_queued = (uint32_t)UART_Async_GetQueuedBytes();
    g_fw_diag_uart_tx_dropped = UART_Async_GetDroppedBytes();
    g_fw_diag_uart_tx_dma_errors = UART_Async_GetDmaErrorCount();

    if ((hlpuart1.hdmarx != NULL) && (hlpuart1.hdmarx->Instance != NULL))
    {
        g_fw_diag_uart_rx_dma_ccr = hlpuart1.hdmarx->Instance->CCR;
    }
    else
    {
        g_fw_diag_uart_rx_dma_ccr = 0U;
    }
}


static void Fw_ResetContext(void)
{
    memset(&fw_update, 0, sizeof(fw_update));
    fw_update.target_slot = APP_TARGET_SLOT;
    fw_update.target_address = APP_TARGET_ADDRESS;
}


static uint8_t BootHealth_IsCurrentTrial(void)
{
    BootMetaV2_t meta;

    if (BootMeta_ReadV3(&meta) == 0U)
    {
        return 0U;
    }

    /*
     * The current APP is a trial only while it is the pending slot and the
     * last confirmed slot is still the opposite image.
     */
    if ((meta.pending_slot == APP_THIS_SLOT) &&
        (meta.confirmed_slot != APP_THIS_SLOT))
    {
        return 1U;
    }

    return 0U;
}


static void Fw_SendStatus(uint32_t request_id)
{
    BootMetaV2_t meta;
    char msg[384];

    if (BootMeta_ReadV3(&meta) != 0U)
    {
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK FW CURRENT=%c TARGET=%c ACTIVE=%u RX=%lu SIZE=%lu "
            "EXPECT=0x%08lX CONFIRMED=%c PENDING=%c ATTEMPTS=%lu GEN=%lu "
            "HTRIAL=%u HOK=%u HSTABLE=%lums HELAPSED=%lums "
            "HFAIL=0x%03lX HADC=%lu HFOC=%lu HSAMPLE=%lu\r\n",
            (unsigned long)request_id,
            (APP_THIS_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
            (APP_TARGET_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
            (unsigned int)fw_update.active,
            (unsigned long)fw_update.bytes_received,
            (unsigned long)fw_update.image_size,
            (unsigned long)fw_update.expected_crc32,
            (meta.confirmed_slot == BOOT_SLOT_A) ? 'A' : 'B',
            (meta.pending_slot == BOOT_SLOT_A) ? 'A' :
            (meta.pending_slot == BOOT_SLOT_B) ? 'B' : '-',
            (unsigned long)meta.attempts_left,
            (unsigned long)meta.generation,
            (unsigned int)boot_health_trial_active,
            (unsigned int)boot_health_last_sample_ok,
            (unsigned long)boot_health_stable_ms,
            (unsigned long)boot_health_elapsed_ms,
            (unsigned long)g_boot_health_fail_mask,
            (unsigned long)g_boot_health_last_adc_delta,
            (unsigned long)g_boot_health_last_foc_delta,
            (unsigned long)g_boot_health_sample_count);
    }
    else
    {
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK FW CURRENT=%c TARGET=%c ACTIVE=%u RX=%lu SIZE=%lu "
            "EXPECT=0x%08lX META=V1_OR_INVALID\r\n",
            (unsigned long)request_id,
            (APP_THIS_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
            (APP_TARGET_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
            (unsigned int)fw_update.active,
            (unsigned long)fw_update.bytes_received,
            (unsigned long)fw_update.image_size,
            (unsigned long)fw_update.expected_crc32);
    }


}

static void TightenParams_PrintAll(uint32_t request_id)
{
    TightenParams_EmitAllFormatted(&recipe_state, request_id, Protocol_SendFormatted);
}


static uint8_t TightenParams_GetOne(
    uint32_t request_id,
    const char *name)
{
    char msg[128];
    uint32_t value = 0U;

    if (TightenParams_TryGet(&recipe_state.params, name, &value) !=
        TIGHTEN_PARAMS_OK)
    {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                           "UNKNOWN_PARAM");
        return 0U;
    }

    (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK GET %s=%lu\r\n",
             (unsigned long)request_id, name, (unsigned long)value);
    return 1U;
}


static uint8_t TightenParams_SetOne(
    uint32_t request_id,
    const char *name,
    uint32_t value)
{
    char msg[144];
    TightenParamsResult_t result = TightenParams_TrySet(
        &recipe_state.params, name, value,
        ((Tightening_IsBusy() != 0U) ||
         (tightening_start_request != 0U)) ? 1U : 0U);

    if (result == TIGHTEN_PARAMS_BUSY)
    {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        return 0U;
    }
    if (result == TIGHTEN_PARAMS_OUT_OF_RANGE)
    {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                           "VALUE_OUT_OF_RANGE");
        return 0U;
    }
    if (result != TIGHTEN_PARAMS_OK)
    {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                           "UNKNOWN_PARAM");
        return 0U;
    }

    recipe_state.dirty = 1U;
    (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK SET %s=%lu DIRTY=1\r\n",
             (unsigned long)request_id, name, (unsigned long)value);
    return 1U;
}


#if defined(TIGHTEN_SYNTHETIC_BENCH)
#include "tighten_synthetic_port.inc"
#endif
