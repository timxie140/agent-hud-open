; A legacy install has no helper and no watchdog. Every helper-enabled package
; includes this pre-uninstall hook, including the old uninstaller on an upgrade.
!macro AGENTHUD_STOP_RECOVERY
  ${If} ${FileExists} "$INSTDIR\agent-hud-recovery.exe"
    DetailPrint "Stopping Agent HUD recovery and its GUI for maintenance..."
    Push $0
    StrCpy $0 1
    ClearErrors
    ExecWait '"$INSTDIR\agent-hud-recovery.exe" --stop-for-update' $0
    ${If} ${Errors}
      StrCpy $0 1
    ${EndIf}
    ${If} $0 != 0
      DetailPrint "Agent HUD recovery did not confirm maintenance; installation stopped."
      ${IfNot} ${Silent}
        MessageBox MB_OK|MB_ICONSTOP "Agent HUD could not stop safely for maintenance. Quit Agent HUD normally, then run this installer again."
      ${EndIf}
      Pop $0
      SetErrorLevel 1
      Abort
    ${EndIf}
    Pop $0
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro AGENTHUD_STOP_RECOVERY
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro AGENTHUD_STOP_RECOVERY
!macroend
