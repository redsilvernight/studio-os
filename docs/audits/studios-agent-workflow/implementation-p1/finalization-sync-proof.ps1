param([string]$RunFile = (Join-Path $PSScriptRoot 'finalization-run.json'))
$ErrorActionPreference = 'Stop'
$run = Get-Content -LiteralPath $RunFile -Raw | ConvertFrom-Json
$scripts = @{ original = Join-Path $run.backup 'sync-claude-config.ps1'; candidate = Join-Path $run.backup 'sync-claude-config.candidate.ps1' }
$reportPath = Join-Path $PSScriptRoot 'finalization-sync-proof.json'
$logPath = Join-Path $PSScriptRoot 'finalization-sync-proof.log'
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('studio-sync-proof-' + [guid]::NewGuid().ToString('N'))
$assertions = [Collections.Generic.List[object]]::new()
$cases = [Collections.Generic.List[object]]::new()
$log = [Collections.Generic.List[string]]::new()
$timer = [Diagnostics.Stopwatch]::StartNew()
$homeBefore = $HOME
$profileBefore = $env:USERPROFILE
$completed = $false
function Assert-Proof([string]$Name, [bool]$Condition) {
    $assertions.Add([pscustomobject]@{ name=$Name; passed=$Condition })
    if (-not $Condition) { throw "Assertion failed: $Name" }
}
function Put([string]$Root, [string]$Relative, [string]$Text) {
    $path = Join-Path $Root $Relative
    [IO.Directory]::CreateDirectory((Split-Path -Parent $path)) | Out-Null
    [IO.File]::WriteAllText($path, $Text, [Text.UTF8Encoding]::new($false))
}
function Snapshot([string]$Root) {
    $files = [ordered]@{}
    Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Where-Object { -not [IO.Path]::GetRelativePath($Root, $_.FullName).StartsWith('AppData' + [IO.Path]::DirectorySeparatorChar) } | Sort-Object FullName | ForEach-Object {
        $relative = [IO.Path]::GetRelativePath($Root, $_.FullName)
        $files[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
    return ,$files
}
function Fingerprint($Value) { ConvertTo-Json -InputObject $Value -Depth 12 -Compress }
function ACLs([string]$Root) {
    $items = [ordered]@{}
    Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Sort-Object FullName | ForEach-Object {
        $items[[IO.Path]::GetRelativePath($Root, $_.FullName)] = (Get-Acl -LiteralPath $_.FullName).Sddl
    }
    return ,$items
}
function Invoke-Isolated([string]$Script, [string]$FakeHome, [string]$Project, [switch]$Audit) {
    if ($timer.Elapsed.TotalSeconds -gt 240) { throw 'Proof exceeded 240 seconds' }
    if (-not $FakeHome.StartsWith($scratch + [IO.Path]::DirectorySeparatorChar) -or -not $Project.StartsWith($scratch + [IO.Path]::DirectorySeparatorChar)) { throw 'Fixture escaped scratch root' }
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = (Get-Command pwsh -ErrorAction Stop).Source
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.WorkingDirectory = $Project
    foreach ($argument in @('-NoLogo','-NoProfile','-NonInteractive','-File',$Script,'-ProjectRoot',$Project)) { $info.ArgumentList.Add($argument) }
    if ($Audit) { $info.ArgumentList.Add('-AuditOnly') }
    $info.Environment['USERPROFILE'] = $FakeHome
    # HOME is deliberately inherited untouched. Script uses only USERPROFILE.
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(30000)) { $process.Kill($true); $process.WaitForExit(); throw 'Subprocess exceeded 30 seconds' }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $log.Add("SCRIPT=$Script FAKE_USERPROFILE=$FakeHome PROJECT=$Project AUDIT=$Audit EXIT=$($process.ExitCode)`n$stdout`n$stderr")
    $expected = if ($Audit) { 2 } else { 0 }
    Assert-Proof "subprocess exit expected $expected" ($process.ExitCode -eq $expected)
    return ($stdout | ConvertFrom-Json)
}
try {
    foreach ($version in @('original','candidate')) {
        $tokens=$null; $errors=$null
        [void][Management.Automation.Language.Parser]::ParseFile($scripts[$version], [ref]$tokens, [ref]$errors)
        Assert-Proof "$version exact file AST parse" ($errors.Count -eq 0)
    }
    foreach ($kind in @('canonical','foreign-agents','foreign-legacy')) {
        foreach ($version in @('original','candidate')) {
            $base = Join-Path $scratch "$kind-$version"
            $fakeHome = Join-Path $base 'home'
            $project = Join-Path $base 'project'
            $agent = "---`nname: personal-agent`ndescription: Personal fixture`nmodel: haiku`n---`nPersonal agent sentinel`n"
            Put $fakeHome '.claude/agents/personal-agent.md' $agent
            Put $fakeHome '.claude/skills/personal-skill/SKILL.md' 'Personal skill sentinel'
            Put $fakeHome '.claude/rules/personal.md' 'Personal rule sentinel'
            Put $fakeHome '.codex/config.toml' "sandbox_mode = 'workspace-write'`napproval_policy = 'on-request'`n# personal config sentinel`n"
            Put $fakeHome '.codex/agents/keep-personal.toml' 'Personal TOML sentinel'
            Put $fakeHome '.agents/skills/keep-personal/SKILL.md' 'Personal shared skill sentinel'
            Put $project 'AGENTS.md' "Personal project instructions`n<!-- BEGIN GENERATED RULES from .agents/rules -->`nCanonical generated rule sentinel`n<!-- END GENERATED RULES -->`n"
            Put $project '.claude/agents/project-agent.md' ($agent.Replace('personal-agent','project-agent'))
            Put $project '.claude/skills/studio-task/SKILL.md' 'Obsolete projected skill sentinel'
            Put $project '.claude/rules/legacy.md' 'Legacy projected rule sentinel'
            if ($kind -eq 'canonical') {
                Put $project '.agents/rules/studio-protocol.md' 'Canonical protocol sentinel'
                Put $project '.agents/skills/studio-task/SKILL.md' 'Canonical studio-task sentinel'
            } elseif ($kind -eq 'foreign-agents') {
                Put $project '.agents/OTHER.md' 'Foreign .agents sentinel without Studio protocol'
            }
            $beforeProject = Snapshot $project
            $beforeHome = Snapshot $fakeHome
            $aclAvailable = $true
            try { $beforeACL = ACLs $fakeHome; $projectACL = ACLs $project } catch { $aclAvailable=$false; $log.Add("ACL unavailable: $_") }
            if ($kind -eq 'canonical') {
                $auditResult = Invoke-Isolated $scripts[$version] $fakeHome $project -Audit
                Assert-Proof "$kind $version audit home untouched" ((Fingerprint (Snapshot $fakeHome)) -eq (Fingerprint $beforeHome))
                Assert-Proof "$kind $version audit project untouched" ((Fingerprint (Snapshot $project)) -eq (Fingerprint $beforeProject))
            }
            $first = Invoke-Isolated $scripts[$version] $fakeHome $project
            $afterProject = Snapshot $project
            $afterHome = Snapshot $fakeHome
            foreach ($name in $beforeHome.Keys) { Assert-Proof "$kind $version preserves personal $name" ($afterHome[$name] -eq $beforeHome[$name]) }
            if ($kind -eq 'canonical' -and $version -eq 'candidate') {
                Assert-Proof 'canonical candidate entire project hashes unchanged' ((Fingerprint $beforeProject) -eq (Fingerprint $afterProject))
                Assert-Proof 'canonical candidate no project changed entries' (@($first.changed | Where-Object { $_.StartsWith($project) }).Count -eq 0)
                $text = [IO.File]::ReadAllText((Join-Path $project 'AGENTS.md'))
                Assert-Proof 'canonical one generated block retained' ([regex]::Matches($text,'<!-- BEGIN GENERATED RULES').Count -eq 1)
            }
            if ($kind -eq 'canonical' -and $version -eq 'original') { Assert-Proof 'canonical original mutates fixture (sensitivity control)' ((Fingerprint $beforeProject) -ne (Fingerprint $afterProject)) }
            $second = Invoke-Isolated $scripts[$version] $fakeHome $project
            Assert-Proof "$kind $version second run project hashes stable" ((Fingerprint $afterProject) -eq (Fingerprint (Snapshot $project)))
            Assert-Proof "$kind $version second run global hashes stable" ((Fingerprint $afterHome) -eq (Fingerprint (Snapshot $fakeHome)))
            Assert-Proof "$kind $version second run reports no changes" (@($second.changed).Count -eq 0)
            if ($aclAvailable) {
                $afterACL = ACLs $fakeHome
                foreach ($name in $beforeACL.Keys) { Assert-Proof "$kind $version personal ACL $name" ($beforeACL[$name] -eq $afterACL[$name]) }
                $afterProjectACL = ACLs $project
                foreach ($name in $projectACL.Keys) { Assert-Proof "$kind $version existing project ACL $name" ($projectACL[$name] -eq $afterProjectACL[$name]) }
            }
            $cases.Add([pscustomobject]@{ kind=$kind; version=$version; globalBefore=$beforeHome; globalAfter=$afterHome; projectBefore=$beforeProject; projectAfter=$afterProject; aclChecked=$aclAvailable; firstChanged=@($first.changed); secondChanged=@($second.changed) })
        }
        $original = $cases | Where-Object { $_.kind -eq $kind -and $_.version -eq 'original' }
        $candidate = $cases | Where-Object { $_.kind -eq $kind -and $_.version -eq 'candidate' }
        Assert-Proof "$kind global outputs original equal candidate" ((Fingerprint $original.globalAfter) -eq (Fingerprint $candidate.globalAfter))
        if ($kind -ne 'canonical') { Assert-Proof "$kind project outputs original equal candidate" ((Fingerprint $original.projectAfter) -eq (Fingerprint $candidate.projectAfter)) }
    }
    Assert-Proof 'parent HOME untouched' ($HOME -eq $homeBefore)
    Assert-Proof 'parent USERPROFILE untouched' ($env:USERPROFILE -eq $profileBefore)
    $provenanceRoot = Join-Path $scratch 'provenance'
    $provenanceHome = Join-Path $provenanceRoot 'home'
    $provenanceProject = Join-Path $provenanceRoot 'project'
    [IO.Directory]::CreateDirectory($provenanceHome) | Out-Null
    [IO.Directory]::CreateDirectory($provenanceProject) | Out-Null
    $keys = @('contract-guardian','dashboard-a11y','migration-reviewer','studio-architect','studio-tester','sync-debugger')
    foreach ($key in $keys) {
        $gitInfo = [Diagnostics.ProcessStartInfo]::new()
        $gitInfo.FileName = (Get-Command git).Source
        $gitInfo.UseShellExecute = $false
        $gitInfo.CreateNoWindow = $true
        $gitInfo.RedirectStandardOutput = $true
        $gitInfo.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
        $gitInfo.ArgumentList.Add('show')
        $gitInfo.ArgumentList.Add("HEAD:.claude/agents/$key.md")
        $gitProcess = [Diagnostics.Process]::Start($gitInfo)
        $sourceText = $gitProcess.StandardOutput.ReadToEnd()
        $gitProcess.WaitForExit()
        if ($gitProcess.ExitCode -ne 0) { throw "git show failed: $key" }
        Put $provenanceProject ".claude/agents/$key.md" $sourceText
    }
    $provenanceResult = Invoke-Isolated $scripts.original $provenanceHome $provenanceProject
    foreach ($key in $keys) {
        $actual = [IO.File]::ReadAllText((Join-Path $provenanceProject ".codex/agents/$key.toml")).Replace("`r`n", "`n")
        $expected = [IO.File]::ReadAllText((Join-Path $run.backup "$key/A-current.toml")).Replace("`r`n", "`n")
        Assert-Proof "provenance $key historical sync reproduces A-current" ($actual -eq $expected)
    }
    $completed = $true
} catch {
    $log.Add($_.ToString())
    throw
} finally {
    [IO.File]::WriteAllText($logPath, ($log -join "`n`n"))
    $report = [ordered]@{
        passed = ($completed -and $assertions.Count -gt 0 -and @($assertions | Where-Object { -not $_.passed }).Count -eq 0 -and $cases.Count -eq 6)
        assertionCount=$assertions.Count; elapsedSeconds=$timer.Elapsed.TotalSeconds; scratch=$scratch
        source=@{ original=$scripts.original; originalSha256=(Get-FileHash -LiteralPath $scripts.original).Hash; candidate=$scripts.candidate; candidateSha256=(Get-FileHash -LiteralPath $scripts.candidate).Hash }
        subprocessCount=@($log | Where-Object { $_.StartsWith('SCRIPT=') }).Count
        assertions=$assertions; cases=$cases; logPath=$logPath
        limits=@('Synthetic fixtures only; real personal home and real project never passed to sync scripts.', 'Hooks and MCP integrations absent in fixtures; no hook or MCP integration behavior verified.', 'File hashes exclude pwsh AppData runtime cache; existing-file ACLs checked; timestamps and directory ACLs not compared.', 'HOME inherited unchanged; safety relies on inspected scripts using USERPROFILE exclusively.', 'Temporary fixture tree retained for review; no deletion performed.')
    }
    $report | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Output "sync proof: passed=$($report.passed); assertions=$($report.assertionCount); subprocesses=$($report.subprocessCount)"
    Write-Output "report: $reportPath"
    Write-Output "log: $logPath"
}
