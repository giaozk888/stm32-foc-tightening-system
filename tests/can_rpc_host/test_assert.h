#ifndef CAN_RPC_TEST_ASSERT_H
#define CAN_RPC_TEST_ASSERT_H
#include <stdio.h>
#include <stdlib.h>
#ifdef assert
#undef assert
#endif
/* msvcrt assert/abort may create a modal desktop dialog. These test checks
 * report a nonzero process exit immediately, without touching the desktop. */
#define assert(expr) do { if (!(expr)) { fprintf(stderr,"CHECK FAILED: %s, %s:%d\n",#expr,__FILE__,__LINE__); fflush(stderr); _Exit(1); } } while (0)
#endif
