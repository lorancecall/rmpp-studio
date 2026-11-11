; Inno Setup script for rmpp-studio (built by windows/build.ps1, which passes /DAppVersion=x.y.z).
; Per-user install (no admin): %LOCALAPPDATA%\Programs\rmpp-studio, with the rmpp-ctl command in {app}\cli
; (optionally added to the user's PATH; removed again on uninstall).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3D2B8C-4E1A-4C7B-9A55-2D8E0B7C41A9}
AppName=rmpp-studio
AppVersion={#AppVersion}
AppVerName=rmpp-studio {#AppVersion}
AppPublisher=lorancecall
AppComments=Drive, record and edit reMarkable Paper Pro tutorials over SSH
DefaultDirName={autopf}\rmpp-studio
DefaultGroupName=rmpp-studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=rmpp-studio-setup-{#AppVersion}
SetupIconFile=rmpp-studio.ico
UninstallDisplayIcon={app}\rmpp-studio.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes

[Tasks]
Name: "addtopath"; Description: "Add the rmpp-ctl command to PATH (use it from any terminal)"; GroupDescription: "Command line:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\rmpp-studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\rmpp-ctl\*"; DestDir: "{app}\cli"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\rmpp-studio"; Filename: "{app}\rmpp-studio.exe"
Name: "{group}\{cm:UninstallProgram,rmpp-studio}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\rmpp-studio"; Filename: "{app}\rmpp-studio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\rmpp-studio.exe"; Description: "{cm:LaunchProgram,rmpp-studio}"; Flags: nowait postinstall skipifsilent

[Code]
const
  EnvKey = 'Environment';

function PathHas(Path, Dir: string): Boolean;
begin
  Result := Pos(';' + Lowercase(Dir) + ';', ';' + Lowercase(Path) + ';') > 0;
end;

procedure AddToPath(Dir: string);
var
  Path: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Path) then
    Path := '';
  if PathHas(Path, Dir) then
    exit;
  if (Path <> '') and (Copy(Path, Length(Path), 1) <> ';') then
    Path := Path + ';';
  RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Path + Dir);
end;

procedure RemoveFromPath(Dir: string);
var
  Path, Lower, Item: string;
  P: Integer;
  NewPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Path) then
    exit;
  NewPath := '';
  Path := Path + ';';
  while Length(Path) > 0 do
  begin
    P := Pos(';', Path);
    Item := Copy(Path, 1, P - 1);
    Delete(Path, 1, P);
    Lower := Lowercase(Item);
    if (Item <> '') and (Lower <> Lowercase(Dir)) then
    begin
      if NewPath <> '' then
        NewPath := NewPath + ';';
      NewPath := NewPath + Item;
    end;
  end;
  RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', NewPath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('addtopath') then
      AddToPath(ExpandConstant('{app}\cli'))
    else
      RemoveFromPath(ExpandConstant('{app}\cli'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}\cli'));
end;
