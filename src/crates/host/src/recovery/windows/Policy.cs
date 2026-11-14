using System;

namespace AgentHudRecovery {
    public sealed class Options {
        public string Executable;
        public string[] Arguments = new string[0];
        public string StateRoot;
        public int MaxRestarts = 3;
        public int WindowMs = 600000;
        public int[] BackoffsMs = new int[] { 3000, 10000, 30000 };
        public int ReadyTimeoutMs = 30000;
    }

    public static class Policy {
        public static bool IsCrash(int exitCode) {
            uint code = unchecked((uint)exitCode);
            return code == 0xc0000005u || code == 0xc0000409u || code == 0xc00000fdu || code == 0xe06d7363u;
        }
        public static bool Restart(bool ready, bool stopping, bool ending, bool maintenance, int exitCode, int recentRestarts, int maxRestarts) {
            return ready && !stopping && !ending && !maintenance && exitCode != 0 && IsCrash(exitCode) && recentRestarts < maxRestarts;
        }
    }
}
