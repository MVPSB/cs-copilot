# 扫描已跟踪文件中的疑似密钥。用法：powershell -File scripts/check_secrets.ps1
# 命中即退出码 1，可直接挂到 pre-commit 或 CI。

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$patterns = @(
    'app-[A-Za-z0-9]{16,}',
    'sk-[A-Za-z0-9]{16,}',
    'Bearer\s+[A-Za-z0-9\-_\.]{20,}',
    'AKIA[0-9A-Z]{16}'
)

$allowList = @('.env.example', 'SECURITY.md', 'check_secrets.ps1')

$files = git ls-files | Where-Object { $allowList -notcontains $_ -and $_ -notmatch '\.(png|jpg|jpeg|gif|ico|xlsx|zip|pdf)$' }

$hits = @()
foreach ($file in $files) {
    if (-not (Test-Path -LiteralPath $file)) { continue }
    foreach ($pattern in $patterns) {
        $matches = Select-String -LiteralPath $file -Pattern $pattern -AllMatches -ErrorAction SilentlyContinue
        foreach ($m in $matches) {
            $hits += [PSCustomObject]@{
                File = $file
                Line = $m.LineNumber
                Match = ($m.Matches[0].Value.Substring(0, [Math]::Min(12, $m.Matches[0].Value.Length)) + '...')
            }
        }
    }
}

if ($hits.Count -eq 0) {
    Write-Host "OK: 未发现疑似密钥（已扫描 $($files.Count) 个文件）"
    exit 0
}

Write-Host "发现疑似密钥：" -ForegroundColor Red
$hits | Sort-Object File, Line | Format-Table -AutoSize
Write-Host "请改为环境变量，并按 SECURITY.md 吊销与清理历史。" -ForegroundColor Yellow
exit 1
