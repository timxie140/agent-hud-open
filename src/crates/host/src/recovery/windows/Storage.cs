using System;
using System.IO;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace AgentHudRecovery {
    public sealed class Manifest {
        public string runId { get; set; }
        public int monitorPid { get; set; }
        public string monitorCreated { get; set; }
        public string monitorPath { get; set; }
        public int guiPid { get; set; }
        public string guiCreated { get; set; }
        public string guiPath { get; set; }
    }
    internal sealed class Storage {
        internal readonly string DirectoryPath, ManifestPath, MutexName;
        private static readonly SecurityIdentifier User = WindowsIdentity.GetCurrent().User;
        private static readonly SecurityIdentifier SystemSid = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
        internal static string Hash(string path) {
            using (SHA256 sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(path).ToUpperInvariant()))).Replace("-", "").ToLowerInvariant();
        }
        internal static string FileHash(string path) {
            using (SHA256 sha = SHA256.Create()) using (FileStream f = File.OpenRead(path)) return BitConverter.ToString(sha.ComputeHash(f)).Replace("-", "");
        }
        internal Storage(string root, string exe) {
            string key = Hash(exe); DirectoryPath = Path.GetFullPath(Path.Combine(root, key)); ManifestPath = Path.Combine(DirectoryPath, "manifest.json"); MutexName = "Global\\AgentHUDRecovery-" + key + "-lock";
        }
        private static void RejectReparse(string path) {
            string full = Path.GetFullPath(path), root = Path.GetPathRoot(full);
            string current = root;
            foreach (string part in full.Substring(root.Length).Split(new char[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar }, StringSplitOptions.RemoveEmptyEntries)) {
                current = Path.Combine(current, part);
                try { if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new IOException("reparse point rejected"); }
                catch (FileNotFoundException) { }
                catch (DirectoryNotFoundException) { }
            }
        }
        internal void ValidatePath() { RejectReparse(DirectoryPath); RejectReparse(ManifestPath); }
        internal void EnsureDirectory() {
            ValidatePath();
            Directory.CreateDirectory(DirectoryPath);
            ValidatePath();
            DirectorySecurity s = new DirectorySecurity(); s.SetAccessRuleProtection(true, false);
            InheritanceFlags flags = InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit;
            s.AddAccessRule(new FileSystemAccessRule(User, FileSystemRights.FullControl, flags, PropagationFlags.None, AccessControlType.Allow));
            s.AddAccessRule(new FileSystemAccessRule(SystemSid, FileSystemRights.FullControl, flags, PropagationFlags.None, AccessControlType.Allow));
            Directory.SetAccessControl(DirectoryPath, s);
        }
        internal static EventWaitHandle Event(string name, bool create) {
            if (!create) return EventWaitHandle.OpenExisting(name, EventWaitHandleRights.Modify | EventWaitHandleRights.Synchronize);
            EventWaitHandleSecurity s = new EventWaitHandleSecurity(); s.SetAccessRuleProtection(true, false);
            s.AddAccessRule(new EventWaitHandleAccessRule(User, EventWaitHandleRights.FullControl, AccessControlType.Allow));
            s.AddAccessRule(new EventWaitHandleAccessRule(SystemSid, EventWaitHandleRights.FullControl, AccessControlType.Allow));
            bool made; EventWaitHandle e = new EventWaitHandle(false, EventResetMode.ManualReset, name, out made, s);
            if (!made) { e.Dispose(); throw new InvalidOperationException("event already exists"); } return e;
        }
        internal Mutex Lock(out bool owned) {
            MutexSecurity s = new MutexSecurity(); s.SetAccessRuleProtection(true, false);
            s.AddAccessRule(new MutexAccessRule(User, MutexRights.FullControl, AccessControlType.Allow));
            s.AddAccessRule(new MutexAccessRule(SystemSid, MutexRights.FullControl, AccessControlType.Allow));
            bool created; Mutex m = new Mutex(false, MutexName, out created, s);
            try { owned = m.WaitOne(0); } catch (AbandonedMutexException) { owned = true; } return m;
        }
        internal Manifest Read() {
            ValidatePath();
            using (FileStream stream = new FileStream(ManifestPath, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                if (stream.Length > 16384) throw new InvalidDataException("manifest too large");
                byte[] bytes = new byte[checked((int)stream.Length)]; int offset = 0;
                while (offset < bytes.Length) { int n = stream.Read(bytes, offset, bytes.Length - offset); if (n == 0) throw new EndOfStreamException(); offset += n; }
                if (stream.ReadByte() != -1) throw new InvalidDataException("manifest too large");
                return new JavaScriptSerializer().Deserialize<Manifest>(new UTF8Encoding(false, true).GetString(bytes));
            }
        }
        internal void Publish(Manifest m) {
            string tmp = Path.Combine(DirectoryPath, m.runId + ".tmp");
            ValidatePath(); RejectReparse(tmp);
            using (FileStream stream = new FileStream(tmp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            using (StreamWriter writer = new StreamWriter(stream, new UTF8Encoding(false))) writer.Write(new JavaScriptSerializer().Serialize(m));
            if (File.Exists(ManifestPath)) File.Replace(tmp, ManifestPath, null); else File.Move(tmp, ManifestPath);
        }
        internal void DeleteOwn(string runId) {
            ValidatePath();
            if (File.Exists(ManifestPath) && Read().runId == runId) File.Delete(ManifestPath);
        }
        internal void Log(string msg) {
            try {
                string file = Path.Combine(DirectoryPath, "recovery.log");
                ValidatePath(); RejectReparse(file); RejectReparse(file + ".1"); RejectReparse(file + ".2");
                string line = DateTime.UtcNow.ToString("o") + " " + msg + "\r\n";
                if (Encoding.UTF8.GetByteCount(line) + 3 > 65536) return;
                if (File.Exists(file) && new FileInfo(file).Length + Encoding.UTF8.GetByteCount(line) + 3 > 65536) {
                    string old = file + ".2"; if (File.Exists(old)) File.Delete(old);
                    if (File.Exists(file + ".1")) File.Move(file + ".1", old);
                    File.Move(file, file + ".1");
                }
                File.AppendAllText(file, line);
            } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}
