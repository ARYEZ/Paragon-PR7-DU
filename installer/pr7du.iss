; Paragon PR7-DU installer (Inno Setup 6): disk usage, the way WizTree shows it.
;   iscc /DAppVersion=0.1.0 installer\pr7du.iss      (after pyinstaller pr7du.spec has made dist\PR7-DU)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-DU, with a Start menu entry. PR7-DU asks for
; administrator rights only when you choose FASTER AS ADMINISTRATOR (reading a drive's MFT needs them).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{9DFF1917-658D-4BE5-8C19-A88E7150AC24}
AppName=Paragon PR7-DU
AppVersion={#AppVersion}
AppVerName=Paragon PR7-DU {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-DU
DefaultGroupName=Paragon PR7-DU
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-DU-Setup-{#AppVersion}
SetupIconFile=..\pr7du\icons\app.ico
UninstallDisplayIcon={app}\PR7-DU.exe
UninstallDisplayName=Paragon PR7-DU
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-DU\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-DU"; Filename: "{app}\PR7-DU.exe"; Comment: "See what fills your disks"
Name: "{autodesktop}\Paragon PR7-DU"; Filename: "{app}\PR7-DU.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-DU.exe"; Description: "{cm:LaunchProgram,Paragon PR7-DU}"; Flags: nowait postinstall skipifsilent
; Updates (Check for updates runs this installer with /SILENT /relaunch=1): start PR7-DU again when done.
Filename: "{app}\PR7-DU.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
