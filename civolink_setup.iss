; CIVOLINK QS Estimating Engine — Inno Setup installer script.
;
; Built by scripts/build_release.py (never by hand):
;   compile_installer() runs:
;     iscc /DMyAppVersion=<qs_engine.__version__> civolink_setup.iss
; which emits release/CIVOLINK-QS-Setup-<version>.exe from the
; PyInstaller --onedir tree at dist/CIVOLINK-QS/.
;
; The installer is signed + verified by the release pipeline AFTER
; compilation (see scripts/sign_artifacts.py); do not ship an
; installer that skipped those gates.

#define MyAppName "CIVOLINK QS Estimating Engine"
#ifndef MyAppVersion
  #define MyAppVersion "1.4.2"
#endif
#define MyAppPublisher "CIVOLINK"
#define MyAppExeName "CIVOLINK-QS.exe"

[Setup]
AppId={{ADE076E1-872B-477D-A9C9-A2A4DBC0AD5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\CIVOLINK QS
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=CIVOLINK-QS-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Files]
Source: "dist\CIVOLINK-QS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked
