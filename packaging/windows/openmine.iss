; Inno Setup script for the Windows installer.
;
;   iscc /DAppVersion=1.0.0 packaging\windows\openmine.iss
;
; Expects the PyInstaller build in dist\OpenMine (see openmine.spec).
; Installing a newer version over an older one updates it in place.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6C9D7E1A-4B0E-4D55-9C1D-0E5A7F3B2A61}
AppName=OpenMine
AppVersion={#AppVersion}
AppVerName=OpenMine {#AppVersion}
AppPublisher=OpenMine contributors
AppPublisherURL=https://github.com/oreo1298/OpenMine
AppSupportURL=https://github.com/oreo1298/OpenMine/issues
AppUpdatesURL=https://github.com/oreo1298/OpenMine/releases
DefaultDirName={autopf}\OpenMine
DefaultGroupName=OpenMine
DisableProgramGroupPage=yes
; Installs for the current user without admin rights; can be switched to all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=OpenMine-{#AppVersion}-windows-setup
SetupIconFile=openmine.ico
UninstallDisplayIcon={app}\OpenMine.exe
UninstallDisplayName=OpenMine
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Drop files from older versions before copying the new ones.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\OpenMine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OpenMine"; Filename: "{app}\OpenMine.exe"; AppUserModelID: "io.github.oreo1298.OpenMine"
Name: "{autodesktop}\OpenMine"; Filename: "{app}\OpenMine.exe"; Tasks: desktopicon; AppUserModelID: "io.github.oreo1298.OpenMine"

[Run]
Filename: "{app}\OpenMine.exe"; Description: "{cm:LaunchProgram,OpenMine}"; Flags: nowait postinstall skipifsilent
