import { expect, test, type Page } from '@playwright/test';
import { resolve } from 'node:path';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';

async function expectConversationOrder(page: Page, expected: string[]) {
  await expect.poll(() => page.locator('.message-list > .message, .message-list > .approval-card, .message-list > .tool-result').evaluateAll(nodes => nodes.map(node => {
    if (node.classList.contains('approval-card')) return 'approval';
    if (node.classList.contains('tool-result')) return 'tool';
    return node.classList.contains('user') ? 'user' : 'assistant';
  }))).toEqual(expected);
}

test('workspace groups keep identical folder names distinct and support collapse, search and archives', async ({ page }) => {
  await page.goto('/');
  const headers = { 'X-Pi-Request': '1' };
  const config = await (await page.request.get('/api/bootstrap', { headers })).json();
  const workspaces = [resolve('../.pi-agent/group-one/project'), resolve('../.pi-agent/group-two/project')];
  const ids: string[] = [];
  try {
    for (const [index, workspace] of workspaces.entries()) {
      mkdirSync(workspace, { recursive: true });
      expect((await page.request.put('/api/settings', { headers, data: { workspace, tools: config.capabilities, tool_limits: config.tool_limits } })).ok()).toBe(true);
      const response = await page.request.post('/api/sessions', { headers });
      const item = await response.json(); ids.push(item.session_id);
      expect((await page.request.patch(`/api/sessions/${item.session_id}`, { headers, data: { title: `分组任务 ${index}` } })).ok()).toBe(true);
    }
    await page.reload();
    await page.getByRole('button', { name: '分组任务 0', exact: true }).click();
    const first = page.getByRole('region', { name: workspaces[0], exact: true });
    const second = page.getByRole('region', { name: workspaces[1], exact: true });
    await expect(first.getByRole('button', { name: '分组任务 0', exact: true })).toBeVisible();
    await expect(first.locator('.workspace-group-heading')).toHaveAttribute('title', workspaces[0]);
    await second.locator('.workspace-group-heading').click();
    await expect(second.locator('.workspace-group-heading')).toHaveAttribute('aria-expanded', 'false');
    await page.reload();
    await expect(second.locator('.workspace-group-heading')).toHaveAttribute('aria-expanded', 'false');
    await page.getByRole('textbox', { name: '搜索会话' }).fill('group-two');
    await expect(page.locator('.workspace-group')).toHaveCount(1);
    await expect(second.getByRole('button', { name: '分组任务 1', exact: true })).toBeVisible();
    await page.getByRole('textbox', { name: '搜索会话' }).fill('');
    expect((await page.request.patch(`/api/sessions/${ids[1]}`, { headers, data: { archived: true } })).ok()).toBe(true);
    await page.reload();
    await expect(second).toHaveCount(0);
    await page.getByRole('button', { name: '已归档会话', exact: true }).click();
    await page.getByRole('textbox', { name: '搜索会话' }).fill('分组任务 1');
    await expect(second.getByRole('button', { name: '分组任务 1', exact: true })).toBeVisible();
    await page.screenshot({ path: resolve('../.pi-agent/qa/workspace-groups.png'), fullPage: true });
    const item = await (await page.request.get(`/api/sessions/${ids[0]}`)).json();
    expect(item.session.workspace).toBe(workspaces[0]);
  } finally {
    await page.request.put('/api/settings', { headers, data: { workspace: config.workspace, tools: config.capabilities, tool_limits: config.tool_limits } });
  }
});

test('all tools are selected by default and deselection survives reload and blocks next turn', async ({ page }) => {
  await page.goto('/');
  const tools = ['read', 'list', 'search', 'write', 'edit', 'command'];
  for (const name of tools) {
    await expect(page.getByRole('checkbox', { name: `启用 ${name}`, exact: true })).toBeChecked();
  }
  await expect(page.locator('.tool-chips')).not.toContainText('审批');
  await expect(page.locator('.tool-chips')).not.toContainText('propose_command');
  await page.screenshot({ path: resolve('../.pi-agent/qa/tool-selection.png'), fullPage: true });
  for (const name of tools) {
    await page.getByRole('checkbox', { name: `启用 ${name}`, exact: true }).uncheck();
  }
  await expect(page.getByRole('checkbox', { name: '启用 command', exact: true })).toBeEnabled();
  await page.reload();
  for (const name of tools) {
    await expect(page.getByRole('checkbox', { name: `启用 ${name}`, exact: true })).not.toBeChecked();
  }
  const path = `disabled-${Date.now()}.txt`;
  await page.getByRole('textbox', { name: '输入消息' }).fill(`写入 ${JSON.stringify({ path, content: 'must not write' })}`);
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  expect(existsSync(resolve('../.pi-agent/web-e2e-workspace', path))).toBe(false);
  await expect(page.getByRole('button', { name: '批准并继续' })).toHaveCount(0);
  for (const name of tools) {
    await page.getByRole('checkbox', { name: `启用 ${name}`, exact: true }).check();
  }
  await expect(page.getByRole('checkbox', { name: '启用 command', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '工作区与工具' }).click();
  const dialog = page.getByRole('dialog', { name: '工作区与工具设置' });
  await expect(dialog.getByRole('checkbox')).toHaveCount(6);
  await expect(dialog.getByRole('spinbutton')).toHaveCount(6);
  for (const name of tools) await expect(dialog.getByRole('spinbutton', { name: `${name} 最大调用次数` })).toHaveValue('20');
  await expect(dialog.getByRole('checkbox', { name: /command/ })).toBeChecked();
  await page.getByRole('button', { name: '关闭对话框' }).click();
});

test('file approval survives reload, writes only after approve and rejection preserves content', async ({ page }) => {
  await page.goto('/');
  const path = `approval-${Date.now()}.txt`;
  const target = resolve('../.pi-agent/web-e2e-workspace', path);
  await page.getByRole('textbox', { name: '输入消息' }).fill(`写入 ${JSON.stringify({ path, content: 'approved browser content\n' })}`);
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByRole('button', { name: '批准并继续' })).toBeEnabled({ timeout: 15000 });
  expect(existsSync(target)).toBe(false);
  await expect(page.locator('.approval-diff')).toContainText('+approved browser content');
  await page.reload();
  await expect(page.getByRole('button', { name: '批准并继续' })).toBeEnabled();
  await page.screenshot({ path: resolve('../.pi-agent/qa/file-approval.png'), fullPage: true });
  await page.getByRole('button', { name: '批准并继续' }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  expect(readFileSync(target, 'utf8')).toBe('approved browser content\n');
  await page.getByRole('textbox', { name: '输入消息' }).fill(`修改 ${JSON.stringify({ path, old_text: 'approved', new_text: 'rejected' })}`);
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByRole('button', { name: '拒绝', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '拒绝', exact: true }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  expect(readFileSync(target, 'utf8')).toBe('approved browser content\n');
  await expectConversationOrder(page, ['user', 'approval', 'tool', 'assistant', 'user', 'approval', 'tool', 'assistant']);
});

test('completed commands remain in their own turns after later messages and reload', async ({ page }) => {
  await page.goto('/');
  const python = resolve('..', process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
  for (const text of ['first turn command', 'second turn command']) {
    await page.getByRole('textbox', { name: '输入消息' }).fill(`执行 ${JSON.stringify({ executable: python, argv: ['-c', `print(${JSON.stringify(text)})`], timeout_seconds: 5 })}`);
    await page.getByRole('button', { name: '发送消息' }).click();
    await expect(page.getByRole('button', { name: '批准并继续' })).toBeEnabled({ timeout: 15000 });
    await page.getByRole('button', { name: '批准并继续' }).click();
    await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  }
  await page.getByRole('textbox', { name: '输入消息' }).fill('你好');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  const assertTurnOrder = async () => {
    await expect(page.locator('.approval-card')).toHaveCount(2);
    await expectConversationOrder(page, ['user', 'approval', 'tool', 'assistant', 'user', 'approval', 'tool', 'assistant', 'user', 'assistant']);
    await expect(page.locator('.approval-card').nth(0)).toContainText('first turn command');
    await expect(page.locator('.approval-card').nth(1)).toContainText('second turn command');
  };
  await assertTurnOrder();
  await page.reload();
  await assertTurnOrder();
  await page.screenshot({ path: resolve('../.pi-agent/qa/approval-turn-order.png'), fullPage: true });
});

test('command review preserves argv boundaries and records real execution result', async ({ page }) => {
  await page.goto('/');
  const python = resolve('..', process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
  await page.getByRole('textbox', { name: '输入消息' }).fill(`执行 ${JSON.stringify({ executable: python, argv: ['-c', 'import sys; print(sys.argv[1])', 'browser argument with spaces'], timeout_seconds: 5 })}`);
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByRole('button', { name: '批准并继续' })).toBeEnabled({ timeout: 15000 });
  await expect(page.locator('.approval-card')).toContainText('browser argument with spaces');
  await page.screenshot({ path: resolve('../.pi-agent/qa/command-approval.png'), fullPage: true });
  await page.getByRole('button', { name: '批准并继续' }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  const card = page.locator('.approval-card');
  await card.locator('summary').first().click();
  await expect(card).toContainText('"returncode": 0');
  await expect(card).toContainText('browser argument with spaces');
  await page.getByRole('button', { name: 'command 返回结果', exact: true }).click();
  const details = page.getByRole('dialog', { name: '执行节点详情' });
  await expect(details.locator('.checkpoint-reference')).toContainText('Checkpoint:');
  await expect(details.locator('.step-messages').nth(1)).toContainText('browser argument with spaces');
  await expect(details).toContainText('快照覆盖本批全部工具调用');
  await expect(details.locator('.snapshot-grid details').nth(0)).toHaveAttribute('open', '');
  await expect(details.locator('.snapshot-grid details').nth(1)).toHaveAttribute('open', '');
  await expect(details.getByRole('button', { name: '复制 checkpoint ID', exact: true })).toBeVisible();
  await details.getByRole('button', { name: '复制 checkpoint ID', exact: true }).click();
  await expect(details.getByRole('button', { name: '复制 checkpoint ID', exact: true })).toContainText('已复制');
  await page.screenshot({ path: resolve('../.pi-agent/qa/approved-command-checkpoint.png'), fullPage: true });
  await page.getByRole('button', { name: '关闭节点详情' }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: '批准并继续' })).toHaveCount(0);
});

test('real browser: send, refresh, persist, rename, archive and restore', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('button', { name: '发送消息' })).toBeVisible();
  await expect(page.getByText('本地已连接')).toBeVisible();
  await page.screenshot({ path: resolve('../.pi-agent/qa/welcome.png'), fullPage: true });
  await page.getByRole('textbox', { name: '输入消息' }).fill('读取 README.md 并告诉我它的内容。');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.message.user')).toBeVisible();
  await page.reload();
  await expect(page.locator('.message.assistant')).toContainText('The web workbench reads real files.', { timeout: 15000 });
  await expect(page.locator('.activity-list')).toContainText('read 返回结果');
  await page.getByRole('button', { name: /read 返回结果/ }).click();
  await expect(page.getByRole('dialog', { name: '执行节点详情' })).toContainText('输入');
  await expect(page.getByRole('dialog', { name: '执行节点详情' })).toContainText('输出');
  await expect(page.locator('.snapshot-grid details').nth(0)).toHaveAttribute('open', '');
  await expect(page.locator('.snapshot-grid details').nth(1)).toHaveAttribute('open', '');
  await expect(page.getByRole('dialog', { name: '执行节点详情' })).toContainText('tool_rounds');
  await page.getByRole('button', { name: '关闭节点详情' }).click();
  await expect(page.locator('.message.user')).toHaveCount(1);
  await expect(page.locator('.run-summary')).toContainText('已完成');
  await page.screenshot({ path: resolve('../.pi-agent/qa/conversation.png'), fullPage: true });
  await page.getByRole('button', { name: '会话操作' }).click();
  await page.getByRole('button', { name: '重命名', exact: true }).click();
  await page.getByLabel('会话名称').fill('浏览器联调');
  await page.getByRole('button', { name: '保存名称' }).click();
  await expect(page.locator('.breadcrumb')).toContainText('浏览器联调');
  await page.getByRole('button', { name: '会话操作' }).click();
  await page.getByRole('button', { name: '归档会话', exact: true }).click();
  await page.getByRole('button', { name: '已归档会话', exact: true }).click();
  await page.getByRole('button', { name: '浏览器联调', exact: true }).click();
  await expect(page.getByRole('button', { name: '恢复会话', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '恢复会话', exact: true }).click();
  await page.getByRole('button', { name: '返回最近会话', exact: true }).click();
  await expect(page.getByRole('button', { name: '浏览器联调', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '工作区与工具' }).click();
  await expect(page.getByRole('dialog', { name: '工作区与工具设置' })).toBeVisible();
  await page.getByRole('spinbutton', { name: 'read 最大调用次数' }).fill('7');
  await page.getByRole('spinbutton', { name: 'write 最大调用次数' }).fill('2');
  await page.getByRole('spinbutton', { name: 'edit 最大调用次数' }).fill('0');
  await page.getByRole('spinbutton', { name: 'command 最大调用次数' }).fill('3');
  await page.getByRole('checkbox', { name: /列出目录/ }).uncheck();
  await page.getByRole('checkbox', { name: /搜索文本/ }).uncheck();
  await page.getByRole('button', { name: '保存设置' }).click();
  await expect(page.locator('.tool-chips')).toContainText('read');
  await expect(page.getByRole('checkbox', { name: '启用 search', exact: true })).not.toBeChecked();
  await page.reload();
  await page.getByRole('button', { name: '工作区与工具' }).click();
  await expect(page.getByRole('spinbutton', { name: 'read 最大调用次数' })).toHaveValue('7');
  await expect(page.getByRole('spinbutton', { name: 'write 最大调用次数' })).toHaveValue('2');
  await expect(page.getByRole('spinbutton', { name: 'edit 最大调用次数' })).toHaveValue('0');
  await expect(page.getByRole('spinbutton', { name: 'command 最大调用次数' })).toHaveValue('3');
  expect(errors).toEqual([]);
});

test('token counters update through SSE, persist on refresh and reset for a new session', async ({ page }) => {
  await page.goto('/');
  const counters = page.getByLabel('Token 用量', { exact: true });
  await expect(counters).toBeVisible();
  await page.getByRole('textbox', { name: '输入消息' }).fill('你好');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  const session = counters.getByRole('region', { name: '当前会话 Token', exact: true });
  await expect(session).toContainText('未提供');
  await expect(session).toContainText('1 次未提供完整用量');
  const allText = await counters.getByRole('region', { name: '累计 Token', exact: true }).textContent();
  await page.reload();
  await expect(session).toContainText('1 次未提供完整用量');
  await expect(counters.getByRole('region', { name: '累计 Token', exact: true })).toHaveText(allText!);
  await page.getByRole('button', { name: '新建会话' }).click();
  await expect(session).toContainText('0 次模型请求');
  await expect(counters.getByRole('region', { name: '累计 Token', exact: true })).toHaveText(allText!);
  await page.screenshot({ path: resolve('../.pi-agent/qa/token-usage.png'), fullPage: true });
});

test('mobile layout, sidebar and safe rendering', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByText('本地已连接')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.getByRole('button', { name: '打开会话栏' }).click();
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByRole('textbox', { name: '输入消息' }).fill('<img src=x onerror=alert(1)>');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  await expect(page.locator('.message.user img')).toHaveCount(0);
  await page.screenshot({ path: resolve('../.pi-agent/qa/mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '展开运行详情', exact: true }).click();
  await page.getByRole('button', { name: '模型响应完成', exact: true }).click();
  const details = page.getByRole('dialog', { name: '执行节点详情' });
  await expect(details.locator('.snapshot-grid details').nth(0)).toHaveAttribute('open', '');
  await expect(details.locator('.snapshot-grid details').nth(1)).toHaveAttribute('open', '');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: resolve('../.pi-agent/qa/mobile-node-details.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(details).toHaveCount(0);
});

test('stop action is explicit and does not duplicate the prompt', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: '输入消息' }).fill('读取 stream.txt');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByLabel('正在生成的回复')).toBeVisible();
  await page.getByRole('button', { name: '停止运行' }).click();
  await expect(page.locator('.run-summary')).toContainText('已停止', { timeout: 15000 });
  await page.reload();
  await expect(page.locator('.run-summary')).toContainText('已停止');
  await expect(page.locator('.message.user')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '模型响应已取消', exact: true })).toBeDisabled();
});

test('stream preview survives refresh and becomes one durable reply', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: '输入消息' }).fill('读取 stream.txt');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByLabel('正在生成的回复')).toBeVisible();
  await page.screenshot({ path: resolve('../.pi-agent/qa/stream-preview.png'), fullPage: true });
  await expect(page.locator('.run-summary')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  await expect(page.getByLabel('正在生成的回复')).toHaveCount(0);
  await expect(page.locator('.message.assistant')).toHaveCount(1);
  await expect(page.locator('.message.assistant')).toContainText('Streaming browser probe.');
});

test('explicit recovery and checkpoint branch preserve independent histories', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: '输入消息' }).fill('你好');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  const sourceId = await page.evaluate(() => localStorage.getItem('pi.session'));
  await page.getByRole('textbox', { name: '输入消息' }).fill('读取 README.md');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.activity-list')).toContainText('正在生成回复');
  await page.getByRole('button', { name: '停止运行' }).click();
  await expect(page.getByRole('button', { name: '继续运行', exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '继续运行', exact: true }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  await expect(page.locator('.message.user')).toHaveCount(2);
  await page.getByRole('button', { name: '会话操作' }).click();
  await page.getByRole('button', { name: '从检查点创建分支', exact: true }).click();
  const options = page.getByLabel('已完成的检查点').locator('option');
  await expect(options).toHaveCount(2);
  await page.screenshot({ path: resolve('../.pi-agent/qa/branch-selection.png'), fullPage: true });
  const firstCheckpoint = await options.last().getAttribute('value');
  await page.getByLabel('已完成的检查点').selectOption(firstCheckpoint!);
  await page.getByRole('button', { name: '创建分支', exact: true }).click();
  await expect(page.locator('.breadcrumb')).toContainText('分支');
  await expect(page.locator('.message.user')).toHaveCount(1);
  const branchId = await page.evaluate(() => localStorage.getItem('pi.session'));
  expect(branchId).not.toBe(sourceId);
  await page.getByRole('textbox', { name: '输入消息' }).fill('hello');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.run-summary')).toContainText('已完成', { timeout: 15000 });
  await page.reload();
  await expect(page.locator('.message.user')).toHaveCount(2);
  const original = await page.request.get(`/api/sessions/${sourceId}`);
  const view = await original.json();
  expect(view.history.messages.filter((message: { role: string }) => message.role === 'user').map((message: { text: string }) => message.text)).toEqual(['你好', '读取 README.md']);
});
