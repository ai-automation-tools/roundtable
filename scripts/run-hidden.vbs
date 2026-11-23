' Run a PowerShell script with no console window at all.
'
' Task Scheduler launches pwsh.exe as a console application, so conhost paints
' a window on the interactive desktop *before* PowerShell parses
' -WindowStyle Hidden. The window is unavoidable that way; it flashes on every
' fire. wscript.exe is a windowless host, and Shell.Run(cmd, 0, True) starts
' the child hidden and waits for it, so the exit code still reaches the task.
'
' Keep this file ASCII, no BOM -- wscript chokes on a UTF-8 BOM.
'
' Usage: wscript.exe run-hidden.vbs "<full path to .ps1>" [extra pwsh args...]

Option Explicit

Dim shell, cmd, i

If WScript.Arguments.Count < 1 Then WScript.Quit 2

Set shell = CreateObject("WScript.Shell")

cmd = """C:\Program Files\PowerShell\7\pwsh.exe""" & _
      " -NoProfile -ExecutionPolicy Bypass -File """ & WScript.Arguments(0) & """"

' WScript.Arguments has already stripped the quotes, so re-quote any argument
' with a space in it (a path), or pwsh would split it in two.
Dim a
For i = 1 To WScript.Arguments.Count - 1
    a = WScript.Arguments(i)
    If InStr(a, " ") > 0 Then a = """" & a & """"
    cmd = cmd & " " & a
Next

WScript.Quit shell.Run(cmd, 0, True)
