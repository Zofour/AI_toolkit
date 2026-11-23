# 列出所有 class=ConsoleWindowClass 的顶层窗口（标题 + pid），用来检测“黑框”
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinEnum {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    public static List<string> Consoels() {
        var list = new List<string>();
        EnumWindows((h, l) => {
            var sb = new StringBuilder(256);
            GetClassName(h, sb, 256);
            if (sb.ToString() == "ConsoleWindowClass") {
                var t = new StringBuilder(512);
                GetWindowText(h, t, 512);
                uint pid; GetWindowThreadProcessId(h, out pid);
                list.Add(pid + "|" + (IsWindowVisible(h) ? "vis" : "hid") + "|" + t.ToString());
            }
            return true;
        }, IntPtr.Zero);
        return list;
    }
}
"@
$all = @()
for ($i = 0; $i -lt 60; $i++) {
    $all += [WinEnum]::Consoels()
    Start-Sleep -Milliseconds 120
}
$all | Select-Object -Unique | ForEach-Object { $_ }
