; ============================================================
; Agent-Customer 电商AI客服助手 — Inno Setup 安装脚本
;
; 将 PyInstaller 产物 dist/AgentCustomer/ 打包为单个 setup.exe，
; 用户双击后自动解压安装、创建快捷方式、写入卸载项。
;
; 安装位置：%LocalAppData%\Programs\Agent-Customer（用户目录）
;   - 免管理员（PrivilegesRequired=lowest）
;   - 应用把数据库/日志/config.json/user_data 写在用户数据目录
;     （见 utils/runtime_path.py），安装目录只存程序文件。
;
; 编译命令（ISCC.exe 路径按实际安装位置调整）：
;   ISCC.exe scripts\installer.iss                 （用默认版本号）
;   ISCC.exe /DAppVersion=1.3 scripts\installer.iss （指定版本号）
; 实际构建由 scripts\build_win_exe.py 调用，自动从 git tag 读取版本号。
; 产物：dist\installer\Agent-Customer-Setup-<version>.exe
; ============================================================

#define AppName      "Agent-Customer"
; 版本号可被 ISCC /DAppVersion=x.y.z 覆盖（build_win_exe.py 会从 git tag 传入）；
; 未传入时用默认占位版本。
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#define AppPublisher "Agent-Customer"
#define AppExe       "AgentCustomer.exe"
; 源目录：PyInstaller 的 onedir 产物
#define SourceDir    "..\dist\AgentCustomer"

[Setup]
AppId={{8F3A2C1E-7B4D-4E5F-9A6B-2C8D1E3F5A7B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
; 免管理员：装到用户目录
PrivilegesRequired=lowest
; 输出单个安装程序
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
; 用真 ico 作为安装程序图标（icon/icon.ico 实为 PNG，Inno 不接受，故用转换后的副本）
SetupIconFile=..\icon\icon_setup.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; 中文界面
ShowLanguageDialog=no
; 64 位安装
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
; 官方未附带中文 .isl，用英文编译，下方 [CustomMessages] 覆盖为中文
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.WelcomeLabel1=欢迎使用 [name] 安装向导
english.WelcomeLabel2=将在您的计算机上安装 [name/ver]。%n%n建议您在继续之前关闭所有其他应用程序。
english.FinishedHeadingLabel=安装完成
english.FinishedLabel=安装向导已在您的计算机上完成 [name] 的安装。
english.ClickFinish=点击"完成"退出安装向导。
english.RunEntryExec=启动 %1
english.SelectDirLabel3=安装向导将把 [name] 安装到以下文件夹。
english.ButtonInstall=安装(&I)
english.ButtonNext=下一步(&N) >
english.ButtonBack=< 上一步(&B)
english.ButtonCancel=取消
english.ButtonFinish=完成(&F)
english.ExitSetupTitle=退出安装
english.ExitSetupMessage=安装尚未完成。如果现在退出，程序将不会被安装。%n%n您可以稍后再次运行安装程序完成安装。%n%n确定退出安装向导吗？

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
; 打包整个 onedir 产物（exe + _internal，含已打进去的 Playwright 驱动）
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 不打 config.json（含 LLM api_key），首次运行由应用自动生成默认配置

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; 安装完成后可选直接运行
Filename: "{app}\{#AppExe}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(
      HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      '{#AppName}'
    );
end;

// 不配置 [UninstallDelete]：数据库、日志、配置和浏览器登录态位于用户数据目录，
// 卸载程序必须保留这些用户数据，避免误删历史会话和凭据。
