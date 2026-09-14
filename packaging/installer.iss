; Inno Setup script - builds the Windows installer.
; Compile with:  iscc packaging\installer.iss
; Expects PyInstaller output in dist\QSL Sender\

#define AppName "QSL Sender"
#define AppVersion "0.1.0"  ; x-release-please-version
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
OutputDir=..\dist
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

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent
