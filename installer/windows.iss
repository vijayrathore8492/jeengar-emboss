; Inno Setup script for Jeengar Emboss. Built in CI (release.yml) after PyInstaller.
;   iscc /DVersion=1.3.0 installer\windows.iss
#ifndef Version
  #define Version "0.0.0"
#endif
#define AppName "Jeengar Emboss"
#define Publisher "Jeengar Industries LLP"
#define ExeName "Jeengar Emboss.exe"

[Setup]
AppId={{8C1F2E6A-5D3B-4B7E-9A1C-2F0E7D4B6A11}
AppName={#AppName}
AppVersion={#Version}
AppVerName={#AppName} {#Version}
AppPublisher={#Publisher}
AppPublisherURL=https://jeengar.com
AppSupportURL=https://github.com/vijayrathore8492/jeengar-emboss
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest
OutputDir=..\pkg
OutputBaseFilename=JeengarEmboss-{#Version}-windows-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; an older version is replaced in place; user data lives in %APPDATA% and is never touched
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
