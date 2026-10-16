param(
    [string]$Compiler = 'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
)

# Host-only test of the actual PWM_SetDuty function from each firmware source.
# HAL compare writes are captured in RAM. No probe, serial port or board is used.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $PSScriptRoot 'pwm_duty_host_build'
if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) {
    throw "Host C compiler not found: $Compiler"
}
New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

$prefix = @'
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
typedef struct { unsigned unused; } TIM_HandleTypeDef;
static TIM_HandleTypeDef htim1;
static uint32_t compares[3];
static unsigned writes;
#define TIM_CHANNEL_1 0U
#define TIM_CHANNEL_2 1U
#define TIM_CHANNEL_3 2U
static void capture_compare(TIM_HandleTypeDef *timer, unsigned channel, uint32_t value)
{
    assert(timer == &htim1);
    assert(channel < 3U);
    compares[channel] = value;
    ++writes;
}
#define __HAL_TIM_SET_COMPARE(timer, channel, value) capture_compare(timer, channel, value)
'@

$suffix = @'
static void check(float u, float v, float w, uint32_t eu, uint32_t ev, uint32_t ew)
{
    writes = 0;
    PWM_SetDuty(u, v, w);
    assert(writes == 3U);
    assert(compares[0] == eu && compares[1] == ev && compares[2] == ew);
}
int main(void)
{
    check(-1.0f, -1.0f, -1.0f, 85U, 85U, 85U);
    check(0.0f, 0.0f, 0.0f, 85U, 85U, 85U);
    check(0.02f, 0.02f, 0.02f, 85U, 85U, 85U);
    check(0.5f, 0.5f, 0.5f, 2125U, 2125U, 2125U);
    check(0.9f, 0.9f, 0.9f, 3825U, 3825U, 3825U);
    check(0.95f, 0.95f, 0.95f, 4037U, 4037U, 4037U);
    check(0.98f, 0.98f, 0.98f, 4165U, 4165U, 4165U);
    check(1.0f, 1.0f, 1.0f, 4165U, 4165U, 4165U);
    check(0.9f, 0.5f, 0.1f, 3825U, 2125U, 425U);
    puts("PASS: actual PWM_SetDuty, 9 cases; 90% -> CCR1/2/3=3825 (mock HAL only)");
    return 0;
}
'@

foreach ($slot in @('a', 'b')) {
    $sourcePath = Join-Path $taskRoot "foc2_app_$slot\Core\Src\main.c"
    $source = Get-Content -LiteralPath $sourcePath -Raw
    $arr = [regex]::Match($source, '(?m)^#define\s+PWM_ARR\s+(\d+U)\s*$')
    $body = [regex]::Match($source, '(?ms)^static void PWM_SetDuty\(float du, float dv, float dw\)\s*\{.*?^\}')
    if (-not $arr.Success -or -not $body.Success) {
        throw "Cannot extract exact PWM source for slot $slot"
    }
    if ($arr.Groups[1].Value -ne '4249U') {
        throw 'PWM period changed; review expected compare values before testing'
    }
    $program = $prefix + "`n#define PWM_ARR " + $arr.Groups[1].Value + "`n" + $body.Value + "`n" + $suffix
    $executable = Join-Path $buildDir "pwm_set_duty_$slot.exe"
    $program | & $Compiler -x c - -std=c11 -O2 -Wall -Wextra -Werror -pedantic -UNDEBUG -o $executable
    if ($LASTEXITCODE -ne 0) { throw "Slot $slot host compilation failed" }
    Write-Output "Slot $($slot.ToUpper()):"
    & $executable
    if ($LASTEXITCODE -ne 0) { throw "Slot $slot PWM mapping test failed" }
}
