// Windows-only helper packaging. It never starts or attaches to a HUD instance.
import {
  readdirSync,
  mkdirSync,
  copyFileSync,
  mkdtempSync,
  existsSync,
  rmSync,
} from "node:fs";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
} from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

if (process.platform !== "win32") throw new Error("Build recovery on Windows.");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const index = process.argv.indexOf("--out");
if (index < 0 || !process.argv[index + 1])
  throw new Error("Expected --out <helper.exe>.");
const out = resolve(process.argv[index + 1]);
if (!out.toLowerCase().endsWith(".exe"))
  throw new Error("Expected an .exe output.");
mkdirSync(dirname(out), { recursive: true });
const temporaryRoot = resolve(tmpdir());
const staging = mkdtempSync(join(temporaryRoot, "agenthud-recovery-build-"));
try {
  const executable = join(staging, "agent-hud-recovery.exe");
  const source = join(root, "src/crates/host/src/recovery/windows");
  const compiler = join(
    process.env.WINDIR || "C:\\Windows",
    "Microsoft.NET/Framework64/v4.0.30319/csc.exe",
  );
  const args = [
    "/nologo",
    "/warnaserror",
    "/optimize+",
    "/debug:pdbonly",
    "/target:winexe",
    "/platform:anycpu",
    "/reference:System.Web.Extensions.dll",
    "/reference:System.Windows.Forms.dll",
    `/out:${executable}`,
    ...readdirSync(source)
      .filter((name) => name.endsWith(".cs"))
      .sort()
      .map((name) => join(source, name)),
  ];
  const build = spawnSync(compiler, args, {
    cwd: root,
    stdio: "inherit",
    windowsHide: true,
  });
  if (build.status !== 0)
    throw new Error(
      `Recovery compilation failed: ${build.error || build.status}`,
    );
  const smoke = spawnSync(executable, ["--protocol"], {
    encoding: "utf8",
    timeout: 5000,
    windowsHide: true,
  });
  if (smoke.status !== 0 || smoke.stdout?.trim() !== "AgentHUDRecovery/1")
    throw new Error(
      "Recovery protocol-only smoke failed; no app was launched.",
    );
  copyFileSync(executable, out);
  const symbols = join(staging, "agent-hud-recovery.pdb");
  if (existsSync(symbols))
    copyFileSync(symbols, out.replace(/\.exe$/i, ".pdb"));
  console.log("Windows recovery helper compiled and protocol smoke passed.");
} finally {
  const child = relative(temporaryRoot, resolve(staging));
  if (
    !child ||
    child.startsWith("..") ||
    isAbsolute(child) ||
    !basename(staging).startsWith("agenthud-recovery-build-")
  )
    throw new Error("Refusing to remove an unexpected build directory.");
  rmSync(staging, { recursive: true, force: true });
}
