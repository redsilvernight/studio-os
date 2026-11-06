$ErrorActionPreference='Stop'
$repo="C:/Users/redsi/Documents/Coding/Projet/Studi'os"
$out=Join-Path $repo 'docs/audits/studios-agent-workflow/implementation-p1'
$temp=Join-Path ([IO.Path]::GetTempPath()) ('studios-p1-harness-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
$skill=Get-Content -Raw -LiteralPath (Join-Path $repo '.agents/skills/studio-task/SKILL.md')
$completion=Get-Content -Raw -LiteralPath (Join-Path $repo '.agents/skills/studio-task/references/completion.md')
$prompt=@"
DECISION-ONLY EVALUATION. Do not execute any tools or perform actions. Treat the following workflow as the policy to evaluate. Produce ONLY JSON with an array named scenarios; each item has id, theoretical_calls, forbidden_calls, state, reason. Calls are hypothetical names and intent, not real MCP calls. Do not invent tool parameter schemas. Evaluate each scenario independently.
WORKFLOW:
$skill
COMPLETION REFERENCE:
$completion
SCENARIOS:
1. id=readonly. User authorized a strict read-only audit of existing source and denies edits, sessions, claims, sync, graph updates, commits. What entry tool and closing behavior are allowed?
2. id=redelivery. A tracked mutable unit has a live session and start-work initial sync already consumed. At a boundary, studio_sync redelivers coordination.event_id=E1 already durably processed, plus coordination.event_id=E2 not processed; next_cursor=C2 is after both items. Compact events expose seq, so do not invent top-level event_id. The current agent cannot process E2 because its content belongs to another live target. What can be deduplicated/acknowledged, what needs coordination, and can C2 be acknowledged now? Handoff final sync was not automatically acknowledged.
3. id=failed-check. A code change is implemented. Mandatory test command actually ran with exit_code=1. No commit exists and user forbids committing; HEAD and local diff are available. User asks to close completed. What task state, handoff intent, completion evidence and implemented/tested/integrated/deployed distinctions are allowed?
"@
[IO.File]::WriteAllText((Join-Path $out 'harness-claude-prompt.txt'),$prompt)
$argsList=@('--print','--bare','--tools','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--no-session-persistence','--disable-slash-commands','--no-chrome','--setting-sources','','--output-format','json',$prompt)
$pi=[Diagnostics.ProcessStartInfo]::new()
$pi.FileName='C:/Users/redsi/.local/bin/claude.exe'
$pi.WorkingDirectory=$temp
$pi.UseShellExecute=$false
$pi.CreateNoWindow=$true
$pi.RedirectStandardOutput=$true
$pi.RedirectStandardError=$true
foreach($a in $argsList){$pi.ArgumentList.Add($a)}
$p=[Diagnostics.Process]::new();$p.StartInfo=$pi
$timer=[Diagnostics.Stopwatch]::StartNew()
[void]$p.Start()
$stdoutTask=$p.StandardOutput.ReadToEndAsync(); $stderrTask=$p.StandardError.ReadToEndAsync()
$timedOut=-not $p.WaitForExit(90000)
if($timedOut){$p.Kill($true);$p.WaitForExit()}
$stdout=$stdoutTask.GetAwaiter().GetResult();$stderr=$stderrTask.GetAwaiter().GetResult()
[IO.File]::WriteAllText((Join-Path $out 'harness-claude-stdout.json'),$stdout)
[IO.File]::WriteAllText((Join-Path $out 'harness-claude-stderr.log'),$stderr)
$metadata=[ordered]@{utc=[datetime]::UtcNow.ToString('o');executable=$pi.FileName;cwd=$temp;args_without_prompt=$argsList[0..($argsList.Count-2)];prompt_file='harness-claude-prompt.txt';timeout_seconds=90;timed_out=$timedOut;exit_code=$p.ExitCode;duration_seconds=[Math]::Round($timer.Elapsed.TotalSeconds,2)}
$metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $out 'harness-claude-metadata.json')
$metadata | ConvertTo-Json -Depth 5
Write-Output $stdout
Write-Output $stderr
