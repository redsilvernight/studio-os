; Studio OS Desktop - NSIS installer hooks (per-user install, no elevation).
;
; The frozen daemon lives in "$INSTDIR\sidecar\" and may still be running (it can
; outlive the window in persist mode): stop it before files are replaced or
; removed, or Windows keeps them locked.
;
; FAIL-CLOSED SCOPE (B3): only a studio-daemon.exe whose executable path is
; under "$INSTDIR\sidecar\" is ever stopped, and only by PID. A developer
; daemon (or any other copy) running from anywhere else is left alone.
; Enumeration goes through the fixed system PowerShell (never resolved through
; PATH); without administrator rights it can only see the current user's own
; processes. If enumeration fails, nothing is killed: the install then reports
; locked files instead of stopping the wrong process.
;
; Nothing here touches user data. The Vault, workspaces, repositories and
; ".studio" folders are never inside the install directory or these paths.

!macro StudioStopDaemon
  ; Publish the sidecar root to the child process so no quoted path has to be
  ; embedded in the command line (install paths may contain spaces or brackets).
  System::Call 'kernel32::SetEnvironmentVariable(t "STUDIO_NSI_SIDECAR_ROOT", t "$INSTDIR\sidecar")'
  nsExec::ExecToStack "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $\"& { $$procs = Get-CimInstance Win32_Process -Filter $\"Name='studio-daemon.exe'$\" -ErrorAction SilentlyContinue; $$root = $$env:STUDIO_NSI_SIDECAR_ROOT; foreach ($$p in $$procs) { if ($$root -and $$p.ExecutablePath -and $$p.ExecutablePath.StartsWith($$root + '\', [System.StringComparison]::OrdinalIgnoreCase)) { try { Stop-Process -Id $$p.ProcessId -Force -ErrorAction Stop } catch {} } } }$\""
  Pop $0
  System::Call 'kernel32::SetEnvironmentVariable(t "STUDIO_NSI_SIDECAR_ROOT", t "")'
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro StudioStopDaemon
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro StudioStopDaemon
!macroend

; Reached only when the user ticked "Delete the application data" (unchecked by
; default). Removes the daemon's own data folder as well - its configuration,
; local queue, logs and caches. Credentials stay in the Windows Credential
; Manager and are documented as a manual step.
!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
    RmDir /r "$APPDATA\StudioOS"
  ${EndIf}
!macroend
