/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : A/B IAP Bootloader V3 - dual-copy power-loss-safe metadata
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stddef.h>
#include <string.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
/*
 * V1 metadata is retained only for backward compatibility with the
 * already-working APP A/B builds.
 *
 * Layout at 0x0807F000:
 *   magic, version=1, active_slot, crc32
 */
typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;
    uint32_t active_slot;
    uint32_t crc32;
} BootMetaV1_t;

/*
 * V2 metadata adds trial-boot / rollback state and per-slot image CRC data.
 *
 * confirmed_slot:
 *   Last application that has explicitly confirmed successful startup.
 *
 * pending_slot:
 *   Newly downloaded application to try on the next reset.
 *   BOOT_SLOT_NONE means no trial is pending.
 *
 * attempts_left:
 *   Before every pending-slot trial the bootloader DECREMENTS this value
 *   and saves metadata before jumping. If the new APP keeps resetting before
 *   confirmation, the counter eventually reaches 0 and the bootloader falls
 *   back to confirmed_slot.
 *
 * app_[ab]_size / app_[ab]_crc32:
 *   size==0 means "legacy/vector-only validation".
 *   size>0 enables full-image CRC32 validation before boot.
 *
 * generation:
 *   Monotonic metadata write counter reserved for diagnostics / later journal.
 *
 * flags:
 *   Reserved for future use; write 0 for now.
 */
typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;

    uint32_t confirmed_slot;
    uint32_t pending_slot;
    uint32_t attempts_left;
    uint32_t generation;

    uint32_t app_a_size;
    uint32_t app_a_crc32;
    uint32_t app_b_size;
    uint32_t app_b_crc32;

    uint32_t flags;
    uint32_t crc32;
} BootMetaV2_t;

/*
 * V3 intentionally keeps the V2 payload layout unchanged.
 *
 * The V3 upgrade is about STORAGE SEMANTICS:
 *   - two independent erase pages,
 *   - CRC32 on each copy,
 *   - generation selects the newest valid copy,
 *   - only the older/invalid page is erased during an update.
 *
 * Keeping the payload layout identical makes migration from V2 simple and
 * preserves all already-proven trial/rollback/image-CRC fields.
 */
typedef BootMetaV2_t BootMetaV3_t;

/*
 * SRAM mailbox shared by APP A/B and the bootloader.
 *
 * IMPORTANT:
 * The top 64 bytes of SRAM are reserved by the linker in BOTH the
 * bootloader and APP projects:
 *
 *   0x2001FFC0 .. 0x2001FFFF
 *
 * The APP writes a request, then performs NVIC_SystemReset().
 * The bootloader validates the mailbox and performs the Metadata V3 flash
 * update while executing from Bank1 boot flash.
 */
typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;
    uint32_t command;
    uint32_t requester_slot;
    uint32_t target_slot;
    uint32_t image_size;
    uint32_t image_crc32;
    uint32_t crc32;
} BootMailbox_t;

typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t boot_count;
    uint32_t last_target;
    uint32_t previous_target;
    uint32_t reset_flags;
    uint32_t confirmed_slot;
    uint32_t pending_slot;
    uint32_t attempts_left;
} BootTrace_t;

typedef void (*AppEntry_t)(void);
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* -------------------------------------------------------------------------- */
/* Flash map                                                                  */
/* -------------------------------------------------------------------------- */
#define APP_A_ADDRESS           (0x08008000UL)
#define APP_A_END               (0x08040000UL)

#define APP_B_ADDRESS           (0x08040000UL)
#define APP_B_END               (0x08078000UL)

/*
 * Power-loss-safe metadata V3 uses TWO independent erase pages.
 *
 * Copy 0 keeps the historical metadata address so old APP V1/V2 firmware can
 * continue writing there during the staged migration.
 *
 * Copy 1 is taken from the previously reserved region.
 *
 * Bank2 page map:
 *   Page125 : 0x0807E800..0x0807EFFF  Metadata V3 copy 1
 *   Page126 : 0x0807F000..0x0807F7FF  Metadata V3 copy 0 / legacy V1/V2
 *   Page127 : 0x0807F800..0x0807FFFF  Parameter record (unchanged)
 */
#define BOOT_META_COPY0_ADDRESS (0x0807F000UL)
#define BOOT_META_COPY0_PAGE    (126U)

#define BOOT_META_COPY1_ADDRESS (0x0807E800UL)
#define BOOT_META_COPY1_PAGE    (125U)

#define BOOT_META_BANK          FLASH_BANK_2

/*
 * Legacy V2 helper compatibility:
 * Boot_SaveMetadataV2() is intentionally kept during staged migration and
 * still writes the historical single-copy metadata page (copy0 / Page126).
 */
#define BOOT_META_PAGE          BOOT_META_COPY0_PAGE

/* Legacy APP V1/V2 always used this address. */
#define BOOT_META_ADDRESS       BOOT_META_COPY0_ADDRESS

#define BOOT_META_MAGIC         (0x424F4F54UL)  /* "BOOT" */

#define BOOT_META_VERSION_V1    (1UL)
#define BOOT_META_VERSION_V2    (2UL)
#define BOOT_META_VERSION_V3    (3UL)

#define BOOT_SLOT_NONE          (0UL)
#define BOOT_SLOT_A             (1UL)
#define BOOT_SLOT_B             (2UL)

/*
 * Application-side FW END will normally create a V2 record with 2 attempts.
 * Bootloader itself does not invent a new pending slot; it only consumes it.
 */
#define BOOT_TRIAL_DEFAULT_ATTEMPTS (2UL)

/* STM32G474RE SRAM: 0x20000000 .. 0x2001FFFF, top-of-stack may be 0x20020000. */
#define SRAM_START_ADDRESS      (0x20000000UL)
#define SRAM_END_EXCLUSIVE      (0x20020000UL)

/* -------------------------------------------------------------------------- */
/* APP -> Bootloader SRAM mailbox                                             */
/* -------------------------------------------------------------------------- */
#define BOOT_MAILBOX_ADDRESS        (0x2001FFC0UL)
#define BOOT_MAILBOX_RESERVED_BYTES (64UL)

#define BOOT_MAILBOX_MAGIC          (0x584F424DUL) /* "MBOX" in little endian */
#define BOOT_MAILBOX_VERSION        (1UL)

#define BOOT_MAILBOX_CMD_NONE               (0UL)
#define BOOT_MAILBOX_CMD_CONFIRM_CURRENT    (1UL)
#define BOOT_MAILBOX_CMD_START_TRIAL        (2UL)
#define BOOT_MAILBOX_CMD_SET_CONFIRMED_SLOT (3UL)

#define BOOT_TRACE_ADDRESS (BOOT_MAILBOX_ADDRESS + sizeof(BootMailbox_t))
#define BOOT_TRACE_MAGIC   (0x45435254UL) /* "TRCE" */

_Static_assert(sizeof(BootMailbox_t) <= BOOT_MAILBOX_RESERVED_BYTES,
               "BootMailbox_t exceeds reserved SRAM mailbox");
_Static_assert((sizeof(BootMailbox_t) + sizeof(BootTrace_t)) <=
               BOOT_MAILBOX_RESERVED_BYTES,
               "Boot mailbox + trace exceed reserved SRAM");

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */
/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN PV */
volatile uint32_t g_boot_diag_rollback_commit_attempts = 0U;
volatile uint32_t g_boot_diag_rollback_commit_ok = 0U;
volatile uint32_t g_boot_diag_rollback_pending_slot = BOOT_SLOT_NONE;
volatile uint32_t g_boot_diag_rollback_generation_before = 0U;
volatile uint32_t g_boot_diag_rollback_generation_after = 0U;
volatile uint32_t g_boot_diag_trial_commit_attempts = 0U;
volatile uint32_t g_boot_diag_trial_commit_ok = 0U;
volatile uint32_t g_boot_diag_trial_attempts_before = 0U;
volatile uint32_t g_boot_diag_trial_attempts_after = 0U;
volatile uint32_t g_boot_diag_meta_save_stage = 0U;
volatile HAL_StatusTypeDef g_boot_diag_meta_hal_status = HAL_OK;
volatile HAL_StatusTypeDef g_boot_diag_meta_lock_status = HAL_OK;
volatile uint32_t g_boot_diag_meta_page_error = 0xFFFFFFFFUL;
volatile uint32_t g_boot_diag_meta_flash_error = 0U;
volatile uint32_t g_boot_diag_meta_flash_sr = 0U;
volatile uint32_t g_boot_diag_meta_flash_cr = 0U;
volatile uint32_t g_boot_diag_meta_target_address = 0U;
volatile uint32_t g_boot_diag_meta_target_page = 0U;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
static uint32_t Boot_CRC32(const uint8_t *data, uint32_t len);

static uint32_t Boot_SlotBase(uint32_t slot);
static uint32_t Boot_SlotEnd(uint32_t slot);

static int Boot_IsAppVectorValid(uint32_t app_address,
                                 uint32_t app_end);

static int Boot_IsSlotImageValidV2(uint32_t slot,
                                   const BootMetaV2_t *meta);

static void Boot_JumpToApp(uint32_t app_address);

static int Boot_ReadMetadataV1(BootMetaV1_t *out);
static int Boot_ReadMetadataV2(BootMetaV2_t *out);
static int Boot_SaveMetadataV2(const BootMetaV2_t *meta);

static int Boot_GenerationIsNewer(uint32_t a, uint32_t b);
static int Boot_ReadMetadataV3At(uint32_t address, BootMetaV3_t *out);
static int Boot_ReadMetadataV3(BootMetaV3_t *out, uint32_t *source_address);
static int Boot_SaveMetadataV3(const BootMetaV3_t *meta);
static int Boot_CommitPendingClearV3(BootMetaV3_t *meta,
                                     int clear_pending_image);
static int Boot_CommitTrialAttemptV3(BootMetaV3_t *meta);
static void Boot_ConvertV2ToV3(const BootMetaV2_t *old_meta,
                               BootMetaV3_t *new_meta);
static void Boot_ConvertV1ToV3(const BootMetaV1_t *old_meta,
                               BootMetaV3_t *new_meta);

static int Boot_MailboxRead(BootMailbox_t *out);
static void Boot_MailboxClear(void);
static int Boot_ProcessMailbox(BootMetaV3_t *meta);
static void Boot_TraceBegin(void);
static void Boot_TraceMetadata(const BootMetaV3_t *meta);
static void Boot_TraceTarget(uint32_t app_address);

static void Boot_RunFromV1(const BootMetaV1_t *meta);
static void Boot_RunFromV2(BootMetaV2_t *meta);
static void Boot_RunFromV3(BootMetaV3_t *meta);
static void Boot_RunFallback(void);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

static uint32_t Boot_CRC32(const uint8_t *data, uint32_t len)
{
    uint32_t crc = 0xFFFFFFFFUL;
    uint32_t i;
    uint32_t j;

    if (data == NULL)
    {
        return 0U;
    }

    for (i = 0U; i < len; i++)
    {
        crc ^= (uint32_t)data[i];

        for (j = 0U; j < 8U; j++)
        {
            if ((crc & 1UL) != 0U)
            {
                crc = (crc >> 1U) ^ 0xEDB88320UL;
            }
            else
            {
                crc >>= 1U;
            }
        }
    }

    return crc ^ 0xFFFFFFFFUL;
}


static void Boot_TraceBegin(void)
{
    BootTrace_t trace;
    volatile uint32_t *dst =
        (volatile uint32_t *)BOOT_TRACE_ADDRESS;
    uint32_t i;

    memcpy(&trace, (const void *)BOOT_TRACE_ADDRESS, sizeof(trace));

    if (trace.magic == BOOT_TRACE_MAGIC)
    {
        trace.previous_target = trace.last_target;
        trace.boot_count++;
    }
    else
    {
        memset(&trace, 0, sizeof(trace));
        trace.magic = BOOT_TRACE_MAGIC;
        trace.boot_count = 1U;
    }

    trace.last_target = BOOT_SLOT_NONE;
    trace.reset_flags = RCC->CSR;

    for (i = 1U; i < (sizeof(trace) / sizeof(uint32_t)); i++)
    {
        dst[i] = ((const uint32_t *)&trace)[i];
    }

    dst[0] = trace.magic;
    __DSB();
    __ISB();

    __HAL_RCC_CLEAR_RESET_FLAGS();
}


static void Boot_TraceMetadata(const BootMetaV3_t *meta)
{
    volatile BootTrace_t *trace =
        (volatile BootTrace_t *)BOOT_TRACE_ADDRESS;

    if ((meta == NULL) || (trace->magic != BOOT_TRACE_MAGIC))
    {
        return;
    }

    trace->confirmed_slot = meta->confirmed_slot;
    trace->pending_slot = meta->pending_slot;
    trace->attempts_left = meta->attempts_left;
    __DSB();
}


static void Boot_TraceTarget(uint32_t app_address)
{
    volatile BootTrace_t *trace =
        (volatile BootTrace_t *)BOOT_TRACE_ADDRESS;

    if (trace->magic != BOOT_TRACE_MAGIC)
    {
        return;
    }

    if (app_address == APP_A_ADDRESS)
    {
        trace->last_target = BOOT_SLOT_A;
    }
    else if (app_address == APP_B_ADDRESS)
    {
        trace->last_target = BOOT_SLOT_B;
    }
    else
    {
        trace->last_target = BOOT_SLOT_NONE;
    }

    __DSB();
    __ISB();
}


static uint32_t Boot_SlotBase(uint32_t slot)
{
    if (slot == BOOT_SLOT_A)
    {
        return APP_A_ADDRESS;
    }

    if (slot == BOOT_SLOT_B)
    {
        return APP_B_ADDRESS;
    }

    return 0U;
}


static uint32_t Boot_SlotEnd(uint32_t slot)
{
    if (slot == BOOT_SLOT_A)
    {
        return APP_A_END;
    }

    if (slot == BOOT_SLOT_B)
    {
        return APP_B_END;
    }

    return 0U;
}


static int Boot_IsAppVectorValid(uint32_t app_address,
                                 uint32_t app_end)
{
    uint32_t app_msp;
    uint32_t app_reset;

    if ((app_address == 0U) ||
        (app_end <= app_address))
    {
        return 0;
    }

    app_msp =
        *(volatile const uint32_t *)app_address;

    app_reset =
        *(volatile const uint32_t *)(app_address + 4U);

    /*
     * _estack = 0x20020000 is legal because MSP may point one byte beyond
     * the highest implemented SRAM address.
     */
    if ((app_msp < SRAM_START_ADDRESS) ||
        (app_msp > SRAM_END_EXCLUSIVE))
    {
        return 0;
    }

    /* Cortex-M reset handler must have Thumb bit set. */
    if ((app_reset & 1UL) == 0U)
    {
        return 0;
    }

    app_reset &= ~1UL;

    if ((app_reset < app_address) ||
        (app_reset >= app_end))
    {
        return 0;
    }

    return 1;
}


static int Boot_IsSlotImageValidV2(uint32_t slot,
                                   const BootMetaV2_t *meta)
{
    uint32_t base;
    uint32_t end;
    uint32_t image_size;
    uint32_t expected_crc;
    uint32_t actual_crc;

    if (meta == NULL)
    {
        return 0;
    }

    base = Boot_SlotBase(slot);
    end  = Boot_SlotEnd(slot);

    if (Boot_IsAppVectorValid(base, end) == 0)
    {
        return 0;
    }

    if (slot == BOOT_SLOT_A)
    {
        image_size   = meta->app_a_size;
        expected_crc = meta->app_a_crc32;
    }
    else if (slot == BOOT_SLOT_B)
    {
        image_size   = meta->app_b_size;
        expected_crc = meta->app_b_crc32;
    }
    else
    {
        return 0;
    }

    /*
     * Transition compatibility:
     * size==0 means this slot predates image CRC metadata.
     * Vector validation still applies.
     */
    if (image_size == 0U)
    {
        return 1;
    }

    if ((image_size < 8U) ||
        (image_size > (end - base)))
    {
        return 0;
    }

    actual_crc = Boot_CRC32(
        (const uint8_t *)base,
        image_size);

    if (actual_crc != expected_crc)
    {
        return 0;
    }

    return 1;
}


static void Boot_JumpToApp(uint32_t app_address)
{
    uint32_t app_msp;
    uint32_t app_reset;
    AppEntry_t app_entry;
    uint32_t i;

    app_msp =
        *(volatile const uint32_t *)app_address;

    app_reset =
        *(volatile const uint32_t *)(app_address + 4U);

    app_entry = (AppEntry_t)app_reset;

    Boot_TraceTarget(app_address);

    __disable_irq();

    /*
     * Stop SysTick and remove pending RTOS-related exceptions left by the
     * bootloader/HAL environment.
     */
    SysTick->CTRL = 0U;
    SysTick->LOAD = 0U;
    SysTick->VAL  = 0U;

    SCB->ICSR =
        SCB_ICSR_PENDSTCLR_Msk |
        SCB_ICSR_PENDSVCLR_Msk;

    /*
     * Cortex-M4 NVIC has more words than this device uses; eight words cover
     * all external interrupt lines exposed by STM32G4 here.
     */
    for (i = 0U; i < 8U; i++)
    {
        NVIC->ICER[i] = 0xFFFFFFFFUL;
        NVIC->ICPR[i] = 0xFFFFFFFFUL;
    }

    HAL_RCC_DeInit();
    HAL_DeInit();

    SCB->VTOR = app_address;

    __DSB();
    __ISB();

    __set_CONTROL(0U);
    __set_PSP(0U);
    __set_MSP(app_msp);

    __DSB();
    __ISB();

    /*
     * Important: the APP expects interrupts/SysTick to work during HAL/RTOS
     * startup, so do not enter the APP with PRIMASK still set.
     */
    __enable_irq();

    app_entry();

    while (1)
    {
    }
}


static int Boot_ReadMetadataV1(BootMetaV1_t *out)
{
    BootMetaV1_t meta;
    const BootMetaV1_t *flash_meta =
        (const BootMetaV1_t *)BOOT_META_ADDRESS;
    uint32_t crc;

    if (out == NULL)
    {
        return 0;
    }

    memcpy(&meta, flash_meta, sizeof(meta));

    if (meta.magic != BOOT_META_MAGIC)
    {
        return 0;
    }

    if (meta.version != BOOT_META_VERSION_V1)
    {
        return 0;
    }

    if ((meta.active_slot != BOOT_SLOT_A) &&
        (meta.active_slot != BOOT_SLOT_B))
    {
        return 0;
    }

    crc = Boot_CRC32(
        (const uint8_t *)&meta,
        offsetof(BootMetaV1_t, crc32));

    if (crc != meta.crc32)
    {
        return 0;
    }

    *out = meta;
    return 1;
}


static int Boot_ReadMetadataV2(BootMetaV2_t *out)
{
    BootMetaV2_t meta;
    const BootMetaV2_t *flash_meta =
        (const BootMetaV2_t *)BOOT_META_ADDRESS;
    uint32_t crc;

    if (out == NULL)
    {
        return 0;
    }

    memcpy(&meta, flash_meta, sizeof(meta));

    if (meta.magic != BOOT_META_MAGIC)
    {
        return 0;
    }

    if (meta.version != BOOT_META_VERSION_V2)
    {
        return 0;
    }

    if ((meta.confirmed_slot != BOOT_SLOT_A) &&
        (meta.confirmed_slot != BOOT_SLOT_B))
    {
        return 0;
    }

    if ((meta.pending_slot != BOOT_SLOT_NONE) &&
        (meta.pending_slot != BOOT_SLOT_A) &&
        (meta.pending_slot != BOOT_SLOT_B))
    {
        return 0;
    }

    if (meta.attempts_left > 100UL)
    {
        return 0;
    }

    if (meta.app_a_size > (APP_A_END - APP_A_ADDRESS))
    {
        return 0;
    }

    if (meta.app_b_size > (APP_B_END - APP_B_ADDRESS))
    {
        return 0;
    }

    crc = Boot_CRC32(
        (const uint8_t *)&meta,
        offsetof(BootMetaV2_t, crc32));

    if (crc != meta.crc32)
    {
        return 0;
    }

    *out = meta;
    return 1;
}


static int Boot_SaveMetadataV2(const BootMetaV2_t *meta)
{
    BootMetaV2_t record;
    BootMetaV2_t verify;
    FLASH_EraseInitTypeDef erase_init;
    HAL_StatusTypeDef status;
    uint32_t page_error = 0U;
    uint32_t offset;

    if (meta == NULL)
    {
        return 0;
    }

    record = *meta;

    record.magic   = BOOT_META_MAGIC;
    record.version = BOOT_META_VERSION_V2;
    record.crc32   = Boot_CRC32(
        (const uint8_t *)&record,
        offsetof(BootMetaV2_t, crc32));

    if (HAL_FLASH_Unlock() != HAL_OK)
    {
        return 0;
    }

    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    memset(&erase_init, 0, sizeof(erase_init));
    erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_init.Banks     = BOOT_META_BANK;
    erase_init.Page      = BOOT_META_PAGE;
    erase_init.NbPages   = 1U;

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
                BOOT_META_ADDRESS + offset,
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
        return 0;
    }

    /*
     * Verify the full record through the same parser/CRC path used at boot.
     */
    if (Boot_ReadMetadataV2(&verify) == 0)
    {
        return 0;
    }

    if (memcmp(&verify, &record, sizeof(record)) != 0)
    {
        return 0;
    }

    return 1;
}


static int Boot_GenerationIsNewer(uint32_t a, uint32_t b)
{
    /*
     * Wrap-around-safe comparison as long as two valid generations are never
     * separated by >= 2^31 updates, which is far beyond this application's
     * realistic metadata write count.
     */
    return (((int32_t)(a - b)) > 0) ? 1 : 0;
}


static int Boot_ReadMetadataV3At(uint32_t address,
                                 BootMetaV3_t *out)
{
    BootMetaV3_t meta;
    uint32_t crc;

    if (out == NULL)
    {
        return 0;
    }

    if ((address != BOOT_META_COPY0_ADDRESS) &&
        (address != BOOT_META_COPY1_ADDRESS))
    {
        return 0;
    }

    memcpy(
        &meta,
        (const void *)address,
        sizeof(meta));

    if ((meta.magic != BOOT_META_MAGIC) ||
        (meta.version != BOOT_META_VERSION_V3))
    {
        return 0;
    }

    if ((meta.confirmed_slot != BOOT_SLOT_A) &&
        (meta.confirmed_slot != BOOT_SLOT_B))
    {
        return 0;
    }

    if ((meta.pending_slot != BOOT_SLOT_NONE) &&
        (meta.pending_slot != BOOT_SLOT_A) &&
        (meta.pending_slot != BOOT_SLOT_B))
    {
        return 0;
    }

    if (meta.attempts_left > 100UL)
    {
        return 0;
    }

    if (meta.app_a_size > (APP_A_END - APP_A_ADDRESS))
    {
        return 0;
    }

    if (meta.app_b_size > (APP_B_END - APP_B_ADDRESS))
    {
        return 0;
    }

    crc = Boot_CRC32(
        (const uint8_t *)&meta,
        offsetof(BootMetaV3_t, crc32));

    if (crc != meta.crc32)
    {
        return 0;
    }

    *out = meta;
    return 1;
}


static int Boot_ReadMetadataV3(BootMetaV3_t *out,
                               uint32_t *source_address)
{
    BootMetaV3_t copy0;
    BootMetaV3_t copy1;
    int valid0;
    int valid1;

    if (out == NULL)
    {
        return 0;
    }

    valid0 = Boot_ReadMetadataV3At(
        BOOT_META_COPY0_ADDRESS,
        &copy0);

    valid1 = Boot_ReadMetadataV3At(
        BOOT_META_COPY1_ADDRESS,
        &copy1);

    if ((valid0 == 0) && (valid1 == 0))
    {
        return 0;
    }

    if ((valid0 != 0) && (valid1 == 0))
    {
        *out = copy0;

        if (source_address != NULL)
        {
            *source_address = BOOT_META_COPY0_ADDRESS;
        }

        return 1;
    }

    if ((valid0 == 0) && (valid1 != 0))
    {
        *out = copy1;

        if (source_address != NULL)
        {
            *source_address = BOOT_META_COPY1_ADDRESS;
        }

        return 1;
    }

    /*
     * Both copies are valid. The newer generation wins.
     *
     * Equal generations should not normally happen; choosing copy0 gives a
     * deterministic recovery rule if it ever does.
     */
    if (Boot_GenerationIsNewer(
            copy1.generation,
            copy0.generation) != 0)
    {
        *out = copy1;

        if (source_address != NULL)
        {
            *source_address = BOOT_META_COPY1_ADDRESS;
        }
    }
    else
    {
        *out = copy0;

        if (source_address != NULL)
        {
            *source_address = BOOT_META_COPY0_ADDRESS;
        }
    }

    return 1;
}


static int Boot_SaveMetadataV3(const BootMetaV3_t *meta)
{
    BootMetaV3_t record;
    BootMetaV3_t copy0;
    BootMetaV3_t copy1;
    BootMetaV3_t latest;
    BootMetaV3_t verify;
    FLASH_EraseInitTypeDef erase_init;
    HAL_StatusTypeDef status;
    HAL_StatusTypeDef lock_status;
    uint32_t page_error = 0xFFFFFFFFUL;
    uint32_t target_address;
    uint32_t target_page;
    uint32_t offset;
    int valid0;
    int valid1;
    int have_latest = 0;

    if (meta == NULL)
    {
        return 0;
    }

    g_boot_diag_meta_save_stage = 10U;
    g_boot_diag_meta_hal_status = HAL_OK;
    g_boot_diag_meta_lock_status = HAL_OK;
    g_boot_diag_meta_page_error = 0xFFFFFFFFUL;
    g_boot_diag_meta_flash_error = HAL_FLASH_GetError();
    g_boot_diag_meta_flash_sr = FLASH->SR;
    g_boot_diag_meta_flash_cr = FLASH->CR;

    valid0 = Boot_ReadMetadataV3At(
        BOOT_META_COPY0_ADDRESS,
        &copy0);

    valid1 = Boot_ReadMetadataV3At(
        BOOT_META_COPY1_ADDRESS,
        &copy1);

    /*
     * Choose only the invalid/older copy as the erase target.
     * The newest known-good page remains untouched until the replacement has
     * been completely programmed and verified.
     *
     * If no V3 copy exists yet, write COPY1 first. This deliberately preserves
     * the old V1/V2 record at COPY0 during migration.
     */
    if ((valid0 == 0) && (valid1 == 0))
    {
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }
    else if ((valid0 != 0) && (valid1 == 0))
    {
        latest = copy0;
        have_latest = 1;
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }
    else if ((valid0 == 0) && (valid1 != 0))
    {
        latest = copy1;
        have_latest = 1;
        target_address = BOOT_META_COPY0_ADDRESS;
        target_page = BOOT_META_COPY0_PAGE;
    }
    else if (Boot_GenerationIsNewer(
                 copy1.generation,
                 copy0.generation) != 0)
    {
        latest = copy1;
        have_latest = 1;
        target_address = BOOT_META_COPY0_ADDRESS;
        target_page = BOOT_META_COPY0_PAGE;
    }
    else
    {
        latest = copy0;
        have_latest = 1;
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }

    record = *meta;

    /*
     * Protect monotonic ordering even if a caller forgets to increment the
     * generation field before saving.
     */
    if (have_latest != 0)
    {
        if (Boot_GenerationIsNewer(
                record.generation,
                latest.generation) == 0)
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
    record.crc32 = Boot_CRC32(
        (const uint8_t *)&record,
        offsetof(BootMetaV3_t, crc32));

    g_boot_diag_meta_target_address = target_address;
    g_boot_diag_meta_target_page = target_page;

    status = HAL_FLASH_Unlock();
    g_boot_diag_meta_hal_status = status;
    g_boot_diag_meta_flash_error = HAL_FLASH_GetError();
    g_boot_diag_meta_flash_sr = FLASH->SR;
    g_boot_diag_meta_flash_cr = FLASH->CR;

    if (status != HAL_OK)
    {
        return 0;
    }

    g_boot_diag_meta_save_stage = 20U;

    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    memset(&erase_init, 0, sizeof(erase_init));
    erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_init.Banks = BOOT_META_BANK;
    erase_init.Page = target_page;
    erase_init.NbPages = 1U;

    status = HAL_FLASHEx_Erase(
        &erase_init,
        &page_error);

    g_boot_diag_meta_hal_status = status;
    g_boot_diag_meta_page_error = page_error;
    g_boot_diag_meta_flash_error = HAL_FLASH_GetError();
    g_boot_diag_meta_flash_sr = FLASH->SR;
    g_boot_diag_meta_flash_cr = FLASH->CR;

    if (status == HAL_OK)
    {
        g_boot_diag_meta_save_stage = 30U;
    }

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

    g_boot_diag_meta_hal_status = status;
    g_boot_diag_meta_flash_error = HAL_FLASH_GetError();
    g_boot_diag_meta_flash_sr = FLASH->SR;
    g_boot_diag_meta_flash_cr = FLASH->CR;

    if (status == HAL_OK)
    {
        g_boot_diag_meta_save_stage = 40U;
    }

    lock_status = HAL_FLASH_Lock();
    g_boot_diag_meta_lock_status = lock_status;
    g_boot_diag_meta_flash_sr = FLASH->SR;
    g_boot_diag_meta_flash_cr = FLASH->CR;

    if ((status != HAL_OK) || (lock_status != HAL_OK))
    {
        return 0;
    }

    g_boot_diag_meta_save_stage = 50U;

    /*
     * Verify ONLY the page just written. The other page has intentionally
     * remained untouched and is still the recovery copy if this fails.
     */
    if (Boot_ReadMetadataV3At(
            target_address,
            &verify) == 0)
    {
        return 0;
    }

    if (memcmp(
            &verify,
            &record,
            sizeof(record)) != 0)
    {
        return 0;
    }

    g_boot_diag_meta_save_stage = 60U;

    return 1;
}


/*
 * Atomically retire a pending trial before booting the confirmed image.
 *
 * Boot_SaveMetadataV3() already preserves the newest valid copy until the
 * replacement copy has been erased, programmed and verified.  This wrapper
 * adds the state-machine guarantee: rollback is not allowed to continue until
 * the newly committed record has also been selected by the normal dual-copy
 * reader and its terminal state has been verified.
 */
static int Boot_CommitPendingClearV3(BootMetaV3_t *meta,
                                     int clear_pending_image)
{
    BootMetaV3_t candidate;
    BootMetaV3_t verify;
    uint32_t old_generation;
    uint32_t pending;
    uint32_t source_address;
    uint32_t attempt;

    if (meta == NULL)
    {
        return 0;
    }

    candidate = *meta;
    pending = candidate.pending_slot;
    old_generation = candidate.generation;

    g_boot_diag_rollback_commit_attempts = 0U;
    g_boot_diag_rollback_commit_ok = 0U;
    g_boot_diag_rollback_pending_slot = pending;
    g_boot_diag_rollback_generation_before = old_generation;
    g_boot_diag_rollback_generation_after = old_generation;

    if (clear_pending_image != 0)
    {
        if (pending == BOOT_SLOT_A)
        {
            candidate.app_a_size = 0U;
            candidate.app_a_crc32 = 0U;
        }
        else if (pending == BOOT_SLOT_B)
        {
            candidate.app_b_size = 0U;
            candidate.app_b_crc32 = 0U;
        }
    }

    candidate.pending_slot = BOOT_SLOT_NONE;
    candidate.attempts_left = 0U;
    candidate.generation++;

    /* One retry is safe: the previous valid copy remains the recovery copy. */
    for (attempt = 0U; attempt < 2U; attempt++)
    {
        g_boot_diag_rollback_commit_attempts = attempt + 1U;

        if (Boot_SaveMetadataV3(&candidate) == 0)
        {
            continue;
        }

        if (Boot_ReadMetadataV3(&verify, &source_address) == 0)
        {
            continue;
        }

        (void)source_address;

        if ((verify.confirmed_slot != candidate.confirmed_slot) ||
            (verify.pending_slot != BOOT_SLOT_NONE) ||
            (verify.attempts_left != 0U) ||
            (Boot_GenerationIsNewer(
                 verify.generation,
                 old_generation) == 0))
        {
            continue;
        }

        if ((clear_pending_image != 0) &&
            (((pending == BOOT_SLOT_A) &&
              ((verify.app_a_size != 0U) ||
               (verify.app_a_crc32 != 0U))) ||
             ((pending == BOOT_SLOT_B) &&
              ((verify.app_b_size != 0U) ||
               (verify.app_b_crc32 != 0U)))))
        {
            continue;
        }

        *meta = verify;
        g_boot_diag_rollback_generation_after = verify.generation;
        g_boot_diag_rollback_commit_ok = 1U;
        Boot_TraceMetadata(meta);
        return 1;
    }

    return 0;
}


/* Persist and verify one consumed trial attempt before entering the trial. */
static int Boot_CommitTrialAttemptV3(BootMetaV3_t *meta)
{
    BootMetaV3_t candidate;
    BootMetaV3_t verify;
    uint32_t old_attempts;
    uint32_t old_generation;
    uint32_t source_address;
    uint32_t attempt;

    if ((meta == NULL) ||
        (meta->pending_slot == BOOT_SLOT_NONE) ||
        (meta->attempts_left == 0U))
    {
        return 0;
    }

    candidate = *meta;
    old_attempts = candidate.attempts_left;
    old_generation = candidate.generation;

    candidate.attempts_left = old_attempts - 1U;
    candidate.generation++;

    g_boot_diag_trial_commit_attempts = 0U;
    g_boot_diag_trial_commit_ok = 0U;
    g_boot_diag_trial_attempts_before = old_attempts;
    g_boot_diag_trial_attempts_after = old_attempts;

    for (attempt = 0U; attempt < 2U; attempt++)
    {
        g_boot_diag_trial_commit_attempts = attempt + 1U;

        if (Boot_SaveMetadataV3(&candidate) == 0)
        {
            continue;
        }

        if (Boot_ReadMetadataV3(&verify, &source_address) == 0)
        {
            continue;
        }

        (void)source_address;

        if ((verify.confirmed_slot != candidate.confirmed_slot) ||
            (verify.pending_slot != candidate.pending_slot) ||
            (verify.attempts_left != candidate.attempts_left) ||
            (Boot_GenerationIsNewer(
                 verify.generation,
                 old_generation) == 0))
        {
            continue;
        }

        *meta = verify;
        g_boot_diag_trial_attempts_after = verify.attempts_left;
        g_boot_diag_trial_commit_ok = 1U;
        Boot_TraceMetadata(meta);
        return 1;
    }

    return 0;
}


static void Boot_ConvertV2ToV3(const BootMetaV2_t *old_meta,
                               BootMetaV3_t *new_meta)
{
    if ((old_meta == NULL) || (new_meta == NULL))
    {
        return;
    }

    memset(new_meta, 0, sizeof(*new_meta));

    new_meta->magic = BOOT_META_MAGIC;
    new_meta->version = BOOT_META_VERSION_V3;

    new_meta->confirmed_slot = old_meta->confirmed_slot;
    new_meta->pending_slot = old_meta->pending_slot;
    new_meta->attempts_left = old_meta->attempts_left;
    new_meta->generation = old_meta->generation;

    new_meta->app_a_size = old_meta->app_a_size;
    new_meta->app_a_crc32 = old_meta->app_a_crc32;
    new_meta->app_b_size = old_meta->app_b_size;
    new_meta->app_b_crc32 = old_meta->app_b_crc32;

    new_meta->flags = old_meta->flags;
}


static void Boot_ConvertV1ToV3(const BootMetaV1_t *old_meta,
                               BootMetaV3_t *new_meta)
{
    if ((old_meta == NULL) || (new_meta == NULL))
    {
        return;
    }

    memset(new_meta, 0, sizeof(*new_meta));

    new_meta->magic = BOOT_META_MAGIC;
    new_meta->version = BOOT_META_VERSION_V3;

    new_meta->confirmed_slot = old_meta->active_slot;
    new_meta->pending_slot = BOOT_SLOT_NONE;
    new_meta->attempts_left = 0U;
    new_meta->generation = 1U;

    /*
     * V1 predates per-image CRC metadata. size==0 deliberately retains the
     * already-proven vector-only transition compatibility.
     */
    new_meta->app_a_size = 0U;
    new_meta->app_a_crc32 = 0U;
    new_meta->app_b_size = 0U;
    new_meta->app_b_crc32 = 0U;

    new_meta->flags = 0U;
}


static int Boot_MailboxRead(BootMailbox_t *out)
{
    BootMailbox_t request;
    uint32_t crc;

    if (out == NULL)
    {
        return 0;
    }

    memcpy(
        &request,
        (const void *)BOOT_MAILBOX_ADDRESS,
        sizeof(request));

    if ((request.magic != BOOT_MAILBOX_MAGIC) ||
        (request.version != BOOT_MAILBOX_VERSION))
    {
        return 0;
    }

    crc = Boot_CRC32(
        (const uint8_t *)&request,
        offsetof(BootMailbox_t, crc32));

    if (crc != request.crc32)
    {
        return 0;
    }

    if ((request.requester_slot != BOOT_SLOT_A) &&
        (request.requester_slot != BOOT_SLOT_B))
    {
        return 0;
    }

    if ((request.command != BOOT_MAILBOX_CMD_CONFIRM_CURRENT) &&
        (request.command != BOOT_MAILBOX_CMD_START_TRIAL) &&
        (request.command != BOOT_MAILBOX_CMD_SET_CONFIRMED_SLOT))
    {
        return 0;
    }

    *out = request;
    return 1;
}


static void Boot_MailboxClear(void)
{
    volatile uint32_t *magic =
        (volatile uint32_t *)BOOT_MAILBOX_ADDRESS;

    /*
     * Consume the request BEFORE modifying flash.
     *
     * If power is lost during the following Metadata V3 save, the request is
     * not replayed forever. The previous valid metadata copy remains the
     * recovery state.
     */
    *magic = 0UL;

    __DSB();
    __ISB();
}


static int Boot_ProcessMailbox(BootMetaV3_t *meta)
{
    BootMailbox_t request;
    BootMetaV3_t candidate;

    if (meta == NULL)
    {
        return 0;
    }

    if (Boot_MailboxRead(&request) == 0)
    {
        return 0;
    }

    /*
     * Copy is now local and CRC-validated. Consume the SRAM request before
     * any flash erase/program operation.
     */
    Boot_MailboxClear();

    candidate = *meta;

    if (request.command == BOOT_MAILBOX_CMD_CONFIRM_CURRENT)
    {
        /*
         * A slot may confirm itself only when it is the pending trial, or when
         * it is already confirmed (idempotent repeat).
         */
        if ((candidate.pending_slot != request.requester_slot) &&
            (candidate.confirmed_slot != request.requester_slot))
        {
            return 0;
        }

        if ((candidate.confirmed_slot == request.requester_slot) &&
            (candidate.pending_slot == BOOT_SLOT_NONE) &&
            (candidate.attempts_left == 0UL))
        {
            return 1;
        }

        candidate.confirmed_slot = request.requester_slot;
        candidate.pending_slot = BOOT_SLOT_NONE;
        candidate.attempts_left = 0UL;
        candidate.generation++;

        if (Boot_SaveMetadataV3(&candidate) == 0)
        {
            return 0;
        }

        *meta = candidate;
        return 1;
    }

    if (request.command == BOOT_MAILBOX_CMD_START_TRIAL)
    {
        if ((request.target_slot != BOOT_SLOT_A) &&
            (request.target_slot != BOOT_SLOT_B))
        {
            return 0;
        }

        if (request.target_slot == request.requester_slot)
        {
            return 0;
        }

        if ((request.image_size < 8UL) ||
            (request.image_size >
             (Boot_SlotEnd(request.target_slot) -
              Boot_SlotBase(request.target_slot))))
        {
            return 0;
        }

        /*
         * The currently running requester is the known-good fallback.
         * The target image was already downloaded by the APP; verify its
         * vector + complete CRC again in the bootloader before scheduling it.
         */
        candidate.confirmed_slot = request.requester_slot;
        candidate.pending_slot = request.target_slot;
        candidate.attempts_left = BOOT_TRIAL_DEFAULT_ATTEMPTS;
        candidate.generation++;
        candidate.flags = 0UL;

        if (request.target_slot == BOOT_SLOT_A)
        {
            candidate.app_a_size = request.image_size;
            candidate.app_a_crc32 = request.image_crc32;
        }
        else
        {
            candidate.app_b_size = request.image_size;
            candidate.app_b_crc32 = request.image_crc32;
        }

        if (Boot_IsSlotImageValidV2(
                request.target_slot,
                &candidate) == 0)
        {
            return 0;
        }

        if (Boot_SaveMetadataV3(&candidate) == 0)
        {
            return 0;
        }

        *meta = candidate;
        return 1;
    }

    if (request.command == BOOT_MAILBOX_CMD_SET_CONFIRMED_SLOT)
    {
        if ((request.target_slot != BOOT_SLOT_A) &&
            (request.target_slot != BOOT_SLOT_B))
        {
            return 0;
        }

        /*
         * Service/debug BOOT A/BOOT B keeps the existing image-size/CRC
         * metadata. Do not select an invalid target.
         */
        if (Boot_IsSlotImageValidV2(
                request.target_slot,
                &candidate) == 0)
        {
            return 0;
        }

        candidate.confirmed_slot = request.target_slot;
        candidate.pending_slot = BOOT_SLOT_NONE;
        candidate.attempts_left = 0UL;
        candidate.generation++;

        if (Boot_SaveMetadataV3(&candidate) == 0)
        {
            return 0;
        }

        *meta = candidate;
        return 1;
    }

    return 0;
}


static void Boot_RunFromV1(const BootMetaV1_t *meta)
{
    uint32_t preferred;
    uint32_t fallback;

    if (meta == NULL)
    {
        Boot_RunFallback();
        return;
    }

    preferred = meta->active_slot;
    fallback =
        (preferred == BOOT_SLOT_A) ?
        BOOT_SLOT_B :
        BOOT_SLOT_A;

    if (Boot_IsAppVectorValid(
            Boot_SlotBase(preferred),
            Boot_SlotEnd(preferred)) != 0)
    {
        Boot_JumpToApp(Boot_SlotBase(preferred));
    }

    if (Boot_IsAppVectorValid(
            Boot_SlotBase(fallback),
            Boot_SlotEnd(fallback)) != 0)
    {
        Boot_JumpToApp(Boot_SlotBase(fallback));
    }

    while (1)
    {
    }
}


static void Boot_RunFromV2(BootMetaV2_t *meta)
{
    uint32_t confirmed;
    uint32_t pending;
    uint32_t other;

    if (meta == NULL)
    {
        Boot_RunFallback();
        return;
    }

    confirmed = meta->confirmed_slot;
    pending   = meta->pending_slot;

    /*
     * A pending slot equal to confirmed_slot is nonsensical. Normalize it to
     * "no pending trial" on the next metadata write opportunity.
     */
    if (pending == confirmed)
    {
        meta->pending_slot  = BOOT_SLOT_NONE;
        meta->attempts_left = 0U;
        meta->generation++;

        (void)Boot_SaveMetadataV2(meta);
        pending = BOOT_SLOT_NONE;
    }

    if (pending != BOOT_SLOT_NONE)
    {
        /*
         * Do not waste trial attempts on an image that already fails vector
         * or CRC validation.
         */
        if (Boot_IsSlotImageValidV2(pending, meta) == 0)
        {
            meta->pending_slot  = BOOT_SLOT_NONE;
            meta->attempts_left = 0U;
            meta->generation++;

            (void)Boot_SaveMetadataV2(meta);

            if (Boot_IsSlotImageValidV2(confirmed, meta) != 0)
            {
                Boot_JumpToApp(Boot_SlotBase(confirmed));
            }

            Boot_RunFallback();
        }

        /*
         * No tries remain: rollback to the last confirmed application.
         */
        if (meta->attempts_left == 0U)
        {
            meta->pending_slot  = BOOT_SLOT_NONE;
            meta->generation++;

            (void)Boot_SaveMetadataV2(meta);

            if (Boot_IsSlotImageValidV2(confirmed, meta) != 0)
            {
                Boot_JumpToApp(Boot_SlotBase(confirmed));
            }

            Boot_RunFallback();
        }

        /*
         * Consume one attempt BEFORE jumping.
         *
         * This ordering is what makes rollback work after a crash/watchdog/
         * power-cycle before the new application has a chance to CONFIRM.
         *
         * If the metadata write itself fails, do NOT risk entering the trial
         * image without recording that an attempt was consumed.
         */
        meta->attempts_left--;
        meta->generation++;

        if (Boot_SaveMetadataV2(meta) != 0)
        {
            Boot_JumpToApp(Boot_SlotBase(pending));
        }

        /*
         * Metadata could not be persisted. Stay on the confirmed image.
         */
        if (Boot_IsSlotImageValidV2(confirmed, meta) != 0)
        {
            Boot_JumpToApp(Boot_SlotBase(confirmed));
        }

        Boot_RunFallback();
    }

    /*
     * Normal boot: no pending trial.
     */
    if (Boot_IsSlotImageValidV2(confirmed, meta) != 0)
    {
        Boot_JumpToApp(Boot_SlotBase(confirmed));
    }

    /*
     * Confirmed image became invalid. Try the opposite slot as an emergency
     * recovery path; do not rewrite confirmation state automatically.
     */
    other =
        (confirmed == BOOT_SLOT_A) ?
        BOOT_SLOT_B :
        BOOT_SLOT_A;

    if (Boot_IsSlotImageValidV2(other, meta) != 0)
    {
        Boot_JumpToApp(Boot_SlotBase(other));
    }

    while (1)
    {
    }
}


static void Boot_RunFromV3(BootMetaV3_t *meta)
{
    uint32_t confirmed;
    uint32_t pending;
    uint32_t other;

    if (meta == NULL)
    {
        Boot_RunFallback();
        return;
    }

    confirmed = meta->confirmed_slot;
    pending   = meta->pending_slot;

    /*
     * A pending slot equal to confirmed_slot is nonsensical. Normalize it to
     * "no pending trial" on the next metadata write opportunity.
     */
    if (pending == confirmed)
    {
        if (Boot_CommitPendingClearV3(meta, 0) == 0)
        {
            while (1)
            {
            }
        }

        pending = BOOT_SLOT_NONE;
    }

    Boot_TraceMetadata(meta);

    if (pending != BOOT_SLOT_NONE)
    {
        /*
         * Do not waste trial attempts on an image that already fails vector
         * or CRC validation.
         */
        if (Boot_IsSlotImageValidV2(pending, meta) == 0)
        {
            if (Boot_CommitPendingClearV3(meta, 1) == 0)
            {
                /* Never boot rollback state that was not durably committed. */
                while (1)
                {
                }
            }

            if (Boot_IsSlotImageValidV2(confirmed, meta) != 0)
            {
                Boot_JumpToApp(Boot_SlotBase(confirmed));
            }

            Boot_RunFallback();
        }

        /*
         * No tries remain: rollback to the last confirmed application.
         */
        if (meta->attempts_left == 0U)
        {
            if (Boot_CommitPendingClearV3(meta, 1) == 0)
            {
                /* Never boot rollback state that was not durably committed. */
                while (1)
                {
                }
            }

            if (Boot_IsSlotImageValidV2(confirmed, meta) != 0)
            {
                Boot_JumpToApp(Boot_SlotBase(confirmed));
            }

            Boot_RunFallback();
        }

        /*
         * Consume one attempt BEFORE jumping.
         *
         * This ordering is what makes rollback work after a crash/watchdog/
         * power-cycle before the new application has a chance to CONFIRM.
         *
         * If the metadata write itself fails, do NOT risk entering the trial
         * image without recording that an attempt was consumed.
         */
        if (Boot_CommitTrialAttemptV3(meta) == 0)
        {
            /*
             * Never enter either APP with an uncommitted trial transition.
             * A reset/power cycle can safely retry from the older valid copy.
             */
            while (1)
            {
            }
        }

        Boot_JumpToApp(Boot_SlotBase(pending));
    }

    /*
     * Normal boot: no pending trial.
     */
    if (Boot_IsSlotImageValidV2(confirmed, meta) != 0)
    {
        Boot_JumpToApp(Boot_SlotBase(confirmed));
    }

    /*
     * Confirmed image became invalid. Try the opposite slot as an emergency
     * recovery path; do not rewrite confirmation state automatically.
     */
    other =
        (confirmed == BOOT_SLOT_A) ?
        BOOT_SLOT_B :
        BOOT_SLOT_A;

    if (Boot_IsSlotImageValidV2(other, meta) != 0)
    {
        Boot_JumpToApp(Boot_SlotBase(other));
    }

    while (1)
    {
    }
}


static void Boot_RunFallback(void)
{
    /*
     * Metadata missing/corrupt:
     * preserve the already-proven conservative policy:
     * try A first, then B.
     */
    if (Boot_IsAppVectorValid(APP_A_ADDRESS, APP_A_END) != 0)
    {
        Boot_JumpToApp(APP_A_ADDRESS);
    }

    if (Boot_IsAppVectorValid(APP_B_ADDRESS, APP_B_END) != 0)
    {
        Boot_JumpToApp(APP_B_ADDRESS);
    }

    while (1)
    {
    }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{
  /* USER CODE BEGIN 1 */
    BootMetaV3_t meta_v3;
    BootMetaV2_t meta_v2;
    BootMetaV1_t meta_v1;
    uint32_t meta_v3_source = 0U;
    int have_v3;
    int have_v2;
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */
  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */
  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  /* USER CODE BEGIN 2 */

    Boot_TraceBegin();

    /*
     * V4 bootloader-owned commit + V3 staged-migration strategy
     * ============================
     *
     * Current field devices may still run APP V2 firmware that writes the
     * legacy single-page record at 0x0807F000 (copy0).
     *
     * Therefore the bootloader:
     *
     * 1) Reads the newest valid V3 copy from page125/page126.
     * 2) ALSO checks whether an old V2 record currently exists at page126.
     * 3) If that V2 generation is newer than V3, it means an old APP just
     *    issued FW END / CONFIRM / BOOT after V3 had already been installed.
     *    Convert that newer V2 state into V3 before booting.
     * 4) If no V3 exists, migrate V2 (or V1) by writing COPY1 first, leaving
     *    the legacy COPY0 record untouched until one valid V3 copy exists.
     *
     * This allows the bootloader to be upgraded BEFORE APP A/B without losing
     * compatibility with the already-running V2 application firmware.
     */
    have_v3 = Boot_ReadMetadataV3(
        &meta_v3,
        &meta_v3_source);
    (void)meta_v3_source;

    have_v2 = Boot_ReadMetadataV2(&meta_v2);

    if ((have_v3 != 0) &&
        (have_v2 != 0) &&
        (Boot_GenerationIsNewer(
             meta_v2.generation,
             meta_v3.generation) != 0))
    {
        Boot_ConvertV2ToV3(
            &meta_v2,
            &meta_v3);

        if (Boot_SaveMetadataV3(&meta_v3) != 0)
        {
            if (Boot_ReadMetadataV3(
                    &meta_v3,
                    &meta_v3_source) != 0)
            {
                Boot_RunFromV3(&meta_v3);
            }
        }

        /*
         * Migration write failed. Do not consume a new trial attempt using an
         * unprotected single-copy update. Prefer the V2 confirmed image.
         */
        if (Boot_IsSlotImageValidV2(
                meta_v2.confirmed_slot,
                &meta_v2) != 0)
        {
            Boot_JumpToApp(
                Boot_SlotBase(meta_v2.confirmed_slot));
        }

        Boot_RunFallback();
    }

    if (have_v3 != 0)
    {
        /*
         * V4: APPs no longer need to erase/program metadata directly.
         * Process any validated SRAM mailbox request while executing from the
         * bootloader, then use the resulting V3 metadata for normal boot/trial
         * selection.
         */
        (void)Boot_ProcessMailbox(&meta_v3);

        if (Boot_ReadMetadataV3(
                &meta_v3,
                &meta_v3_source) != 0)
        {
            Boot_RunFromV3(&meta_v3);
        }

        Boot_RunFallback();
    }

    if (have_v2 != 0)
    {
        Boot_ConvertV2ToV3(
            &meta_v2,
            &meta_v3);

        if (Boot_SaveMetadataV3(&meta_v3) != 0)
        {
            if (Boot_ReadMetadataV3(
                    &meta_v3,
                    &meta_v3_source) != 0)
            {
                Boot_RunFromV3(&meta_v3);
            }
        }

        /*
         * If V3 migration cannot be committed, retain the previously proven
         * V2 behavior rather than making the device unbootable.
         */
        Boot_RunFromV2(&meta_v2);
    }

    if (Boot_ReadMetadataV1(&meta_v1) != 0)
    {
        Boot_ConvertV1ToV3(
            &meta_v1,
            &meta_v3);

        if (Boot_SaveMetadataV3(&meta_v3) != 0)
        {
            if (Boot_ReadMetadataV3(
                    &meta_v3,
                    &meta_v3_source) != 0)
            {
                Boot_RunFromV3(&meta_v3);
            }
        }

        Boot_RunFromV1(&meta_v1);
    }

    Boot_RunFallback();

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */
/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}

#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: source line number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  (void)file;
  (void)line;
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
