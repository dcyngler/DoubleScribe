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
#define MyAppVersion "0.4.3"
#define MyAppPublisher "Double Scribe"
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
; Needed for the in-app silent auto-updater (api.py install_update): when the running
; app's own exe/DLLs are locked, Setup closes it via Restart Manager so the copy can
; proceed -- CloseApplications=yes is Inno's default, spelled out here since the app now
; depends on this behaviour rather than just benefiting from it.
CloseApplications=yes
; Deliberately NOT RestartApplications=yes: that would have Setup auto-relaunch the app
; it just closed *in addition to* the manual "skipifnotsilent" [Run] entry below, which
; also unconditionally relaunches on a silent/very-silent install. Both firing at once
; launched DoubleScribe.exe twice right after an auto-update, and the two cold starts
; racing to import faster_whisper's `av` dependency could collide with an AV scanner
; still holding an exclusive lock on the freshly-written _core.pyd/DLLs, producing a
; transient "DLL load failed ... used by another process" crash. One relaunch path only.
RestartApplications=no

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
; Silent/very-silent installs (the in-app auto-updater) skip the checkbox above entirely,
; so relaunch unconditionally here -- this is what makes the update feel like Handy's:
; download, install, and come back up on the new version with no prompts.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent
