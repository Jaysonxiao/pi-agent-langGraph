import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Spawn Python directly: on Windows a shell wrapper can outlive Playwright's cleanup.
export default async function setup() {
  const url = 'http://127.0.0.1:8776';
  try {
    await fetch(url, { signal: AbortSignal.timeout(500) });
    throw new Error('Port 8776 is already in use. Stop the old test service first.');
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Port')) throw error;
  }
  const root = resolve('..');
  const workspace = resolve(root, '.pi-agent/web-e2e-workspace');
  mkdirSync(workspace, { recursive: true });
  writeFileSync(resolve(workspace, 'README.md'), '# Browser test project\n\nThe web workbench reads real files.\n');
  const python = resolve(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
  const child = spawn(python, ['-m', 'pi_agent.web.app', '--provider', 'fake', '--workspace', workspace,
    '--database', resolve(root, `.pi-agent/e2e-${Date.now()}.sqlite`), '--port', '8776'], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  child.stdout.on('data', data => { output = (output + data).slice(-4000); });
  child.stderr.on('data', data => { output = (output + data).slice(-4000); });
  child.on('error', error => { output += error.message; });
  const stop = async () => {
    if (child.exitCode !== null) return;
    await new Promise<void>(resolveExit => {
      const timer = setTimeout(() => child.kill('SIGKILL'), 7000);
      child.once('exit', () => { clearTimeout(timer); resolveExit(); });
      child.kill('SIGTERM');
    });
  };
  for (let attempt = 0; attempt < 100; attempt++) {
    if (child.exitCode !== null) throw new Error(`Test server exited: ${output}`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(500) });
      if (response.ok) return stop;
    } catch { /* Wait for startup. */ }
    await new Promise(resolveWait => setTimeout(resolveWait, 100));
  }
  await stop();
  throw new Error(`Test server was not ready: ${output}`);
}
