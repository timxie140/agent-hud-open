using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;

namespace AgentHudRecovery {
    internal static class Native {
        [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessTimes(IntPtr process, out long creation, out long exit, out long kernel, out long user);
        [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool QueryFullProcessImageName(IntPtr process, int flags, StringBuilder name, ref int size);
        [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
        [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(IntPtr token, int type, IntPtr data, int length, out int required);
        [StructLayout(LayoutKind.Sequential)] struct SidAndAttributes { public IntPtr Sid; public uint Attributes; }
        [StructLayout(LayoutKind.Sequential)] struct TokenUser { public SidAndAttributes User; }

        internal static string CurrentSid { get { return WindowsIdentity.GetCurrent().User.Value; } }
        internal static string PathOf(int pid) {
            IntPtr h = OpenProcess(0x1000, false, pid);
            if (h == IntPtr.Zero) throw new Win32Exception();
            try {
                StringBuilder b = new StringBuilder(32768); int n = b.Capacity;
                if (!QueryFullProcessImageName(h, 0, b, ref n)) throw new Win32Exception();
                return Path.GetFullPath(b.ToString());
            } finally { CloseHandle(h); }
        }
        internal static string SidOf(int pid) {
            IntPtr h = OpenProcess(0x1000, false, pid), token = IntPtr.Zero, data = IntPtr.Zero;
            if (h == IntPtr.Zero) throw new Win32Exception();
            try {
                if (!OpenProcessToken(h, 8, out token)) throw new Win32Exception();
                int n; GetTokenInformation(token, 1, IntPtr.Zero, 0, out n);
                data = Marshal.AllocHGlobal(n);
                if (!GetTokenInformation(token, 1, data, n, out n)) throw new Win32Exception();
                TokenUser u = (TokenUser)Marshal.PtrToStructure(data, typeof(TokenUser));
                return new SecurityIdentifier(u.User.Sid).Value;
            } finally { if (data != IntPtr.Zero) Marshal.FreeHGlobal(data); if (token != IntPtr.Zero) CloseHandle(token); CloseHandle(h); }
        }
        internal static string Created(Process p) { return p.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(System.Globalization.CultureInfo.InvariantCulture); }
        internal static bool SamePath(string a, string b) { return String.Equals(Path.GetFullPath(a), Path.GetFullPath(b), StringComparison.OrdinalIgnoreCase); }
        internal static void Verify(Process p, string created, string path) {
            IntPtr h = p.Handle, token = IntPtr.Zero, data = IntPtr.Zero;
            try {
                long c, e, k, u;
                if (!GetProcessTimes(h, out c, out e, out k, out u)) throw new Win32Exception();
                StringBuilder b = new StringBuilder(32768); int n = b.Capacity;
                if (!QueryFullProcessImageName(h, 0, b, ref n)) throw new Win32Exception();
                if (!OpenProcessToken(h, 8, out token)) throw new Win32Exception();
                int size; GetTokenInformation(token, 1, IntPtr.Zero, 0, out size);
                data = Marshal.AllocHGlobal(size);
                if (!GetTokenInformation(token, 1, data, size, out size)) throw new Win32Exception();
                TokenUser identity = (TokenUser)Marshal.PtrToStructure(data, typeof(TokenUser));
                if (c.ToString(System.Globalization.CultureInfo.InvariantCulture) != created || !SamePath(b.ToString(), path) || new SecurityIdentifier(identity.User.Sid).Value != CurrentSid) throw new InvalidOperationException("process identity mismatch");
            } finally { if (data != IntPtr.Zero) Marshal.FreeHGlobal(data); if (token != IntPtr.Zero) CloseHandle(token); }
        }
        internal static string Quote(string value) {
            if (value == null) throw new ArgumentNullException("value");
            StringBuilder b = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value) {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') { b.Append('\\', slashes * 2 + 1); b.Append('"'); }
                else { b.Append('\\', slashes); b.Append(c); }
                slashes = 0;
            }
            b.Append('\\', slashes * 2); b.Append('"'); return b.ToString();
        }
    }
}
