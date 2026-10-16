#ifndef GATEWAY_H
#define GATEWAY_H
#include "network_v1.h"
bool gateway_network_ready(void);
void gateway_init(void);
void gateway_observe(const net_sample_t *sample);
void gateway_rejected(void);
#endif
