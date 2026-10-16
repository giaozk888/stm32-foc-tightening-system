#include "router_network.h"
#include <stdio.h>
#include <string.h>
int main(void)
{
    char line[1024];
    while (fgets(line, sizeof(line), stdin)) {
        line[strcspn(line, "\r\n")] = '\0';
        puts(rn_line_allowed(line) ? "1" : "0");
    }
    return 0;
}
