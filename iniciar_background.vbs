Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Obtener directorio del script
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Crear carpeta de logs si no existe
logsDir = scriptDir & "\logs"
If Not fso.FolderExists(logsDir) Then
    fso.CreateFolder(logsDir)
End If

' Ejecutar Python en background sin ventana
WshShell.CurrentDirectory = scriptDir
WshShell.Run "cmd /c python servidor_lan.py > logs\servidor.log 2>&1", 0, False

WScript.Echo "Portal de Seguros iniciado en background." & vbCrLf & _
             "Los logs se guardan en: logs\servidor.log" & vbCrLf & vbCrLf & _
             "Para detener: taskkill /f /im python.exe"
