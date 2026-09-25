Option Explicit
Dim shell, fso, root, python, launcher, configFile, startCmd, candidate

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(root, "launch_app.pyw")
configFile = fso.BuildPath(root, "venv_path.txt")
startCmd = fso.BuildPath(root, "start-ui.cmd")
If Not fso.FileExists(startCmd) Then startCmd = fso.BuildPath(fso.GetParentFolderName(root), "start-ui.cmd")

python = ""

' 1. Check saved venv_path.txt
If fso.FileExists(configFile) Then
    Dim stream, line
    Set stream = fso.OpenTextFile(configFile, 1)
    If Not stream.AtEndOfStream Then
        line = Trim(stream.ReadLine())
        If fso.FileExists(fso.BuildPath(line, "Scripts\pythonw.exe")) Then
            python = fso.BuildPath(line, "Scripts\pythonw.exe")
        ElseIf fso.FileExists(fso.BuildPath(line, "venv\Scripts\pythonw.exe")) Then
            python = fso.BuildPath(line, "venv\Scripts\pythonw.exe")
        ElseIf fso.FileExists(line) Then
            python = line
        End If
    End If
    stream.Close
End If

' 2. Check local venv
If python = "" Then
    candidate = fso.BuildPath(fso.GetParentFolderName(root), "venv\Scripts\pythonw.exe")
    If fso.FileExists(candidate) Then python = candidate
End If

' 3. Check known user locations
If python = "" Then
    Dim userProfile
    userProfile = shell.ExpandEnvironmentStrings("%USERPROFILE%")
    candidate = fso.BuildPath(userProfile, "Qwen-Image-2.1\venv\Scripts\pythonw.exe")
    If fso.FileExists(candidate) Then python = candidate
End If
If python = "" And fso.FileExists("C:\Users\d.chipashvili\Qwen-Image-2.1\venv\Scripts\pythonw.exe") Then
    python = "C:\Users\d.chipashvili\Qwen-Image-2.1\venv\Scripts\pythonw.exe"
End If

' 4. If found, launch directly. Otherwise run start-ui.cmd to allow folder selection.
shell.CurrentDirectory = root
If python <> "" And fso.FileExists(python) Then
    shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & launcher & Chr(34), 0, False
ElseIf fso.FileExists(startCmd) Then
    shell.Run Chr(34) & startCmd & Chr(34), 1, False
Else
    MsgBox "The Qwen Python environment was not found. Please run start-ui.cmd.", 16, "Qwen Image Studio"
End If
