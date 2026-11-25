# Print "pid parentpid" for every process, one per line (used by server.js killTree when taskkill is refused).
# Uses CreateToolhelp32Snapshot, not WMI: on the author's PC a service account gets "Access denied" from Get-CimInstance (2026-11-13).
# ASCII only (Windows PowerShell 5.1 reads BOM-less files as the system code page).
$src = @'
using System; using System.Runtime.InteropServices; using System.Text;
public static class MittlerProcTree {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  struct PE { public uint dwSize; public uint cntUsage; public uint pid; public IntPtr heapId; public uint moduleId; public uint threads; public uint ppid; public int basePri; public uint flags;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string exe; }
  [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern bool Process32FirstW(IntPtr snap, ref PE e);
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern bool Process32NextW(IntPtr snap, ref PE e);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  public static string List() {
    var sb = new StringBuilder(); IntPtr snap = CreateToolhelp32Snapshot(2, 0);
    var e = new PE(); e.dwSize = (uint)Marshal.SizeOf(typeof(PE));
    if (Process32FirstW(snap, ref e)) do { sb.Append(e.pid).Append(' ').Append(e.ppid).Append('\n'); } while (Process32NextW(snap, ref e));
    CloseHandle(snap); return sb.ToString();
  }
}
'@
Add-Type -TypeDefinition $src
[MittlerProcTree]::List()
