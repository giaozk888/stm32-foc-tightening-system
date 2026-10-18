#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void barrier(void);
#define AS_DMA_PUBLICATION_BARRIER() barrier()
#include "as5047p_dma_publication.h"
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"line %d: %s\n",__LINE__,#c); exit(1); } } while (0)
static AsDmaPublication pub;
static unsigned inject,barriers,action;
static AsDmaSample sample(uint32_t n)
{
    AsDmaSample s={.status=AS_DMA_OK,.sequence=n,.sample_us=n*1000U,
        .raw=(uint16_t)n,.response=(uint16_t)n}; return s;
}
static void barrier(void)
{
    ++barriers;
    if (action==1U) { /* FOC suspends publisher before the index commit. */
        action=0U; AsDmaSample old;
        CHECK(AsDma_ReadPublished(&pub,&old)); CHECK(old.sequence==7U);
    } else if (inject && --inject==0U) {
        unsigned mode=action; action=0U;
        AsDmaSample a=sample(10U),b=sample(11U);
        AsDma_Publish(&pub,&a); AsDma_Publish(&pub,&b); /* same bank, new epoch */
        if (mode==2U) { inject=2U; action=2U; }
    }
}
int main(void)
{
    AsDmaSample a=sample(7U),out={0}; AsDma_Publish(&pub,&a);
    action=1U; a=sample(8U); AsDma_Publish(&pub,&a);
    CHECK(AsDma_ReadPublished(&pub,&out) && out.sequence==8U);
    for (unsigned point=1U;point<=2U;++point) {
        inject=point; CHECK(AsDma_ReadPublished(&pub,&out));
        CHECK(out.sequence==11U && out.sample_us==11000U && out.raw==11U);
    }
    AsDmaSample previous=out;
    inject=1U; action=2U;
    CHECK(!AsDma_ReadPublished(&pub,&out)); CHECK(!memcmp(&previous,&out,sizeof(out)));
    inject=action=0U;
    pub.generation=UINT32_MAX; a=sample(12U); AsDma_Publish(&pub,&a);
    CHECK(!pub.generation && AsDma_ReadPublished(&pub,&out) && out.sequence==12U);
    a.status=AS_DMA_TIMEOUT; AsDma_Publish(&pub,&a);
    CHECK(AsDma_ReadPublished(&pub,&out) && out.status==AS_DMA_TIMEOUT);
    CHECK(barriers);
    puts("PASS double-bank publication / FOC during writer / task copy ABA / bounded retry / failure / wrap");
}
