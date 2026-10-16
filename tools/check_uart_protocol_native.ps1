param([string]$Workspace = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path)
$ErrorActionPreference = 'Stop'

function Function-Pattern([string]$Name) {
    return '(?ms)^(?:static\s+)?[\w* ]+\b' + [regex]::Escape($Name) + '\s*\([^;{}]*\)\s*\{.*?^\}'
}
function Get-Function([string]$Text, [string]$Name) {
    $matches = [regex]::Matches($Text, (Function-Pattern $Name))
    if ($matches.Count -ne 1) { throw "Expected one function: $Name" }
    return $matches[0].Value
}
function Normalize([string]$Text) {
    # Ignore whitespace only; preserve every literal, comment and code token.
    return [regex]::Replace($Text, '(?s)//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|''(?:\\.|[^''\\\n])*''|\s+', {
        param($match)
        if ($match.Value.StartsWith('"') -or $match.Value.StartsWith("'") -or
            $match.Value.StartsWith('//') -or $match.Value.StartsWith('/*')) {
            return $match.Value
        }
        return ''
    })
}
function Strip-Printing([string]$Text) {
    # Compare handler control/state statements separately from formatting.
    $pattern = '\b(?:snprintf|Protocol_SendFormatted|Protocol_SendString|Protocol_SendTaggedLine|Protocol_SendError|ProtocolTxBuffer_Commit|ProtocolTxBuffer_Cancel)\s*\('
    while ($match = [regex]::Match($Text, $pattern)) {
        if (-not $match.Success) { break }
        $start = $match.Index
        $depth = 1
        $quote = [char]0
        $end = $start + $match.Length
        while ($depth -gt 0 -and $end -lt $Text.Length) {
            $char = $Text[$end]
            if ($quote -ne [char]0) {
                if ($char -eq '\') { $end++ }
                elseif ($char -eq $quote) { $quote = [char]0 }
            } elseif ($char -eq '"' -or $char -eq "'") { $quote = $char }
            elseif ($char -eq '(') { $depth++ }
            elseif ($char -eq ')') { $depth-- }
            $end++
        }
        if ($depth -ne 0) { throw 'Unbalanced printing call' }
        $Text = $Text.Remove($start, $end - $start)
    }
    $Text = $Text -replace '\(void\)\s*;', ';'
    return (Normalize $Text).Replace(';', '')
}

$changed = @('Modbus_ServiceCompletions','Protocol_SendTaggedLine','Protocol_SendError',
    'Protocol_AsyncEventService','Protocol_PrintStatus','Protocol_PrintSelftestStatus',
    'Fw_SendStatus','TightenParams_PrintAll','TightenParams_GetOne','TightenParams_SetOne',
    'Protocol_HandleLine')
$newHelpers = @('Protocol_SendFormatted','UART_SendReliableFormatted')
foreach ($slot in @('a','b')) {
    $backup = Join-Path $Workspace "refactor_backups/20261007_uart_protocol_native/main_$slot.c"
    $old = [IO.File]::ReadAllText($backup).Replace("`r`n", "`n")
    $current = [IO.File]::ReadAllText((Join-Path $Workspace "foc2_app_$slot/Core/Src/main.c")).Replace("`r`n", "`n")
    $oldHandler = Get-Function $old 'Protocol_HandleLine'
    $handler = Get-Function $current 'Protocol_HandleLine'
    # Checked snapshot builders add only allocation/cancel/publication paths.
    $handler = $handler -replace '            ProtocolTxBuffer reply = \{0\};\n', ''
    $handler = $handler -replace '(?s)            if \(!ProtocolTxBuffer_Begin\(&reply,.*?return; /\* Preserve failed-enqueue semantics, no unsafe fallback\. \*/\n', ''
    if ((Strip-Printing $oldHandler) -cne (Strip-Printing $handler)) {
        throw "Protocol handler changed outside print/lease expressions: $slot"
    }
    if ($current -notmatch 'ack_queued = Protocol_SendFormatted\(' -or
        $current -notmatch '(?s)g_fw_diag_ack_queued = \(uint32_t\)ack_queued;.*?if \(ack_queued != 0U\).*?else.*?Fw_ResetContext\(\);') {
        throw "IAP ACK acceptance/failure guard missing: $slot"
    }
    foreach ($name in $changed) {
        $old = $old.Replace((Get-Function $old $name), "/* scoped TX producer: $name */")
        $current = $current.Replace((Get-Function $current $name), "/* scoped TX producer: $name */")
    }
    foreach ($name in $newHelpers) {
        $current = $current.Replace((Get-Function $current $name), '')
        $current = [regex]::Replace($current, '(?m)^static uint8_t ' + $name + '\([^;]*;\n', '')
    }
    $current = $current -replace '(?m)^#include "protocol_tx_(format|buffer)\.h"\n', ''
    $current = $current -replace '(?s)/\* Known producers format into the final UART lease at runtime\..*?\*/\n', ''
    if ((Normalize $old) -cne (Normalize $current)) {
        throw "Source changed outside the explicit UART producer allowlist: $slot"
    }
    Write-Output "SCOPE PASS $slot : non-TX code unchanged; protocol control/state statements and IAP ACK guards preserved."
}
