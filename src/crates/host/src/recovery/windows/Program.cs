using System;
using System.IO;
using System.Linq;

namespace AgentHudRecovery {
    public static class Program {
        public static int Main(string[] args) {
            try {
                string dir = AppDomain.CurrentDomain.BaseDirectory;
                string gui = Path.GetFullPath(Path.Combine(dir, "Agent HUD.exe"));
                string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AgentHUDPrivate", "recovery");
                if (args.Length == 1 && args[0] == "--protocol") { Console.WriteLine("AgentHUDRecovery/1"); return 0; }
                if (args.Length == 1 && args[0] == "--stop-for-update") return Guardian.StopForUpdate(gui, root);
                if (args.Length < 3 || args[0] != "--run" || args[2] != "--" || !Native.SamePath(args[1], gui)) return 2;
                string[] original = args.Skip(3).ToArray();
                if (original.Any(a => a == "--recovery-child")) return 2;
                return Guardian.Run(new Options { Executable = gui, Arguments = original, StateRoot = root });
            } catch { return 1; }
        }
    }
}
