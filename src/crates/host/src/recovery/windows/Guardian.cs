using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Web.Script.Serialization;

namespace AgentHudRecovery {
    public static class Guardian {
        private static string EventName(string id, string kind) { return "Local\\AgentHUDRecovery-" + id + "-" + kind; }
        private static bool Signaled(WaitHandle e) { return e.WaitOne(0); }
        private static bool ValidRunId(string id) { Guid parsed; return id != null && id.Length == 32 && Guid.TryParseExact(id, "N", out parsed) && parsed.ToString("N") == id; }
        public static int Run(Options options) {
            try { return RunInner(options); } catch { return 1; }
        }
        private static int RunInner(Options o) {
            if (o == null || String.IsNullOrWhiteSpace(o.Executable) || String.IsNullOrWhiteSpace(o.StateRoot) || !Path.IsPathRooted(o.Executable) || !Path.IsPathRooted(o.StateRoot) || o.MaxRestarts < 0 || o.MaxRestarts > 100 || o.WindowMs <= 0 || o.WindowMs > 86400000 || o.ReadyTimeoutMs <= 0 || o.ReadyTimeoutMs > 600000 || o.BackoffsMs == null || o.BackoffsMs.Length == 0 || o.BackoffsMs.Length > 100 || o.BackoffsMs.Any(x => x < 0 || x > 600000) || (o.Arguments != null && o.Arguments.Any(x => x == null))) return 1;
            string exe = Path.GetFullPath(o.Executable), hash = Storage.FileHash(exe);
            Storage storage = new Storage(o.StateRoot, exe); storage.EnsureDirectory();
            bool owned;
            using (Mutex mutex = storage.Lock(out owned)) {
                if (!owned) return 1;
                try {
                    if (!StaleManifestIsSafe(storage, exe)) return 1;
                    using (WindowStatus window = new WindowStatus()) {
                        Stopwatch clock = Stopwatch.StartNew();
                        List<long> restarts = new List<long>();
                        Process self = Process.GetCurrentProcess();
                        string monitorPath = Native.PathOf(self.Id), monitorCreated = Native.Created(self);
                        Native.Verify(self, monitorCreated, monitorPath);
                        try {
                            for (;;) {
                                if (window.Pending || window.Ended || Storage.FileHash(exe) != hash) return 0;
                                string run = Guid.NewGuid().ToString("N");
                                using (EventWaitHandle ready = Storage.Event(EventName(run, "ready"), true))
                                using (EventWaitHandle stop = Storage.Event(EventName(run, "stop"), true))
                                using (EventWaitHandle quit = Storage.Event(EventName(run, "quit"), true))
                                using (EventWaitHandle maintenance = Storage.Event(EventName(run, "maintenance"), true)) {
                                  try {
                                Dictionary<string, object> context = new Dictionary<string, object>();
                                context["runId"] = run; context["monitorPid"] = self.Id; context["monitorCreated"] = monitorCreated;
                                context["guiPath"] = exe; context["readyEvent"] = EventName(run, "ready"); context["stopEvent"] = EventName(run, "stop");
                                context["quitEvent"] = EventName(run, "quit"); context["maintenanceEvent"] = EventName(run, "maintenance");
                                ProcessStartInfo start = new ProcessStartInfo(); start.FileName = exe; start.UseShellExecute = false; start.CreateNoWindow = true; start.WorkingDirectory = Path.GetDirectoryName(exe);
                                List<string> args = new List<string>(); args.Add("--recovery-child"); if (o.Arguments != null) args.AddRange(o.Arguments);
                                start.Arguments = String.Join(" ", args.Select(Native.Quote).ToArray());
                                start.EnvironmentVariables["AGENTHUD_RECOVERY_CONTEXT"] = new JavaScriptSerializer().Serialize(context);
                                using (Process child = Process.Start(start)) {
                                    string created = Native.Created(child); Native.Verify(child, created, exe);
                                    if (Storage.FileHash(exe) != hash) { storage.Log("executable changed"); return 1; }
                                    long deadline = clock.ElapsedMilliseconds + o.ReadyTimeoutMs; bool becameReady = false, requestedQuit = false;
                                    while (!child.HasExited) {
                                        if (Signaled(maintenance) && !requestedQuit) { quit.Set(); requestedQuit = true; }
                                        if (window.Ended && !requestedQuit) { quit.Set(); requestedQuit = true; }
                                        if (!becameReady && Signaled(ready)) {
                                            Native.Verify(child, created, exe);
                                            if (Storage.FileHash(exe) != hash) return 1;
                                            storage.Publish(new Manifest { runId = run, monitorPid = self.Id, monitorCreated = monitorCreated, monitorPath = monitorPath, guiPid = child.Id, guiCreated = created, guiPath = exe });
                                            becameReady = true; storage.Log("ready");
                                        }
                                        if (!becameReady && clock.ElapsedMilliseconds >= deadline) { storage.Log("ready timeout"); return 1; }
                                        child.WaitForExit(100);
                                    }
                                    // The GUI may signal readiness and crash before the
                                    // polling thread observes the event while it is alive.
                                    if (!becameReady && Signaled(ready)) becameReady = true;
                                    int code = child.ExitCode;
                                    long now = clock.ElapsedMilliseconds; restarts.RemoveAll(t => now - t > o.WindowMs);
                                    bool stopped = Signaled(stop), maintaining = Signaled(maintenance), ending = window.Pending || window.Ended;
                                    bool restart = Policy.Restart(becameReady, stopped, ending, maintaining, code, restarts.Count, o.MaxRestarts);
                                    int delay = restart ? o.BackoffsMs[Math.Min(restarts.Count, o.BackoffsMs.Length - 1)] : 0;
                                    storage.Log(String.Format("exit=0x{0:X8} ready={1} stop={2} maintenance={3} session={4} restarts={5} delayMs={6}", unchecked((uint)code), becameReady, stopped, maintaining, ending, restarts.Count, delay));
                                    if (!restart) return 0;
                                    restarts.Add(now);
                                    long until = clock.ElapsedMilliseconds + delay;
                                    while (clock.ElapsedMilliseconds < until) {
                                        if (Signaled(stop) || Signaled(maintenance) || window.Pending || window.Ended) return 0;
                                        Thread.Sleep(100);
                                    }
                                }
                                  } finally { storage.DeleteOwn(run); }
                                }
                            }
                        } finally { self.Dispose(); }
                    }
                } finally { mutex.ReleaseMutex(); }
            }
        }
        public static int StopForUpdate(string executable, string stateRoot) {
            try { return StopInner(Path.GetFullPath(executable), stateRoot); } catch { return 1; }
        }
        private static int StopInner(string exe, string root) {
            if (String.IsNullOrWhiteSpace(root) || !Path.IsPathRooted(root)) return 1;
            Storage storage = new Storage(root, exe); storage.ValidatePath(); bool owned;
            using (Mutex mutex = storage.Lock(out owned)) {
                if (owned) {
                    try {
                        return StaleManifestIsSafe(storage, exe) ? 0 : 1;
                    } finally { mutex.ReleaseMutex(); }
                }
                if (!File.Exists(storage.ManifestPath)) return 1;
                Manifest m = storage.Read();
                if (m == null || !ValidRunId(m.runId) || m.monitorPid <= 0 || m.guiPid <= 0 || !Native.SamePath(m.guiPath, exe)) return 1;
                using (Process monitor = Process.GetProcessById(m.monitorPid)) {
                    Native.Verify(monitor, m.monitorCreated, m.monitorPath);
                    if (!Native.SamePath(m.monitorPath, Process.GetCurrentProcess().MainModule.FileName)) return 1;
                    Process gui = null;
                    try {
                        try { gui = Process.GetProcessById(m.guiPid); } catch (ArgumentException) { }
                        if (gui != null) Native.Verify(gui, m.guiCreated, exe);
                        using (EventWaitHandle maintenance = Storage.Event(EventName(m.runId, "maintenance"), false)) maintenance.Set();
                        Stopwatch clock = Stopwatch.StartNew();
                        while (clock.ElapsedMilliseconds < 15000) {
                            bool guiDone = gui == null || gui.HasExited;
                            if (guiDone && monitor.HasExited) return 0;
                            Thread.Sleep(100);
                        }
                        return 1;
                    } finally { if (gui != null) gui.Dispose(); }
                }
            }
        }
        private static bool Exists(int pid) {
            try { using (Process p = Process.GetProcessById(pid)) return !p.HasExited; }
            catch (ArgumentException) { return false; }
        }
        private static bool StaleManifestIsSafe(Storage storage, string exe) {
            storage.ValidatePath();
            if (!File.Exists(storage.ManifestPath)) return true;
            Manifest stale = storage.Read();
            if (stale == null || !ValidRunId(stale.runId) || stale.monitorPid <= 0 || stale.guiPid <= 0 || !Native.SamePath(stale.guiPath, exe)) return false;
            // A live recorded PID is ambiguous even when it has been reused.
            return !Exists(stale.monitorPid) && !Exists(stale.guiPid);
        }
    }
}
