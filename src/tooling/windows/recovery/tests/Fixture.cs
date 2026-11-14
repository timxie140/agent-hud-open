using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;

// This executable is a disposable GUI stand-in. It never opens HUD data.
internal static class Fixture
{
    [DllImport("kernel32.dll")] private static extern uint SetErrorMode(uint mode);
    [DllImport("kernel32.dll")] private static extern void RaiseFailFastException(IntPtr record, IntPtr context, uint flags);
    [DllImport("kernel32.dll")] private static extern void ExitProcess(uint code);
    [DllImport("kernel32.dll")] private static extern int WerSetFlags(uint flags);
    [StructLayout(LayoutKind.Sequential)]
    private struct ExceptionRecord
    {
        public uint Code, Flags;
        public IntPtr Record, Address;
        public uint NumberParameters;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 15)] public UIntPtr[] Information;
    }
    private static void Crash(string root)
    {
        File.AppendAllText(Path.Combine(root, "crashes.log"), DateTime.UtcNow.Ticks + Environment.NewLine);
        var record = new ExceptionRecord { Code = 0xc0000005, Flags = 1, Information = new UIntPtr[15] };
        IntPtr memory = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(ExceptionRecord)));
        Marshal.StructureToPtr(record, memory, false);
        RaiseFailFastException(memory, IntPtr.Zero, 0);
    }

    private static void Signal(IDictionary<string, object> context, string key)
    {
        using (EventWaitHandle handle = EventWaitHandle.OpenExisting((string)context[key]))
            handle.Set();
    }

    public static int Main(string[] args)
    {
        File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "fixture-arguments.log"), String.Join(" | ", args) + Environment.NewLine);
        SetErrorMode(0x0001 | 0x0002 | 0x8000);
        try { WerSetFlags(0x20); } catch (DllNotFoundException) { } catch (EntryPointNotFoundException) { }
        if (args.Length != 3 || args[0] != "--recovery-child") return 2;
        string root = Path.GetFullPath(args[1]);
        string mode = args[2];
        Directory.CreateDirectory(root);
        string starts = Path.Combine(root, "starts.log");
        File.AppendAllText(starts, DateTime.UtcNow.Ticks + " " + System.Diagnostics.Process.GetCurrentProcess().Id + Environment.NewLine);
        int count = File.ReadAllLines(starts).Length;
        var context = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
            Environment.GetEnvironmentVariable("AGENTHUD_RECOVERY_CONTEXT"));
        File.AppendAllText(Path.Combine(root, "runids.log"), (string)context["runId"] + Environment.NewLine);
        if (mode == "unready") return 37;
        Signal(context, "readyEvent");
        File.AppendAllText(Path.Combine(root, "ready.log"), count + Environment.NewLine);
        if (mode == "instant-crash-once" && count == 1) { Crash(root); return 99; }
        Thread.Sleep(350);
        if (mode == "stale-event" && count == 1) { Thread.Sleep(500); Crash(root); return 99; }
        if (mode == "clean") return 0;
        if (mode == "unknown") return 37;
        if (mode == "stop-nonzero") { Signal(context, "stopEvent"); return 37; }
        if (mode == "stop-crash") { Signal(context, "stopEvent"); Crash(root); return 99; }
        if (mode == "crash" || (mode == "crash-once" && count == 1))
        {
            Crash(root);
            return 99;
        }
        if (mode == "crash-once" || mode == "instant-crash-once") return 0;
        using (EventWaitHandle quit = EventWaitHandle.OpenExisting((string)context["quitEvent"]))
        {
            if (!quit.WaitOne(20000)) return 40;
            File.WriteAllText(Path.Combine(root, "quit-seen"), "yes");
            if (mode == "ignore-quit") { Thread.Sleep(19000); return 0; }
            Signal(context, "stopEvent");
            return 0;
        }
    }
}
