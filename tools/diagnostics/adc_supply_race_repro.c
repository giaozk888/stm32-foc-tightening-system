/* Host-only scheduling model; never connects to the board.
 * ADC_AnalogLiveReadChannel below is copied verbatim from main.c. Verify its
 * identity before compilation. HAL mocks model separate call-level locks and
 * the regular channel/DR shared by a lower-priority command and the higher-
 * priority background sampler. This demonstrates a possible software failure,
 * not an instrumented proof of what happened on the physical board.
 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

typedef enum { HAL_OK, HAL_ERROR, HAL_BUSY, HAL_TIMEOUT } HAL_StatusTypeDef;
typedef struct { uint32_t CR, DR; } ADC_TypeDef;
typedef struct { ADC_TypeDef *Instance; unsigned locked; } ADC_HandleTypeDef;
typedef struct {
    uint32_t Channel, Rank, SamplingTime, SingleDiff, OffsetNumber, Offset;
} ADC_ChannelConfTypeDef;
static ADC_TypeDef adc2_registers;
#define ADC2 (&adc2_registers)
#define ADC_CR_ADSTART 1U
#define ADC_REGULAR_RANK_1 1U
#define ANALOG_GPIO_SAMPLE_TIME 247U
#define ADC_SINGLE_ENDED 0U
#define ADC_OFFSET_NONE 0U
static ADC_HandleTypeDef hadc2 = {&adc2_registers, 0U};
static unsigned channel, hook, injected, in_background;
static uint16_t background_pc4, background_pc5;
static const uint16_t pc4_value = 590U, pc5_value = 1288U;
enum { HOOK_NONE, HOOK_BEFORE_START, HOOK_BEFORE_GET };

static HAL_StatusTypeDef ADC_AnalogLiveReadChannel(uint32_t, uint16_t *);
static void preempt_background(unsigned point);

static HAL_StatusTypeDef HAL_ADC_ConfigChannel(ADC_HandleTypeDef *adc,
                                              const ADC_ChannelConfTypeDef *cfg)
{
    if (adc->locked) return HAL_BUSY;
    adc->locked = 1U;
    assert(!(adc->Instance->CR & ADC_CR_ADSTART));
    channel = cfg->Channel;
    adc->locked = 0U; /* The official HAL releases this call-level lock. */
    return HAL_OK;
}

static HAL_StatusTypeDef HAL_ADC_Start(ADC_HandleTypeDef *adc)
{
    preempt_background(HOOK_BEFORE_START);
    if (adc->locked || (adc->Instance->CR & ADC_CR_ADSTART)) return HAL_BUSY;
    adc->locked = 1U;
    adc->locked = 0U; /* Official HAL unlocks before starting conversion. */
    adc->Instance->CR |= ADC_CR_ADSTART;
    adc->Instance->DR = channel == 5U ? pc4_value : pc5_value;
    adc->Instance->CR &= ~ADC_CR_ADSTART; /* Finite conversion completed. */
    return HAL_OK;
}

static HAL_StatusTypeDef HAL_ADC_PollForConversion(ADC_HandleTypeDef *adc,
                                                  uint32_t timeout)
{
    (void)timeout;
    assert(!(adc->Instance->CR & ADC_CR_ADSTART));
    /* Polling returns OK; it does not reserve DR until the caller reads it. */
    return HAL_OK;
}

static uint32_t HAL_ADC_GetValue(const ADC_HandleTypeDef *adc)
{
    preempt_background(HOOK_BEFORE_GET);
    return adc->Instance->DR;
}

/* BEGIN EXACT MAIN.C FUNCTION */
static HAL_StatusTypeDef ADC_AnalogLiveReadChannel(uint32_t channel,
                                                    uint16_t *raw)
{
    ADC_ChannelConfTypeDef cfg = {0};

    if ((ADC2->CR & ADC_CR_ADSTART) != 0U)
    {
        return HAL_BUSY;
    }

    cfg.Channel = channel;
    cfg.Rank = ADC_REGULAR_RANK_1;
    cfg.SamplingTime = ANALOG_GPIO_SAMPLE_TIME;
    cfg.SingleDiff = ADC_SINGLE_ENDED;
    cfg.OffsetNumber = ADC_OFFSET_NONE;
    cfg.Offset = 0U;

    if (HAL_ADC_ConfigChannel(&hadc2, &cfg) != HAL_OK)
    {
        return HAL_ERROR;
    }
    if (HAL_ADC_Start(&hadc2) != HAL_OK)
    {
        return HAL_ERROR;
    }
    if (HAL_ADC_PollForConversion(&hadc2, 2U) != HAL_OK)
    {
        /* No Stop: leave injected IV sampling armed for the 20 kHz loop. */
        return HAL_TIMEOUT;
    }

    *raw = (uint16_t)HAL_ADC_GetValue(&hadc2);
    return HAL_OK;
}
/* END EXACT MAIN.C FUNCTION */

static void preempt_background(unsigned point)
{
    if (hook != point || injected || in_background) return;
    injected = in_background = 1U;
    /* Model the six SAFE-only reads in ADC_AnalogLiveSample: PC4 x3,
     * followed by PC5 x3. The background leaves PC5 selected and in DR. */
    for (unsigned i = 0; i < 3U; ++i)
        assert(ADC_AnalogLiveReadChannel(5U, &background_pc4) == HAL_OK);
    for (unsigned i = 0; i < 3U; ++i)
        assert(ADC_AnalogLiveReadChannel(11U, &background_pc5) == HAL_OK);
    in_background = 0U;
}

static uint32_t bus_mv(uint16_t raw)
{
    return ((uint32_t)raw * 3280U * 25U + 4095U / 2U) / 4095U;
}

static void scenario(unsigned point, const char *name)
{
    uint16_t command_pc4 = 0U;
    hook = point;
    injected = in_background = 0U;
    hadc2.locked = 0U;
    ADC2->CR = ADC2->DR = 0U;
    assert(ADC_AnalogLiveReadChannel(5U, &command_pc4) == HAL_OK);
    assert(command_pc4 == (point == HOOK_NONE ? pc4_value : pc5_value));
    uint32_t mv = bus_mv(command_pc4);
    assert((mv >= 10000U && mv <= 14000U) == (point == HOOK_NONE));
    if (point != HOOK_NONE) {
        assert(background_pc4 == pc4_value && background_pc5 == pc5_value);
        assert(injected == 1U);
    }
    printf("%s: HAL_OK, requested_PC4_raw=%u, estimated_bus_mV=%lu, gate=%s\n",
           name, command_pc4, (unsigned long)mv,
           point == HOOK_NONE ? "PASS" : "REJECT");
}

int main(void)
{
    scenario(HOOK_NONE, "No preemption");
    scenario(HOOK_BEFORE_START, "Background between Config and Start");
    scenario(HOOK_BEFORE_GET, "Background between Poll and GetValue");
    puts("HOST MODEL PASS: 3 scheduling cases; no board IO; not physical root-cause proof.");
    return 0;
}
