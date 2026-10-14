; Inno Setup script for WinAirdrop.
; Built by .github/workflows/release.yml:
;   ISCC.exe /DAppVersion=1.0.0 /DSourceDir=..\dist\WinAirdrop installer\WinAirdrop.iss
;
; Per-user install (no admin rights needed) into %LOCALAPPDATA%\Programs\WinAirdrop.
; Only the optional firewall step asks for administrator permission.
; The language chosen at the start of the setup is also used by WinAirdrop
; (saved as WINAIRDROP_LANGUAGE in %APPDATA%\WinAirdrop\.env).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  ; PyInstaller --onedir output: WinAirdrop.exe + _internal\
  #define SourceDir "..\dist\WinAirdrop"
#endif

[Setup]
AppId={{6F2B8B1E-4D7A-4C55-9B3E-2A9D5E7C1F40}
AppName=WinAirdrop
AppVersion={#AppVersion}
AppVerName=WinAirdrop {#AppVersion}
AppPublisher=josedag31
AppCopyright=Copyright (C) 2026 josedag31
VersionInfoCompany=josedag31
VersionInfoCopyright=Copyright (C) 2026 josedag31
VersionInfoDescription=WinAirdrop Setup
AppPublisherURL=https://github.com/josedag31/WinAirdrop
AppSupportURL=https://github.com/josedag31/WinAirdrop/issues
AppUpdatesURL=https://github.com/josedag31/WinAirdrop/releases
DefaultDirName={localappdata}\Programs\WinAirdrop
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=WinAirdrop-Setup-v{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\WinAirdrop.exe
UninstallDisplayName=WinAirdrop
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
MinVersion=10.0
; Always ask for the language (preselects the Windows language).
ShowLanguageDialog=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
; Shown at the bottom of every setup page.
english.BeveledLabel=WinAirdrop · Created by josedag31
spanish.BeveledLabel=WinAirdrop · Creado por josedag31

[CustomMessages]
english.TaskStartup=Start WinAirdrop when I sign in to Windows (recommended)
spanish.TaskStartup=Iniciar WinAirdrop al iniciar sesión en Windows (recomendado)
english.TaskStartupHelp=If WinAirdrop isn't running, your iPhone can't send anything.
spanish.TaskStartupHelp=Si WinAirdrop no está funcionando, tu iPhone no puede enviar nada.
english.TaskFirewall=Allow WinAirdrop through the Windows Firewall, on private networks only (recommended, asks for administrator permission)
spanish.TaskFirewall=Permitir WinAirdrop en el Firewall de Windows, solo en redes privadas (recomendado, pide permiso de administrador)
english.TaskFirewallHelp=Without this, the firewall blocks your iPhone. You can also do it later from the settings page.
spanish.TaskFirewallHelp=Sin esto, el firewall bloquea a tu iPhone. También puedes hacerlo después desde la página de ajustes.
english.FirewallStatus=Allowing WinAirdrop through the firewall...
spanish.FirewallStatus=Permitiendo WinAirdrop en el firewall...
english.RunNow=Start WinAirdrop and open its settings
spanish.RunNow=Iniciar WinAirdrop y abrir sus ajustes
english.ShortcutComment=Receive files from your iPhone. Open it again to see the settings.
spanish.ShortcutComment=Recibe archivos de tu iPhone. Ábrelo de nuevo para ver los ajustes.
english.AppLanguage=en
spanish.AppLanguage=es

[Tasks]
Name: "startup"; Description: "{cm:TaskStartup}"; GroupDescription: "{cm:TaskStartupHelp}"
Name: "firewall"; Description: "{cm:TaskFirewall}"; GroupDescription: "{cm:TaskFirewallHelp}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\WinAirdrop"; Filename: "{app}\WinAirdrop.exe"; Comment: "{cm:ShortcutComment}"

[Registry]
; Start with Windows: the standard per-user Run key (the settings page uses the same value).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "WinAirdrop"; ValueData: """{app}\WinAirdrop.exe"""; Tasks: startup; Flags: uninsdeletevalue

[InstallDelete]
; Startup shortcut from older versions (now the Run key is used).
Type: files; Name: "{userstartup}\WinAirdrop.lnk"

[Run]
; Firewall rules on the Private profile only, added by WinAirdrop itself.
; ShellExec + runas shows a UAC prompt that says "WinAirdrop".
Filename: "{app}\WinAirdrop.exe"; Parameters: "--elevated --firewall 8770"; \
  Verb: "runas"; Flags: shellexec waituntilterminated; Tasks: firewall; \
  StatusMsg: "{cm:FirewallStatus}"
; First start opens the settings page in the browser automatically.
Filename: "{app}\WinAirdrop.exe"; Description: "{cm:RunNow}"; Flags: nowait postinstall

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM WinAirdrop.exe"; Flags: runhidden; RunOnceId: "StopWinAirdrop"
Filename: "{app}\WinAirdrop.exe"; Parameters: "--elevated --remove-firewall"; \
  Verb: "runas"; Flags: shellexec waituntilterminated; RunOnceId: "RemoveFirewall"

[UninstallDelete]
Type: files; Name: "{userstartup}\WinAirdrop.lnk"

[Code]
{ "Start with Windows" may also have been turned on from the settings page. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'WinAirdrop');
end;

{ Leave the setup language ("en" or "es", plain ASCII) for WinAirdrop. On its
  next start it saves it as WINAIRDROP_LANGUAGE in its .env and deletes this
  file. The .env itself (settings and token) is never touched by the setup. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir: String;
begin
  if CurStep = ssPostInstall then
  begin
    Dir := ExpandConstant('{userappdata}\WinAirdrop');
    ForceDirectories(Dir);
    SaveStringToFile(Dir + '\installer-language', CustomMessage('AppLanguage'), False);
  end;
end;
