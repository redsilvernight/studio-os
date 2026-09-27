; Studio OS Desktop - NSIS installer hooks (per-user install, no elevation).
;
; The frozen daemon lives in "$INSTDIR\sidecar\" and may still be running (it can
; outlive the window in persist mode): stop it before files are replaced or
; removed, or Windows keeps them locked. Only a studio-daemon.exe running from
; this install folder is stopped: a daemon of another channel installed side by
; side, or a developer's own daemon, is left alone. PowerShell and taskkill are
; fixed system binaries (never resolved through PATH); without administrator
; rights they only see the current user's own processes. The install folder is
; handed over in an environment variable, never spliced into the command line.
;
; Nothing here touches user data. The Vault, workspaces, repositories and
; ".studio" folders are never inside the install directory or these paths.
;
; STUDIO_DATA_DIR is the daemon data folder under %APPDATA%; a channel build
; defines it before including this file (desktop/scripts/make-config.mjs).

!ifndef STUDIO_DATA_DIR
  !define STUDIO_DATA_DIR "StudioOS"
!endif

!macro StudioStopDaemon
  System::Call 'Kernel32::SetEnvironmentVariable(t "STUDIO_INSTDIR", t "$INSTDIR")'
  nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$dir = [IO.Path]::GetFullPath($$env:STUDIO_INSTDIR).TrimEnd('\') + '\'; Get-CimInstance Win32_Process -Filter \"Name = 'studio-daemon.exe'\" | Where-Object { $$_.ExecutablePath -and $$_.ExecutablePath.StartsWith($$dir, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { & (Join-Path $$env:SystemRoot 'System32\taskkill.exe') /F /T /PID $$_.ProcessId }"`
  Pop $0
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
    RmDir /r "$APPDATA\${STUDIO_DATA_DIR}"
  ${EndIf}
!macroend
