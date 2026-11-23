' BUCT 校园网自动登录 —— 无窗口启动器
' 由 install_autostart.ps1 放入「启动」文件夹，开机登录后自动运行
Option Explicit
Dim fso, sh, base, py, candidates, i, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)

' 找 pythonw.exe（优先本机用户安装目录 / PATH）
py = ""
candidates = Array( _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"), _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"), _
  "C:\Python313\pythonw.exe", "C:\Python312\pythonw.exe", "C:\Python311\pythonw.exe")
For i = 0 To UBound(candidates)
  If fso.FileExists(candidates(i)) Then
    py = candidates(i)
    Exit For
  End If
Next
If py = "" Then
  ' 退回到 PATH 里的 pythonw
  py = "pythonw.exe"
End If

sh.CurrentDirectory = base
cmd = """" & py & """ """ & base & "\srun_autologin.py"""
sh.Run cmd, 0, False
