; Studio OS Desktop - NSIS installer hooks (per-user install, no elevation).
;
; The frozen daemon lives in "$INSTDIR\sidecar\" and may still be running (it can
; outlive the window in persist mode): stop it before files are replaced or
; removed, or Windows keeps them locked. taskkill is the fixed system binary
; (never resolved through PATH); without administrator rights it can only see
; the current user's own processes.
;
; Nothing here touches user data. The Vault, workspaces, repositories and
; ".studio" folders are never inside the install directory or these paths.

!macro StudioStopDaemon
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM studio-daemon.exe'
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
    RmDir /r "$APPDATA\StudioOS"
  ${EndIf}
!macroend
