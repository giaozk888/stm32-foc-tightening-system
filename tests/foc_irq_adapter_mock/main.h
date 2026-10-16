#ifndef FOC_IRQ_ADAPTER_MOCK_H
#define FOC_IRQ_ADAPTER_MOCK_H
#include <stdint.h>
typedef struct { uint32_t CYCCNT; } MockDwt;
extern MockDwt irq_mock_dwt;
extern uint32_t irq_mock_mask;
#define DWT (&irq_mock_dwt)
static inline uint32_t __get_PRIMASK(void) { return irq_mock_mask; }
static inline void __disable_irq(void) { irq_mock_mask=1U; }
static inline void __set_PRIMASK(uint32_t value) { irq_mock_mask=value; }
#endif
