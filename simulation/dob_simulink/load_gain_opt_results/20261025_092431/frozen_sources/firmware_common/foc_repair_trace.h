#ifndef FOC_REPAIR_TRACE_H
#define FOC_REPAIR_TRACE_H
#include <stddef.h>
#include <stdint.h>
#if !defined(FOC_REPAIR_WINDOW_TRACE) || !defined(FOC_ZERO_ALL_REJECTED_DIAG) || \
    !defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || !defined(FOC_IRQ_COMPACT) || \
    !defined(FOC_PROTECTED_CLOSED_LOOP) || defined(FOC_LATEST_ORIGINAL_FSM) || \
    defined(FOC_COMPACT_CLOSED_LOOP)
#error Repair window trace is restricted to the compact power-hard-off diagnostic
#endif
enum { FOC_REPAIR_TRACE_N=32U };
/* Eight bytes per pair: four 12-bit ADC values, repair mask, ready flag and
 * two 6-bit pre-classification adaptive bounds. No heap or per-row timestamp.
 * Sequence inference is valid only with GAP=0. All callers serialize writes;
 * a frozen trace is immutable until the next boot/explicit fixture Begin. */
typedef struct {
    uint64_t rows[FOC_REPAIR_TRACE_N];
    uint32_t last_seq,last_us,window,repaired;
    uint8_t next,count,frozen,reason,streak,limit,streak_limit,cause,gap;
} FocRepairTrace;
typedef struct {
    uint32_t seq;
    uint16_t raw_u,raw_v,filtered_u,filtered_v;
    uint8_t mask,ready,jump_u,jump_v;
} FocRepairTraceRow;
_Static_assert(sizeof(FocRepairTrace)<=288U,"Bound diagnostic trace RAM");
/* Deliberately out-of-line in Flash: this opt-in diagnostic must not consume
 * a large new RAM hot-code copy. Its extra runtime is measured, not hidden. */
void FocRepairTrace_Record(FocRepairTrace *t,uint32_t seq,uint32_t us,
    uint16_t raw_u,uint16_t raw_v,uint16_t u,uint16_t v,
    uint8_t ready,uint8_t mask,uint16_t jump_u,uint16_t jump_v);
/* Called only AFTER output closure. Never copies the ring on the fault path. */
void FocRepairTrace_Freeze(FocRepairTrace *t,uint8_t reason,uint32_t window,
    uint8_t streak,uint8_t limit,uint8_t streak_limit,uint32_t repaired);
int FocRepairTrace_Row(const FocRepairTrace *t,unsigned i,FocRepairTraceRow *out);
unsigned FocRepairTrace_Hits(uint32_t bits);
/* Foreground only. Binding must prevent reads during mutation; frozen=1 is
 * the publication guarantee. Live queries expose only the frozen=0 status. */
int FocRepairTrace_Format(const FocRepairTrace *t,const char *cmd,char *out,size_t size);
#endif
