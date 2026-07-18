; Inno Setup script for Double Scribe
; Builds a per-user installer (no admin required) from the PyInstaller onedir output.
;
;   Compile: "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" DoubleScribe.iss
;   Output:  installer\DoubleScribeSetup.exe
;
; The app is CPU-only and fully offline (Whisper 'small' bundled). It renders its UI with
; WebView2, which ships as part of Windows 11 (Evergreen runtime) -- no separate download
; needed on a standard Win11 machine. User data (transcripts, index.json) is written to
; %LOCALAPPDATA%\DoubleScribe, so it survives uninstall/reinstall and is never placed in
; the read-only install folder.

#define MyAppName "Double Scribe"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Bevington Group"
#define MyAppExeName "DoubleScribe.exe"

[Setup]
; Stable AppId so upgrades replace the same install rather than stacking.
AppId={{6E3B2C41-9A7D-4F5E-B1C8-4D2A7E9F0C13}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\DoubleScribe
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer
OutputBaseFilename=DoubleScribeSetup
SetupIconFile=app\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller onedir folder (exe + _internal + bundled model + web assets).
Source: "dist\DoubleScribe\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
