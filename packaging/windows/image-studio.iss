; The Windows installer, compiled by packaging/build.py with Inno Setup 6:
;   ISCC /DAppVersion=2.0.0 /DSourceDir=<built app folder> /DOutputDir=<dist> image-studio.iss
; It installs for the current user only (no administrator prompt), like most apps that
; update themselves. Models, pictures and settings live in the user's folders and stay
; when the app is removed; the engine's libraries (several GB, re-downloadable) go with it.

#ifndef AppVersion
  #error Pass /DAppVersion=...
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=...
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
AppId={{F97DA1BE-B44D-49FF-B94F-98F4A098C59F}
AppName=Image Studio
AppVersion={#AppVersion}
AppVerName=Image Studio {#AppVersion}
AppPublisher=Image Studio contributors
DefaultDirName={autopf}\Image Studio
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=ImageStudio-{#AppVersion}-Setup
SetupIconFile={#SourceDir}\image-studio.ico
UninstallDisplayIcon={app}\Image Studio.exe
UninstallDisplayName=Image Studio
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An update replaces the code and the bundled Python wholesale, so no stale file survives.
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\integrations"
Type: filesandordirs; Name: "{app}\training"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; The same AppUserModelID as the window (desktop/app.py), so a pinned taskbar icon is this app.
Name: "{autoprograms}\Image Studio"; Filename: "{app}\Image Studio.exe"; AppUserModelID: "ImageStudio.Desktop"
Name: "{autodesktop}\Image Studio"; Filename: "{app}\Image Studio.exe"; AppUserModelID: "ImageStudio.Desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\Image Studio.exe"; Description: "{cm:LaunchProgram,Image Studio}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{localappdata}\Image Studio\engine"
Type: filesandordirs; Name: "{localappdata}\Image Studio\logs"
