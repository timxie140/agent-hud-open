using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using AgentHudRecovery;

internal static class Tests
{
    [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);
    private static string fixture;
    private static string self;
    private static int failures;

    private static string Q(string s) { return "\"" + s.Replace("\"", "\\\"") + "\""; }
    private static Process Start(params string[] args)
    {
        var info = new ProcessStartInfo(self, String.Join(" ", Array.ConvertAll(args, Q)));
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        return Process.Start(info);
    }
    private static bool WaitFor(string path, int ms)
    {
        var watch = Stopwatch.StartNew();
        while (watch.ElapsedMilliseconds < ms) { if (File.Exists(path)) return true; Thread.Sleep(50); }
        return false;
    }
    private static int ExitWithin(Process process, int timeout)
    {
        if (process.WaitForExit(timeout)) return process.ExitCode;
        process.Kill(); process.WaitForExit(); return -999;
    }
    private static int Starts(string dir)
    {
        string path = Path.Combine(dir, "starts.log");
        return File.Exists(path) ? File.ReadAllLines(path).Length : 0;
    }
    private static void Result(string name, bool ok, string details)
    {
        Console.WriteLine((ok ? "PASS " : "FAIL ") + name + " " + details);
        if (!ok) failures++;
    }
    private static void Scenario(string root, string mode, int expected)
    {
        string dir = Path.Combine(root, mode);
        Directory.CreateDirectory(dir);
        var timer = Stopwatch.StartNew();
        using (Process p = Start("guardian", dir, mode))
        {
            bool done = p.WaitForExit(45000);
            if (!done) { p.Kill(); p.WaitForExit(); }
            int count = Starts(dir);
            bool backoffs = true;
            if (mode == "crash" && count == 4) {
                string[] lines = File.ReadAllLines(Path.Combine(dir, "starts.log"));
                string[] crashes = File.ReadAllLines(Path.Combine(dir, "crashes.log"));
                backoffs = crashes.Length == 4;
                for (int i = 1; i < lines.Length; i++) {
                    long before = Int64.Parse(crashes[i - 1]);
                    long after = Int64.Parse(lines[i].Split(' ')[0]);
                    backoffs &= TimeSpan.FromTicks(after - before).TotalMilliseconds >= new[] { 100, 200, 300 }[i - 1];
                }
            }
            Result(mode, done && count == expected && backoffs, "starts=" + count + " expected=" + expected + " backoffs=" + backoffs + " guardianExit=" + p.ExitCode + " elapsedMs=" + timer.ElapsedMilliseconds);
        }
    }
    private static void Maintenance(string root, bool ignore)
    {
        string mode = ignore ? "ignore-quit" : "wait-quit";
        string dir = Path.Combine(root, mode);
        Directory.CreateDirectory(dir);
        using (Process guardian = Start("guardian", dir, mode))
        {
            bool ready = WaitFor(Path.Combine(dir, "ready.log"), 10000);
            var storage = new Storage(Path.Combine(dir, "state"), fixture);
            ready = ready && WaitFor(storage.ManifestPath, 10000);
            bool updateDone = false;
            int updateExit = -999;
            bool survived = false;
            if (ready)
            {
                Manifest manifest = storage.Read();
                using (Process gui = Process.GetProcessById(manifest.guiPid)) {
                Native.Verify(gui, manifest.guiCreated, fixture);
                using (Process update = Start("update", dir))
                {
                    updateDone = update.WaitForExit(25000);
                    if (!updateDone) { update.Kill(); update.WaitForExit(); }
                    updateExit = update.ExitCode;
                }
                survived = !gui.HasExited;
                }
            }
            bool quit = File.Exists(Path.Combine(dir, "quit-seen"));
            bool guardianDone = guardian.WaitForExit(25000);
            if (!guardianDone) { guardian.Kill(); guardian.WaitForExit(); }
            bool ok = ready && updateDone && quit && guardianDone && Starts(dir) == 1;
            if (ignore) ok &= updateExit != 0 && survived; else ok &= updateExit == 0 && !survived;
            Result(mode, ok, "ready=" + ready + " quit=" + quit + " updateExit=" + updateExit + " aliveAfterUpdate=" + survived + " guardianDone=" + guardianDone + " starts=" + Starts(dir));
        }
    }
    private static void IdentityAndSingleton(string root)
    {
        string dir = Path.Combine(root, "identity"); Directory.CreateDirectory(dir);
        var storage = new Storage(Path.Combine(dir, "state"), fixture);
        using (Process guardian = Start("guardian", dir, "wait-quit")) {
            bool ready = WaitFor(storage.ManifestPath, 10000);
            if (!ready) { Result("identity-singleton", false, "manifest absent"); guardian.WaitForExit(25000); return; }
            string original = File.ReadAllText(storage.ManifestPath);
            Manifest manifest = storage.Read();
            using (Process second = Start("guardian", dir, "wait-quit")) {
                bool secondDone = second.WaitForExit(5000);
                if (!secondDone) { second.Kill(); second.WaitForExit(); }
                bool singleton = secondDone && second.ExitCode != 0 && Starts(dir) == 1;
                manifest.runId = Guid.NewGuid().ToString("N"); storage.Publish(manifest);
                int badRun; using (Process update = Start("update", dir)) { badRun = ExitWithin(update, 5000); }
                manifest = new System.Web.Script.Serialization.JavaScriptSerializer().Deserialize<Manifest>(original);
                manifest.guiCreated = "1"; storage.Publish(manifest);
                int badCreation; using (Process update = Start("update", dir)) { badCreation = ExitWithin(update, 5000); }
                manifest = new System.Web.Script.Serialization.JavaScriptSerializer().Deserialize<Manifest>(original);
                manifest.guiPid = manifest.monitorPid; storage.Publish(manifest);
                int badPid; using (Process update = Start("update", dir)) { badPid = ExitWithin(update, 5000); }
                File.WriteAllText(storage.ManifestPath, original);
                int good; using (Process update = Start("update", dir)) { good = ExitWithin(update, 20000); }
                bool done = guardian.WaitForExit(20000);
                Result("identity-singleton", singleton && badRun > 0 && badCreation > 0 && badPid > 0 && good == 0 && done && Starts(dir) == 1,
                    "singleton=" + singleton + " staleRunExit=" + badRun + " wrongCreationExit=" + badCreation + " wrongPidExit=" + badPid + " validExit=" + good + " done=" + done);
            }
        }
    }
    private static void UnknownKill(string root)
    {
        string dir = Path.Combine(root, "killed"); Directory.CreateDirectory(dir);
        var storage = new Storage(Path.Combine(dir, "state"), fixture);
        using (Process guardian = Start("guardian", dir, "wait-quit")) {
            bool ready = WaitFor(storage.ManifestPath, 10000);
            if (ready) {
                Manifest m = storage.Read();
                using (Process gui = Process.GetProcessById(m.guiPid)) {
                    Native.Verify(gui, m.guiCreated, fixture);
                    gui.Kill(); gui.WaitForExit(5000);
                }
            }
            bool done = guardian.WaitForExit(25000);
            if (!done) { guardian.Kill(); guardian.WaitForExit(); }
            Result("unknown-kill", ready && done && Starts(dir) == 1, "ready=" + ready + " guardianDone=" + done + " starts=" + Starts(dir));
        }
    }
    private static void RunIdsAndStaleEvent(string root)
    {
        string dir = Path.Combine(root, "stale-event"); Directory.CreateDirectory(dir);
        var storage = new Storage(Path.Combine(dir, "state"), fixture);
        using (Process guardian = Start("guardian", dir, "stale-event")) {
            bool first = WaitFor(storage.ManifestPath, 10000);
            if (!first) { Result("runids-stale-event", false, "first manifest absent"); guardian.WaitForExit(25000); return; }
            string oldId = storage.Read().runId;
            using (EventWaitHandle oldStop = EventWaitHandle.OpenExisting("Local\\AgentHUDRecovery-" + oldId + "-stop")) {
                var timer = Stopwatch.StartNew(); string secondId = null;
                while (timer.ElapsedMilliseconds < 10000) {
                    try { if (File.Exists(storage.ManifestPath)) { string id = storage.Read().runId; if (id != oldId) { secondId = id; break; } } }
                    catch (IOException) { }
                    Thread.Sleep(50);
                }
                oldStop.Set(); Thread.Sleep(500);
                bool alive = !guardian.HasExited;
                int update; using (Process p = Start("update", dir)) { update = ExitWithin(p, 20000); }
                bool done = guardian.WaitForExit(20000);
                string[] ids = File.ReadAllLines(Path.Combine(dir, "runids.log"));
                Result("runids-stale-event", secondId != null && ids.Length == 2 && ids[0] != ids[1] && ids[1] == secondId && alive && update == 0 && done,
                    "distinct=" + (secondId != null && ids.Length == 2 && ids[0] != ids[1]) + " aliveAfterOldStop=" + alive + " update=" + update + " done=" + done);
            }
        }
    }
    private static void StorageSafety(string root, string junction)
    {
        string dir = Path.Combine(root, "oversize"); Directory.CreateDirectory(dir);
        var storage = new Storage(Path.Combine(dir, "state"), fixture); storage.EnsureDirectory();
        File.WriteAllText(storage.ManifestPath, new string('x', 16385));
        int launch; using (Process p = Start("guardian", dir, "clean")) { launch = ExitWithin(p, 10000); }
        int update; using (Process p = Start("update", dir)) { update = ExitWithin(p, 10000); }
        Result("oversize-manifest", launch > 0 && update > 0 && Starts(dir) == 0, "guardianExit=" + launch + " updateExit=" + update + " starts=" + Starts(dir));
        if (junction == "-") Console.WriteLine("SKIP reparse-junction unavailable");
        else {
            string path = Path.Combine(junction, "state");
            int result = Guardian.Run(new Options { Executable = fixture, StateRoot = path, Arguments = new[] { dir, "clean" } });
            Result("reparse-junction", result != 0 && !Directory.Exists(path), "guardianExit=" + result + " stateCreated=" + Directory.Exists(path));
        }
        var crashStorage = new Storage(Path.Combine(root, "crash", "state"), fixture);
        string log = File.ReadAllText(Path.Combine(crashStorage.DirectoryPath, "recovery.log"));
        Result("crash-exit-log", log.Contains("exit=0xC0000005") && log.Contains("ready=True") && log.Contains("stop=False") && log.Contains("delayMs=100"), "crashCodeAndFlags=" + log.Contains("exit=0xC0000005"));
    }
    private static void ShutdownWindow()
    {
        using (var w = new WindowStatus())
        {
            SendMessage(w.Handle, 0x11, IntPtr.Zero, IntPtr.Zero);
            bool query = w.Pending && !w.Ended;
            SendMessage(w.Handle, 0x16, IntPtr.Zero, IntPtr.Zero);
            bool cancelled = !w.Pending && !w.Ended;
            SendMessage(w.Handle, 0x11, IntPtr.Zero, IntPtr.Zero);
            SendMessage(w.Handle, 0x16, new IntPtr(1), IntPtr.Zero);
            Result("shutdown-window", query && cancelled && w.Pending && w.Ended, "query=" + query + " cancelled=" + cancelled + " confirmed=" + w.Ended);
        }
    }
    public static int Main(string[] args)
    {
        self = Process.GetCurrentProcess().MainModule.FileName;
        fixture = Path.Combine(Path.GetDirectoryName(self), "RecoveryFixture.exe");
        if (args.Length >= 1 && args[0] == "guardian")
        {
            var options = new Options { Executable = fixture, Arguments = new[] { args[1], args[2] }, StateRoot = Path.Combine(args[1], "state"), MaxRestarts = 3, WindowMs = 600000, BackoffsMs = new[] { 100, 200, 300 }, ReadyTimeoutMs = 3000 };
            return Guardian.Run(options);
        }
        if (args.Length >= 1 && args[0] == "update") return Guardian.StopForUpdate(fixture, Path.Combine(args[1], "state"));
        if (args.Length != 2) { Console.Error.WriteLine("Provide an empty private test directory and a private junction or '-'."); return 2; }
        string root = Path.GetFullPath(args[0]);
        Directory.CreateDirectory(root);
        if (Directory.GetFileSystemEntries(root).Length != 0) { Console.Error.WriteLine("Test directory must be empty."); return 2; }
        Scenario(root, "clean", 1);
        Scenario(root, "unknown", 1);
        Scenario(root, "unready", 1);
        Scenario(root, "stop-nonzero", 1);
        Scenario(root, "stop-crash", 1);
        Scenario(root, "crash-once", 2);
        Scenario(root, "instant-crash-once", 2);
        Scenario(root, "crash", 4);
        ShutdownWindow();
        Maintenance(root, false);
        Maintenance(root, true);
        UnknownKill(root);
        IdentityAndSingleton(root);
        RunIdsAndStaleEvent(root);
        StorageSafety(root, args[1]);
        Console.WriteLine("FAILURES=" + failures);
        return failures == 0 ? 0 : 1;
    }
}
