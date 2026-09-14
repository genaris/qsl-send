; Inno Setup script - builds the Windows installer.
; Compile with:  iscc packaging\installer.iss
; Expects PyInstaller output in dist\QSL Sender\

#define AppName "QSL Sender"
#define AppVersion "0.1.0"
#define AppPublisher "LU2AOG"
#define AppExe "QSL Sender.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; Per-user install needs no administrator rights, which matters when
; colleagues cannot install software on a work machine.
PrivilegesRequired=lowest
; Separate from dist/, which holds PyInstaller's compiled folder. Keeping
; them apart is what lets the workflow publish just the installer.
OutputDir=..\installer
OutputBaseFilename=QSL-Sender-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\dist\QSL Sender\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Beside the executable as well as inside _internal, so the application can
; find it to seed a new user's settings on first run.
Source: "..\qsl-send.example.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\template.jpg"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent
