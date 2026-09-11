import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as fs from 'fs';
import * as crypto from 'crypto';
import * as http from 'http';
import * as os from 'os';
import * as path from 'path';

let routerProcess: cp.ChildProcess | null = null;
let statusBar: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;
let approvalBrokerProcess: cp.ChildProcess | null = null;
let chatPanel: vscode.WebviewPanel | null = null;
let chatHistory: Array<{ role: 'user' | 'assistant'; content: string }> = [];
let chatInFlight = false;
const MAX_CHAT_MESSAGES = 20;
const APPROVAL_BROKER_PORT = 8767;
const shownApprovalIds = new Set<string>();

// ── ユーティリティ ───────────────────────────────────────────────────────────

function cfg<T>(key: string): T {
    return vscode.workspace.getConfiguration('glm').get<T>(key) as T;
}

function routerUrl(endpoint: string): string {
    return `http://127.0.0.1:${cfg<number>('port')}${endpoint}`;
}

function routerHeaders(): Record<string, string> {
    const tokenPath = path.join(os.homedir(), '.glm', 'auth_token');
    if (!fs.existsSync(tokenPath)) {
        fs.mkdirSync(path.dirname(tokenPath), { recursive: true });
        fs.writeFileSync(tokenPath, crypto.randomBytes(32).toString('base64url'), { encoding: 'utf8', mode: 0o600 });
    }
    const token = fs.readFileSync(tokenPath, 'utf8').trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
}

function getRouterPath(): string {
    const configured = cfg<string>('routerPath');
    if (configured) { return configured; }
    const fromEnvironment = process.env.GLM_ROUTER_PATH;
    if (fromEnvironment && fs.existsSync(fromEnvironment)) { return fromEnvironment; }
    const workspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const candidates = [
        workspace ? path.join(workspace, 'glm', 'router.py') : '',
        workspace ? path.join(workspace, 'router.py') : '',
        'D:\\Users\\新しいフォルダー\\AIIDE\\glm\\router.py',
        path.join(os.homedir(), 'OneDrive', 'co-vibe', 'glm', 'router.py'),
        path.join(os.homedir(), 'Desktop', 'co-vibe', 'glm', 'router.py'),
    ].filter(Boolean);
    return candidates.find(candidate => fs.existsSync(candidate)) ?? '';
}
function approvalBrokerUrl(endpoint: string): string {
    return `http://127.0.0.1:${APPROVAL_BROKER_PORT}${endpoint}`;
}

function httpGet(url: string, headers: Record<string, string> = {}): Promise<string> {
    return new Promise((resolve, reject) => {
        http.get(url, { timeout: 3000, headers }, res => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => resolve(data));
        }).on('error', reject).on('timeout', () => reject(new Error('timeout')));
    });
}
async function startApprovalBroker() {
    try {
        await httpGet(approvalBrokerUrl('/pending'), routerHeaders());
        return;
    } catch {
        const script = getRouterPath();
        if (!script) { return; }
        const broker = path.join(path.dirname(script), 'glm_approval_broker.py');
        if (!fs.existsSync(broker)) { return; }
        approvalBrokerProcess = cp.spawn('py.exe', [broker, '--port', String(APPROVAL_BROKER_PORT)], {
            stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
        });
        approvalBrokerProcess.stderr?.on('data', (data: Buffer) => outputChannel.append(data.toString()));
        approvalBrokerProcess.on('exit', () => { approvalBrokerProcess = null; });
    }
}

async function pollApprovals() {
    try {
        const raw = await httpGet(approvalBrokerUrl('/pending'), routerHeaders());
        const pending = JSON.parse(raw) as { requests?: Array<{ id: string; tool: string; params: unknown; diff?: string }> };
        for (const request of pending.requests ?? []) {
            if (shownApprovalIds.has(request.id)) { continue; }
            shownApprovalIds.add(request.id);
            const summary = request.diff
                ? `GLM: ${request.tool} を実行します。\n\n${request.diff.slice(0, 4000)}`
                : `GLM: ${request.tool} を実行します。${JSON.stringify(request.params).slice(0, 240)}`;
            const choice = await vscode.window.showWarningMessage(
                summary,
                { modal: true }, '一度許可', '常に許可', '一度拒否', '常に拒否'
            );
            const decisions: Record<string, boolean | string> = {
                '一度許可': true, '常に許可': 'allow_all', '一度拒否': false, '常に拒否': 'deny_all',
            };
            const decision = choice ? decisions[choice] : false;
            await httpPost(approvalBrokerUrl('/respond'), { id: request.id, decision });
            shownApprovalIds.delete(request.id);
        }
    } catch {
        return;
    }
}

function httpPost(url: string, payload: unknown): Promise<string> {
    return new Promise((resolve, reject) => {
        const body = JSON.stringify(payload);
        const request = http.request(url, {
            method: 'POST', timeout: 120000,
            headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body), ...routerHeaders() },
        }, response => {
            let data = '';
            response.on('data', chunk => data += chunk);
            response.on('end', () => response.statusCode && response.statusCode < 300 ? resolve(data) : reject(new Error(data)));
        });
        request.on('error', reject);
        request.on('timeout', () => request.destroy(new Error('timeout')));
        request.write(body);
        request.end();
    });
}

function isRouterRunning(): Promise<boolean> {
    return httpGet(routerUrl('/health'))
        .then(() => true)
        .catch(() => false);
}

// ── ステータスバー ────────────────────────────────────────────────────────────

function updateStatusBar(state: 'running' | 'stopped' | 'checking') {
    const icons: Record<typeof state, string> = {
        running:  '$(circle-filled) GLM',
        stopped:  '$(circle-outline) GLM',
        checking: '$(loading~spin) GLM',
    };
    const tips: Record<typeof state, string> = {
        running:  'GLM Router 起動中 — クリックでステータス確認',
        stopped:  'GLM Router 停止中 — クリックで起動',
        checking: 'GLM Router 確認中...',
    };
    statusBar.text    = icons[state];
    statusBar.tooltip = tips[state];
    statusBar.command = state === 'stopped' ? 'glm.startRouter' : 'glm.status';
    statusBar.backgroundColor = state === 'running'
        ? undefined
        : new vscode.ThemeColor('statusBarItem.warningBackground');
}

async function refreshStatusBar() {
    updateStatusBar('checking');
    const alive = await isRouterRunning();
    updateStatusBar(alive ? 'running' : 'stopped');
}

// ── コマンド: 起動 ────────────────────────────────────────────────────────────

async function startRouter() {
    if (await isRouterRunning()) {
        vscode.window.showInformationMessage('GLM Router はすでに起動中です。');
        return;
    }

    const py   = 'py.exe';
    const script = getRouterPath();
    const mode   = cfg<string>('mode');
    const port   = cfg<number>('port');

    if (!script) {
        vscode.window.showErrorMessage('router.py が見つかりません。GLM Router Path を設定してください。');
        return;
    }

    outputChannel.show(true);
    outputChannel.appendLine(`[GLM] 起動: ${script} --mode ${mode} --port ${port}`);

    routerProcess = cp.spawn(py, [script, '--mode', mode, '--port', String(port)], {
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
    });

    routerProcess.stdout?.on('data', (d: Buffer) => outputChannel.append(d.toString()));
    routerProcess.stderr?.on('data', (d: Buffer) => outputChannel.append(d.toString()));
    routerProcess.on('exit', (code) => {
        outputChannel.appendLine(`[GLM] プロセス終了 (code=${code})`);
        routerProcess = null;
        updateStatusBar('stopped');
    });

    // 起動完了を最大10秒待つ
    updateStatusBar('checking');
    for (let i = 0; i < 20; i++) {
        await new Promise(r => setTimeout(r, 500));
        if (await isRouterRunning()) {
            updateStatusBar('running');
            vscode.window.showInformationMessage(`GLM Router 起動完了 (port ${port}, mode ${mode})`);
            return;
        }
    }
    vscode.window.showErrorMessage('GLM Router の起動に失敗しました。出力パネルを確認してください。');
    updateStatusBar('stopped');
}

// ── コマンド: 停止 ────────────────────────────────────────────────────────────

async function stopRouter() {
    if (routerProcess) {
        routerProcess.kill();
        routerProcess = null;
    }
    updateStatusBar('stopped');
    vscode.window.showInformationMessage('GLM Router を停止しました。');
}

// ── コマンド: ステータス ──────────────────────────────────────────────────────

async function showStatus() {
    try {
        const raw  = await httpGet(routerUrl('/status'));
        const data = JSON.parse(raw) as Record<string, unknown>;
        const lines = [
            `VRAM: ${data['vram_used_gb']}GB / 空き ${data['vram_free_gb']}GB`,
            `GPU: ${data['gpu_temp']}℃  使用率: ${data['gpu_util']}%`,
            `スロットリング: ${data['throttling'] ? '⚠ あり' : 'なし'}`,
            `予算: $${data['budget_spent']} / 上限 $${(data['budget_ratio'] as number * 100).toFixed(0)}% 消費`,
        ];
        vscode.window.showInformationMessage(lines.join('  |  '), { modal: false });
    } catch {
        vscode.window.showWarningMessage('GLM Router に接続できません。起動していますか？');
    }
}

async function showDashboard() {
    const panel = vscode.window.createWebviewPanel(
        'glmDashboard', 'GLM Dashboard', vscode.ViewColumn.Beside, { enableScripts: false }
    );
    try {
        const raw = await httpGet(routerUrl('/status'));
        const data = JSON.parse(raw) as Record<string, unknown>;
        const budget = Number(data['budget_ratio'] ?? 0) * 100;
        panel.webview.html = `<!doctype html><html><body style="font-family:var(--vscode-font-family);padding:20px">
<h2>GLM Router</h2><table>
<tr><td>GPU temperature</td><td>${data['gpu_temp']} C</td></tr>
<tr><td>GPU utilization</td><td>${data['gpu_util']}%</td></tr>
<tr><td>VRAM used</td><td>${data['vram_used_gb']} GB</td></tr>
<tr><td>VRAM free</td><td>${data['vram_free_gb']} GB</td></tr>
<tr><td>Cloud budget</td><td>$${data['budget_spent']} (${budget.toFixed(1)}%)</td></tr>
<tr><td>Thermal throttling</td><td>${data['throttling'] ? 'Detected' : 'No'}</td></tr>
</table></body></html>`;
    } catch {
        panel.webview.html = '<p>GLM Router に接続できません。先に「GLM: ルーター起動」を実行してください。</p>';
    }
}

function chatHtml(initialMode: 'ask' | 'agent' | 'plan' = 'ask'): string {
    return `<!doctype html><html><body style="font-family:var(--vscode-font-family);margin:0;display:flex;flex-direction:column;height:100vh">
<main id="messages" style="flex:1;overflow:auto;padding:16px"></main>
<div style="display:flex;gap:8px;padding:8px 12px;border-top:1px solid var(--vscode-panel-border)">
<label>Mode <select id="mode"><option value="ask" ${initialMode === 'ask' ? 'selected' : ''}>Ask</option><option value="agent" ${initialMode === 'agent' ? 'selected' : ''}>Agent</option><option value="plan" ${initialMode === 'plan' ? 'selected' : ''}>Plan</option></select></label>
<label>Model <select id="model"><option value="auto">Auto</option><option value="GLM-0.1-nano-gate">GLM nano gate</option><option value="GLM-0.2-fast">GLM fast</option><option value="claude-haiku-4-5">Claude Haiku</option><option value="claude-sonnet-5">Claude Sonnet</option></select></label>
</div>
<form id="form" style="display:flex;gap:8px;padding:12px;border-top:1px solid var(--vscode-panel-border)">
<textarea id="input" aria-label="Message" rows="3" style="flex:1;resize:vertical"></textarea><button id="send" type="submit">Send</button><button id="clear" type="button">Clear</button>
</form><script>
const vscode=acquireVsCodeApi(),messages=document.getElementById('messages'),input=document.getElementById('input'),mode=document.getElementById('mode'),model=document.getElementById('model');
function add(role,text){const item=document.createElement('section');item.style.margin='0 0 14px';const label=document.createElement('strong');label.textContent=role;const content=document.createElement('pre');content.style.whiteSpace='pre-wrap';content.style.fontFamily='inherit';content.textContent=text;item.append(label,content);messages.append(item);messages.scrollTop=messages.scrollHeight;}
function clear(){messages.textContent='';}document.getElementById('form').addEventListener('submit',event=>{event.preventDefault();const text=input.value.trim();if(!text)return;add('You',text);input.value='';vscode.postMessage({type:'chat',text,mode:mode.value,model:model.value});});document.getElementById('clear').addEventListener('click',()=>vscode.postMessage({type:'clear'}));
window.addEventListener('message',event=>{const message=event.data;if(message.type==='answer')add('GLM',message.text);if(message.type==='error')add('GLM error',message.text);if(message.type==='clear')clear();});
</script></body></html>`;
}

async function openChat(initialMode: 'ask' | 'agent' | 'plan' = 'ask') {
    if (chatPanel) {
        chatPanel.reveal(vscode.ViewColumn.Beside);
        return;
    }
    const panel = vscode.window.createWebviewPanel('glmChat', 'GLM Chat', vscode.ViewColumn.Beside, { enableScripts: true });
    chatPanel = panel;
    panel.webview.html = chatHtml(initialMode);
    panel.onDidDispose(() => { chatPanel = null; });
    panel.webview.onDidReceiveMessage(async (message: { type: string; text?: string; mode?: string; model?: string }) => {
        if (message.type === 'clear') {
            chatHistory = [];
            panel.webview.postMessage({ type: 'clear' });
            return;
        }
        if (message.type !== 'chat' || !message.text?.trim() || chatInFlight) { return; }
        chatInFlight = true;
        const userMessage = message.text.trim();
        chatHistory.push({ role: 'user', content: userMessage });
        try {
            let text = '';
            if (message.mode === 'plan') {
                const raw = await httpPost(routerUrl('/api/orchestrator/plan'), { objective: userMessage });
                const result = JSON.parse(raw) as { plan?: { tasks?: Array<{ role: string; objective: string }> }; error?: string };
                text = result.plan?.tasks?.map((task, index) => `${index + 1}. ${task.role}: ${task.objective}`).join('\n') ?? result.error ?? '計画を作成できませんでした。';
            } else if (message.mode === 'agent') {
                const raw = await httpPost(routerUrl('/api/agent/run'), {
                    model: message.model || 'auto', messages: chatHistory, requested_by: 'code-oss-workbench', max_steps: 8, max_seconds: 180,
                });
                const result = JSON.parse(raw) as { message?: { content?: string }; reason?: string; error?: string };
                text = result.message?.content ?? result.reason ?? result.error ?? 'Agent応答を取得できませんでした。';
            } else {
                const raw = await httpPost(routerUrl('/v1/chat/completions'), {
                    model: message.model || 'auto', stream: false, messages: chatHistory,
                });
                const result = JSON.parse(raw) as { choices?: Array<{ message?: { content?: string } }>; error?: string };
                text = result.choices?.[0]?.message?.content ?? result.error ?? '応答を取得できませんでした。';
            }
            chatHistory.push({ role: 'assistant', content: text });
            chatHistory = chatHistory.slice(-MAX_CHAT_MESSAGES);
            panel.webview.postMessage({ type: 'answer', text });
        } catch (error) {
            panel.webview.postMessage({ type: 'error', text: `Router request failed: ${String(error)}` });
        } finally {
            chatInFlight = false;
        }
    });
}

function clearChat() {
    chatHistory = [];
    chatPanel?.webview.postMessage({ type: 'clear' });
}

async function showGitDiff() {
    const workspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspace) {
        vscode.window.showWarningMessage('差分を表示するワークスペースを開いてください。');
        return;
    }
    const result = await new Promise<string>((resolve, reject) => {
        cp.execFile('git', ['diff', '--no-ext-diff'], { cwd: workspace, maxBuffer: 2 * 1024 * 1024 }, (error, stdout, stderr) => {
            if (error && !stdout) { reject(new Error(stderr || error.message)); return; }
            resolve(stdout);
        });
    }).catch(error => {
        vscode.window.showErrorMessage(`Git差分を取得できません: ${String(error)}`);
        return null;
    });
    if (result === null) { return; }
    const content = result || '作業ツリーに未コミットの差分はありません。\n';
    const document = await vscode.workspace.openTextDocument({ content, language: 'diff' });
    await vscode.window.showTextDocument(document, { preview: true, preserveFocus: false });
}

function workspaceRelative(document: vscode.TextDocument): string {
    const workspace = vscode.workspace.getWorkspaceFolder(document.uri);
    if (!workspace) { return document.fileName; }
    return path.relative(workspace.uri.fsPath, document.uri.fsPath).split(path.sep).join('/');
}

async function languageRequest(endpoint: string, document: vscode.TextDocument, extra: Record<string, unknown> = {}) {
    const raw = await httpPost(routerUrl(endpoint), {
        path: workspaceRelative(document), content: document.getText(), ...extra,
    });
    return JSON.parse(raw) as Record<string, any>;
}

function registerLanguageProviders(context: vscode.ExtensionContext) {
    const selector: vscode.DocumentSelector = [{ scheme: 'file', language: 'python' }];
    const diagnostics = vscode.languages.createDiagnosticCollection('glm');
    context.subscriptions.push(diagnostics);

    const refreshDiagnostics = async (document: vscode.TextDocument) => {
        if (document.languageId !== 'python') { return; }
        try {
            const result = await languageRequest('/api/language/type-diagnostics', document);
            const items = (result.diagnostics ?? []).map((item: any) => {
                const start = new vscode.Position(Math.max(0, Number(item.line ?? 1) - 1), Math.max(0, Number(item.column ?? 1) - 1));
                const range = new vscode.Range(start, start.translate(0, 1));
                const severity = String(item.severity).toLowerCase() === 'warning'
                    ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error;
                return new vscode.Diagnostic(range, String(item.message ?? ''), severity);
            });
            diagnostics.set(document.uri, items);
        } catch { diagnostics.delete(document.uri); }
    };

    context.subscriptions.push(vscode.workspace.onDidOpenTextDocument(refreshDiagnostics));
    context.subscriptions.push(vscode.workspace.onDidSaveTextDocument(refreshDiagnostics));
    if (vscode.window.activeTextEditor) { void refreshDiagnostics(vscode.window.activeTextEditor.document); }

    context.subscriptions.push(vscode.languages.registerCompletionItemProvider(selector, {
        async provideCompletionItems(document, position) {
            const line = document.lineAt(position.line).text.slice(0, position.character);
            const prefix = line.match(/[A-Za-z_]\w*$/)?.[0] ?? '';
            const result = await languageRequest('/api/language/completions', document, { prefix });
            return (result.items ?? []).map((item: any) => new vscode.CompletionItem(item.label, vscode.CompletionItemKind.Variable));
        },
    }, '.'));

    context.subscriptions.push(vscode.languages.registerDefinitionProvider(selector, {
        async provideDefinition(document, position) {
            const name = document.getText(document.getWordRangeAtPosition(position) ?? new vscode.Range(position, position));
            const result = await languageRequest('/api/workspace/definitions', document, { name });
            return (result.definitions ?? []).map((item: any) => new vscode.Location(
                vscode.Uri.file(path.join(vscode.workspace.getWorkspaceFolder(document.uri)?.uri.fsPath ?? '', item.path)),
                new vscode.Position(Number(item.line ?? 1) - 1, Number(item.column ?? 1) - 1),
            ));
        },
    }));

    context.subscriptions.push(vscode.languages.registerReferenceProvider(selector, {
        async provideReferences(document, position) {
            const word = document.getText(document.getWordRangeAtPosition(position) ?? new vscode.Range(position, position));
            const result = await languageRequest('/api/language/references', document, { name: word });
            const root = vscode.workspace.getWorkspaceFolder(document.uri)?.uri.fsPath ?? '';
            return (result.references ?? []).map((item: any) => new vscode.Location(
                vscode.Uri.file(path.join(root, item.path)),
                new vscode.Position(Number(item.line ?? 1) - 1, Number(item.column ?? 1) - 1),
            ));
        },
    }));

    context.subscriptions.push(vscode.languages.registerRenameProvider(selector, {
        async provideRenameEdits(document, position, newName) {
            const word = document.getText(document.getWordRangeAtPosition(position) ?? new vscode.Range(position, position));
            const result = await languageRequest('/api/language/rename', document, { name: word, new_name: newName });
            const edit = new vscode.WorkspaceEdit();
            const root = vscode.workspace.getWorkspaceFolder(document.uri)?.uri.fsPath ?? '';
            for (const item of result.edits ?? []) {
                const uri = vscode.Uri.file(path.join(root, item.path));
                const start = new vscode.Position(Number(item.line ?? 1) - 1, Number(item.column ?? 1) - 1);
                edit.replace(uri, new vscode.Range(start, start.translate(0, word.length)), String(item.new_text ?? newName));
            }
            return edit;
        },
    }));

    context.subscriptions.push(vscode.languages.registerDocumentSymbolProvider(selector, {
        async provideDocumentSymbols(document) {
            const result = await languageRequest('/api/language/symbols', document);
            return (result.symbols ?? []).map((item: any) => {
                const start = new vscode.Position(Number(item.line ?? 1) - 1, Number(item.column ?? 1) - 1);
                const range = new vscode.Range(start, start.translate(0, String(item.name).length));
                return new vscode.DocumentSymbol(String(item.name), String(item.kind ?? ''), vscode.SymbolKind.Function, range, range);
            });
        },
    }));
}

// ── コマンド: セッション一覧 ──────────────────────────────────────────────────

async function showSessions() {
    try {
        const raw  = await httpGet(routerUrl('/sessions'));
        const list = JSON.parse(raw) as Array<Record<string, unknown>>;
        if (!list.length) {
            vscode.window.showInformationMessage('セッション履歴はありません。');
            return;
        }
        const items = list.slice(0, 30).map(s => ({
            label:       String(s['title'] ?? '(無題)'),
            description: `${s['model']} | ${s['turns']}ターン | ${String(s['last_active']).slice(0, 16)}`,
            detail:      `トークン: ${s['tokens']}`,
        }));
        await vscode.window.showQuickPick(items, {
            title: 'GLM セッション履歴',
            placeHolder: 'セッションを選択（現在は参照のみ）',
        });
    } catch {
        vscode.window.showWarningMessage('GLM Router に接続できません。');
    }
}

// ── コマンド: 診断 ────────────────────────────────────────────────────────────

async function runDoctor() {
    const py     = 'py.exe';
    const script = getRouterPath();
    outputChannel.show(true);
    outputChannel.appendLine('[GLM] システム診断を実行中...\n');
    const proc = cp.spawn(py, [script, '--doctor'], { windowsHide: true });
    proc.stdout?.on('data', (d: Buffer) => outputChannel.append(d.toString()));
    proc.stderr?.on('data', (d: Buffer) => outputChannel.append(d.toString()));
    proc.on('exit', () => outputChannel.appendLine('\n[GLM] 診断完了'));
}

// ── コマンド: モード切替 ──────────────────────────────────────────────────────

async function switchMode() {
    const pick = await vscode.window.showQuickPick(
        [
            { label: 'STRATEGY',   description: 'サイズ×複雑度×予算で自動最適化（推奨）' },
            { label: 'LOCAL_ONLY', description: '常にローカルOllama（API不要）' },
            { label: 'THRESHOLD',  description: 'トークン数16K超でクラウド切替' },
        ],
        { title: 'GLM: ルーティングモード選択' }
    );
    if (!pick) { return; }
    await vscode.workspace.getConfiguration('glm').update(
        'mode', pick.label, vscode.ConfigurationTarget.Global
    );
    vscode.window.showInformationMessage(
        `GLM モードを ${pick.label} に変更しました。再起動後に反映されます。`
    );
}

async function runEval() {
    try {
        const raw = await httpPost(routerUrl('/api/mlops/eval'), { model_id: 'GLM-0.2-fast', version: '1.0', min_pass_rate: 0.8 });
        const result = JSON.parse(raw) as { ok?: boolean; eval?: { pass_rate: number; passed: number; total_cases: number; promoted: boolean }; error?: string };
        if (!result.ok || !result.eval) {
            vscode.window.showErrorMessage(`Eval実行失敗: ${result.error || 'unknown error'}`);
            return;
        }
        const text = `Pass@1: ${(result.eval.pass_rate * 100).toFixed(0)}% (${result.eval.passed}/${result.eval.total_cases}) | 判定: ${result.eval.promoted ? '承認済モデルへ自動昇格' : '保留'}`;
        vscode.window.showInformationMessage(`GLM MLOps Eval: ${text}`);
    } catch (error) {
        vscode.window.showErrorMessage(`Eval接続エラー: ${String(error)}`);
    }
}

// ── アクティベーション ────────────────────────────────────────────────────────

export async function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('GLM Router');

    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.show();
    context.subscriptions.push(statusBar);

    const cmds: [string, () => unknown][] = [
        ['glm.startRouter', startRouter],
        ['glm.stopRouter',  stopRouter],
        ['glm.status',      showStatus],
        ['glm.sessions',    showSessions],
        ['glm.doctor',      runDoctor],
        ['glm.switchMode',  switchMode],
        ['glm.dashboard',   showDashboard],
        ['glm.chat',        () => openChat('ask')],
        ['glm.agentChat',   () => openChat('agent')],
        ['glm.planChat',    () => openChat('plan')],
        ['glm.clearChat',   clearChat],
        ['glm.showGitDiff', showGitDiff],
        ['glm.runEval',     runEval],
    ];
    for (const [id, fn] of cmds) {
        context.subscriptions.push(vscode.commands.registerCommand(id, fn));
    }
    registerLanguageProviders(context);

    await refreshStatusBar();
    await startApprovalBroker();

    // 30秒ごとにステータスバーを更新
    const timer = setInterval(() => refreshStatusBar(), 30_000);
    context.subscriptions.push({ dispose: () => clearInterval(timer) });
    const approvalTimer = setInterval(() => void pollApprovals(), 1_000);
    context.subscriptions.push({ dispose: () => clearInterval(approvalTimer) });

    if (cfg<boolean>('autoStart')) {
        startRouter();
    }
}

export function deactivate() {
    routerProcess?.kill();
    approvalBrokerProcess?.kill();
}
