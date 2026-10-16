param([string]$Workspace = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path)
$ErrorActionPreference = 'Stop'
function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText($Path).Replace("`r`n", "`n")
}
function Function-Pattern([string]$Name) {
    return '(?ms)^(?:static\s+)?[\w* ]+\b' + [regex]::Escape($Name) + '\s*\([^;{}]*\)\s*\{.*?^\}'
}
function Remove-Function([string]$Text, [string]$Name) {
    $pattern = Function-Pattern $Name
    if ([regex]::Matches($Text, $pattern).Count -ne 1) { throw "Not exactly one function: $Name" }
    return [regex]::Replace($Text, $pattern, "/* scoped UART function: $Name */")
}
function Normalize-Printing([string]$Text, [bool]$NewVersion) {
    if ($NewVersion) {
        $helpers = '(?ms)^/\* Private literal-only path\..*?(?=^/\*\n \* Reliable path for protocol/router traffic\.)'
        if ([regex]::Matches($Text, $helpers).Count -ne 1) { throw 'Printing helpers not found exactly once' }
        $Text = [regex]::Replace($Text, $helpers, '')
        $Text = [regex]::Replace($Text, '^#include <stdarg.h>\n', '', [Text.RegularExpressions.RegexOptions]::Multiline)
        $Text = $Text.Replace('UART_SendLiteral(', 'UART_SendString(').Replace('UART_SendFormatted(', 'snprintf(')
    } else {
        # All removed dynamic sends were the buffer just formatted in the same
        # branch/adjacent statement. Formatting arguments remain in comparison.
        $Text = [regex]::Replace($Text, '\bUART_SendString\(\s*[A-Za-z_]\w*\s*\);', '')
    }
    # Ignore source whitespace, but preserve every string/character literally.
    return [regex]::Replace($Text, '(?s)//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|''(?:\\.|[^''\\\n])*''|\s+', {
        param($match)
        if ($match.Value.StartsWith('"') -or $match.Value.StartsWith("'") -or
            $match.Value.StartsWith('//') -or $match.Value.StartsWith('/*')) { return $match.Value }
        return ''
    })
}
foreach ($slot in @('foc2_app_a', 'foc2_app_b')) {
    $old = Read-Normalized (Join-Path $Workspace "refactor_backups/20261003_uart_zero_copy/$slot/Core/Src/main.c")
    $current = Read-Normalized (Join-Path $Workspace "$slot/Core/Src/main.c")
    $phaseOld = Read-Normalized (Join-Path $Workspace "refactor_backups/20261004_shared_log_zero_copy/$slot/Core/Src/main.c")
    if ((Normalize-Printing $phaseOld $false) -cne (Normalize-Printing $current $true)) {
        throw "Changes beyond literal/formatted UART output migration: $slot"
    }
    Write-Output "PASS $slot`: Oct 04 migration preserves all format arguments and all non-printing main.c code."
    # Having proved the new printing phase, run the original Oct 03 scope check
    # against its exact baseline, so older UART integration remains audited.
    $new = $phaseOld
    # Prove the large protocol handler differs ONLY in the read-only PING reply.
    $pattern = Function-Pattern 'Protocol_HandleLine'
    $oldHandler = [regex]::Match($old, $pattern).Value
    $newHandler = [regex]::Match($new, $pattern).Value
    $oldPing = @'
        snprintf(
            msg,
            sizeof(msg),
            "%lu OK PING PONG\r\n",
            (unsigned long)request_id);
        Protocol_SendString(msg);
'@
    $newPing = '        Protocol_SendTaggedLine(request_id, "OK PING PONG");'
    if (!$oldHandler.Contains($oldPing)) { throw "Original PING not found: $slot" }
    if ($oldHandler.Replace($oldPing, $newPing) -cne $newHandler) { throw "Unexpected protocol handler changes: $slot" }
    foreach ($name in @('UART_SendString', 'UART_SendReliableString', 'Protocol_SendTaggedLine',
                         'Protocol_SendError', 'RouterTask', 'Router_Uart1Tx', 'MX_LPUART1_UART_Init')) {
        $old = Remove-Function $old $name
        $new = Remove-Function $new $name
    }
    $old = Remove-Function $old 'Protocol_HandleLine'
    $new = Remove-Function $new 'Protocol_HandleLine'
    foreach ($name in @('Router_RxLine', 'Router_RxByte', 'Router_RxGap')) {
        $new = [regex]::Replace($new, (Function-Pattern $name), '')
    }
    $new = $new.Replace('#include "uart_line_parser.h"' + "`n", '')
    $new = [regex]::Replace($new, '(?ms)^#ifndef UART_LOG_BAUD\n.*?^#endif\n#if UART_LOG_BAUD > 115200U\n.*?^#endif\n', '')
    # This allowed change is only a comment describing the removed TX mutex.
    $new = $new.Replace('* silently lost when the fixed TX pool temporarily lacks a contiguous run.',
        "* silently lost when another producer briefly owns the TX ring mutex or when`n * the ring is temporarily full.")
    # Ignore blank-line counts left by replacing whole function definitions.
    $old = [regex]::Replace($old, '\n[ \t]*\n(?:[ \t]*\n)+', "`n`n")
    $new = [regex]::Replace($new, '\n[ \t]*\n(?:[ \t]*\n)+', "`n`n")
    if ($old -cne $new) { throw "Changes outside the explicitly scoped UART integration: $slot" }
    Write-Output "PASS $slot`: all other main.c text unchanged; protocol handler only PING reply changed."
}
foreach ($relative in @('Core/Src/uart_async.c', 'Core/Src/uart_rx_dma.c',
    'Core/Inc/uart_async.h', 'Core/Src/router.c', 'Core/Inc/router.h',
    'Middleware/pigweed/pw_log_backend.c', 'Middleware/pigweed/pw_log_backend.h',
    'Middleware/pigweed/pw_log_router_bridge.c')) {
    $a = Read-Normalized (Join-Path $Workspace "foc2_app_a/$relative")
    $b = Read-Normalized (Join-Path $Workspace "foc2_app_b/$relative")
    if ($a -cne $b) { throw "A/B UART/log/Router adapter drift: $relative" }
}
Write-Output 'PASS A/B UART/log/Router adapters identical; no board actions performed.'
