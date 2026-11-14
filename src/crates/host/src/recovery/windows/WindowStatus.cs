using System;
using System.Threading;
using System.Windows.Forms;

namespace AgentHudRecovery {
    public sealed class WindowStatus : IDisposable {
        private readonly Thread thread;
        private readonly ManualResetEvent started = new ManualResetEvent(false);
        private Form window;
        private volatile bool pending, ended;
        private Exception error;
        public bool Pending { get { return pending; } }
        public bool Ended { get { return ended; } }
        public IntPtr Handle { get { return window.Handle; } }
        public WindowStatus() {
            thread = new Thread(delegate() {
                try {
                    window = new HiddenWindow(this);
                    IntPtr ignored = window.Handle;
                    started.Set();
                    Application.Run(window);
                } catch (Exception e) { error = e; started.Set(); }
            });
            thread.IsBackground = true; thread.SetApartmentState(ApartmentState.STA); thread.Start();
            if (!started.WaitOne(10000) || error != null || window == null) throw new InvalidOperationException("shutdown listener unavailable", error);
        }
        public void Dispose() {
            if (window != null && !window.IsDisposed) {
                try { window.BeginInvoke((MethodInvoker)delegate { window.Close(); }); } catch (InvalidOperationException) { }
            }
            thread.Join(5000); started.Dispose();
        }
        private sealed class HiddenWindow : Form {
            private readonly WindowStatus owner;
            internal HiddenWindow(WindowStatus owner) { this.owner = owner; ShowInTaskbar = false; FormBorderStyle = FormBorderStyle.None; }
            protected override void SetVisibleCore(bool value) { base.SetVisibleCore(false); }
            protected override void WndProc(ref Message m) {
                if (m.Msg == 0x11) { owner.pending = true; m.Result = new IntPtr(1); return; }
                if (m.Msg == 0x16) { owner.ended = m.WParam != IntPtr.Zero; owner.pending = owner.ended; m.Result = IntPtr.Zero; return; }
                base.WndProc(ref m);
            }
        }
    }
}
