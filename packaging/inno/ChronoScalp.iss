; ChronoScalp per-user installer. Requires the PyInstaller onedir folders
; dist\ChronoScalpRunner and dist\ChronoScalpPanel. Does not require admin.

#define MyAppName "ChronoScalp"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "ChronoScalp"
#define MyAppURL "https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR"

[Setup]
AppId={{A7B3E4C1-6D20-4F5A-9C11-0E2B8A4D7C55}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\ChronoScalp
DefaultGroupName=ChronoScalp
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=ChronoScalp-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\runner\ChronoScalpRunner.exe
InfoBeforeFile=InfoBefore.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\..\dist\ChronoScalpRunner\*"; DestDir: "{app}\runner"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\dist\ChronoScalpPanel\*"; DestDir: "{app}\panel"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\scripts\windows\*"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\..\config\*"; DestDir: "{app}\bundled\config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..env.example"; DestDir: "{app}\bundled"; Flags: ignoreversion
Source: "..\..\docs\WINDOWS_INSTALL_FA.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\BAZRASI_SADEGHANE_FA.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\docs\RISK_DISCLAIMER.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\ChronoScalp Panel"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\start_panel.ps1"""; WorkingDir: "{app}"
Name: "{group}\Start ChronoScalp"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\start_runner.ps1"""; WorkingDir: "{app}"
Name: "{group}\Stop ChronoScalp"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\stop_runner.ps1"""; WorkingDir: "{app}"
Name: "{group}\Uninstall ChronoScalp"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ChronoScalp Panel"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\start_panel.ps1"""; WorkingDir: "{app}"
Name: "{autodesktop}\Start ChronoScalp"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\start_runner.ps1"""; WorkingDir: "{app}"
Name: "{autodesktop}\Stop ChronoScalp"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\stop_runner.ps1"""; WorkingDir: "{app}"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\install_user_data.ps1"" -InstallDir ""{app}"""; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\register_logon_task.ps1"""; Flags: runhidden waituntilterminated postinstall

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\unregister_logon_task.ps1"""; Flags: runhidden waituntilterminated

[Code]
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if MsgBox('Delete ChronoScalp user data in %APPDATA%\ChronoScalp as well? No keeps config, .env, and journals.', mbConfirmation, MB_YESNO) = IDYES then
    SaveStringToFile(ExpandConstant('{app}\delete_user_data.flag'), 'yes', False);
end;
