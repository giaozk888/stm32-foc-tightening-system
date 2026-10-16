/* ARM code-generation check only; no board interaction. */
#include "foc_filtered_protection_candidate.h"
uint8_t PairFast_PopcountProbe(uint32_t bits) { return FocFp_Popcount(bits); }
