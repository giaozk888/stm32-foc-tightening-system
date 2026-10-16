#define PW_LOG_MODULE_NAME "PWTHREAD"

#include "FreeRTOS.h"
#include "pw_log/log.h"
#include "pw_thread/thread.h"
#include "pw_thread/yield.h"
#include "pw_thread_freertos/context.h"
#include "pw_thread_freertos/options.h"
#include "task.h"

namespace {

constexpr size_t kSmokeStackWords = 256U;
pw::thread::freertos::StaticContextWithStack<kSmokeStackWords> g_context;

void Worker()
{
    PW_LOG_INFO("worker start backend=FreeRTOS");
    pw::this_thread::yield();
    vTaskDelay(pdMS_TO_TICKS(25U));
    PW_LOG_INFO("worker complete yield=OK delay=25ms");
}

}  // namespace

extern "C" void PW_ThreadSmokeStart(void)
{
    auto options = pw::thread::freertos::Options()
                       .set_name("PwSmoke")
                       .set_priority(tskIDLE_PRIORITY + 1U)
                       .set_static_context(g_context);

    pw::Thread(options, Worker).detach();
    PW_LOG_INFO("created static_stack=%u words priority=%u",
                static_cast<unsigned>(kSmokeStackWords),
                static_cast<unsigned>(tskIDLE_PRIORITY + 1U));
}

