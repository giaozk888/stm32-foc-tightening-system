#ifndef ROUTER_TCP_H
#define ROUTER_TCP_H
/* Called only by the UART/Router owner task. TCP task only feeds RX queues. */
void router_tcp_init(void);
void router_tcp_service(void);
#endif
