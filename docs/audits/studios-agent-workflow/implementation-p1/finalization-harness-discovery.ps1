$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$codex = 'C:/Users/redsi/AppData/Local/OpenAI/Codex/bin/a159911ff70742e9/codex.exe'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('finalization-harness-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($fixture)
& git -C $fixture init --quiet
if ($LASTEXITCODE -ne 0) { throw 'Temporary Git fixture initialization failed' }
$names = @(Get-ChildItem -LiteralPath (Join-Path $repo '.codex/agents') -Filter '*.toml' | ForEach-Object BaseName)
$servers = @('obsidian-memory','studio-os','local-ai-hub','node_repl','opencode-dispatch','context7','postgres-test')
function Read-PromptMetadata([string]$phase) {
    $info = [Diagnostics.ProcessStartInfo]::new($codex)
    $info.WorkingDirectory = $fixture
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($arg in @('debug','prompt-input')) { $info.ArgumentList.Add($arg) }
    foreach ($server in $servers) {
        $info.ArgumentList.Add('-c')
        $info.ArgumentList.Add('mcp_servers.' + $server + '.enabled=false')
    }
    foreach ($arg in @('features.apps=false','features.plugins=false','features.memories=false')) {
        $info.ArgumentList.Add('-c'); $info.ArgumentList.Add($arg)
    }
    $info.ArgumentList.Add('LOCAL DISCOVERY CHECK ONLY. No model request.')
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $process = [Diagnostics.Process]::Start($info)
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $timeout = -not $process.WaitForExit(45000)
    if ($timeout) { $process.Kill($true); $process.WaitForExit() }
    $output = $stdout.GetAwaiter().GetResult()
    $errors = $stderr.GetAwaiter().GetResult()
    $timer.Stop()
    # Never persist the model-visible input: it may contain unrelated global policies.
    $parsed = $false
    $keys = @()
    try { $document = $output | ConvertFrom-Json; $parsed = $true; $keys = @($document.PSObject.Properties.Name) } catch {}
    [ordered]@{
        phase = $phase; exit_code = $process.ExitCode; timed_out = $timeout
        duration_ms = $timer.ElapsedMilliseconds; json_parsed = $parsed
        stdout_chars = $output.Length; stderr_chars = $errors.Length
        top_level_keys = $keys
        role_name_hits = @($names | Where-Object { $output.Contains($_) })
        contains_fixture_path = $output.Contains($fixture)
        model_request = $false; raw_output_persisted = $false
    }
}
$before = Read-PromptMetadata 'empty-fixture'
[void][IO.Directory]::CreateDirectory((Join-Path $fixture '.codex/agents'))
Get-ChildItem -LiteralPath (Join-Path $repo '.codex/agents') -Filter '*.toml' | Copy-Item -Destination (Join-Path $fixture '.codex/agents')
$after = Read-PromptMetadata 'six-agent-fixture'
[ordered]@{ fixture = $fixture; agent_count = $names.Count; disabled_mcp = $servers; before = $before; after = $after } |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'finalization-harness-discovery.json') -Encoding utf8
Get-Content -LiteralPath (Join-Path $PSScriptRoot 'finalization-harness-discovery.json') -Raw
