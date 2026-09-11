// GLM Standalone IDE Frontend Core Logic (v1.1)

// Tauriデスクトップ環境では origin が tauri.localhost になるため、
// バックエンド(GLM Core) の固定ローカルアドレスへ向ける。
const IS_TAURI = '__TAURI_INTERNALS__' in window
  || location.protocol === 'tauri:'
  || location.hostname === 'tauri.localhost'
  || location.hostname.endsWith('.tauri.localhost');
const CORE_URL = IS_TAURI ? 'http://127.0.0.1:8765' : window.location.origin;
const ROUTER_URL = CORE_URL;
const BROKER_URL = CORE_URL;
const MODE_LABELS = {
  STRATEGY: '自動最適化',
  LOCAL_ONLY: 'ローカルのみ',
  THRESHOLD: 'しきい値',
};

let monacoEditor = null;
let monacoDiffEditor = null;
let currentOriginalModel = null;
let currentModifiedModel = null;

// Multi-Tab & File State
let openTabs = [];
let activeTabPath = '';
let currentActivePath = '';
let isDiffMode = false;
let chatHistory = [];
let isGenerating = false;
let authHeader = {};
let pendingRename = null;
let agentSessionId = 'ui-' + Date.now().toString(36);
let workspaceFiles = [];
let terminalCursor = 0;
let terminalTimer = null;
let backendDown = false;
let lastChatRequest = null;
let latestSessions = [];
let customizationFiles = [];

const UI_ICONS = {
  explorer: '<svg viewBox="0 0 16 16"><path d="M2.5 2.5h4l1.2 1.5h5.8v9.5h-11z"/></svg>',
  search: '<svg viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.2"/><path d="m10.2 10.2 3.3 3.3"/></svg>',
  source: '<svg viewBox="0 0 16 16"><circle cx="5" cy="4" r="2"/><circle cx="11" cy="12" r="2"/><path d="M5 6v1.8c0 1.8 1.2 2.7 3 2.7h1"/></svg>',
  debug: '<svg viewBox="0 0 16 16"><path d="M5 3.2v9.6l7-4.8z"/></svg>',
  remote: '<svg viewBox="0 0 16 16"><path d="M2.5 5h9m0 0-2-2m2 2-2 2M13.5 11h-9m0 0 2-2m-2 2 2 2"/></svg>',
  extensions: '<svg viewBox="0 0 16 16"><path d="M6 2.5h4v3.2h3.2v4H10v3.8H6V9.7H2.8v-4H6z"/></svg>',
  settings: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6 5 5M11 11l1.4 1.4M12.4 3.6 11 5M5 11l-1.4 1.4"/></svg>',
  plus: '<svg viewBox="0 0 16 16"><path d="M8 3v10M3 8h10"/></svg>',
  history: '<svg viewBox="0 0 16 16"><path d="M3.8 5.4A5 5 0 1 1 3 8"/><path d="M3.8 2.6v2.8H1M8 5.2V8l2 1.3"/></svg>',
  agent: '<svg viewBox="0 0 16 16"><rect x="3" y="4" width="10" height="8" rx="2"/><path d="M6 4V2.5h4V4M6.2 7.3h.1M9.7 7.3h.1M6.3 9.7h3.4"/></svg>',
  auto: '<svg viewBox="0 0 16 16"><path d="M8 1.8 9.6 6H14l-3.5 2.6 1.3 4.2L8 10.3l-3.8 2.5 1.3-4.2L2 6h4.4z"/></svg>',
  sliders: '<svg viewBox="0 0 16 16"><path d="M3 4h10M3 8h10M3 12h10"/><circle cx="6" cy="4" r="1.3"/><circle cx="10" cy="8" r="1.3"/><circle cx="7" cy="12" r="1.3"/></svg>',
  mic: '<svg viewBox="0 0 16 16"><rect x="6" y="2" width="4" height="7" rx="2"/><path d="M3.8 7.5a4.2 4.2 0 0 0 8.4 0M8 11.8V14M5.5 14h5"/></svg>',
  send: '<svg viewBox="0 0 16 16"><path d="M8 13V3M4.2 6.8 8 3l3.8 3.8"/></svg>',
  run: '<svg viewBox="0 0 16 16"><path d="M5 3.2v9.6l7-4.8z"/></svg>',
  stop: '<svg viewBox="0 0 16 16"><rect x="4" y="4" width="8" height="8" rx="1"/></svg>',
  save: '<svg viewBox="0 0 16 16"><path d="M3 2.5h8.5L13 4v9.5H3z"/><path d="M5 2.5v4h6M5 13.5V9h6v4.5"/></svg>',
  info: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="5.5"/><path d="M8 7.2v3.6M8 5.1h.1"/></svg>',
  trash: '<svg viewBox="0 0 16 16"><path d="M3 4.5h10M6.5 2.5h3M5 4.5l.5 9h5l.5-9"/></svg>',
  code: '<svg viewBox="0 0 16 16"><path d="m6 4-4 4 4 4M10 4l4 4-4 4"/></svg>',
  diff: '<svg viewBox="0 0 16 16"><path d="M4 3v10M12 3v10M2.5 5.5h3M10.5 5.5h3M2.5 10.5h3M10.5 10.5h3"/></svg>',
  goto: '<svg viewBox="0 0 16 16"><path d="M5 11 11 5M7 5h4v4M4 4h-1v9h9v-1"/></svg>',
  edit: '<svg viewBox="0 0 16 16"><path d="m3 11.5-.5 2 2-.5 7.2-7.2-1.5-1.5zM9.7 4.8l1.5 1.5"/></svg>',
  check: '<svg viewBox="0 0 16 16"><path d="M3.5 8.5 6.5 11.5 12.5 4.5"/></svg>',
  review: '<svg viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" rx="1"/><path d="M5 6h6M5 8.5h6M5 11h3"/></svg>',
  sparkle: '<svg viewBox="0 0 16 16"><path d="M8 1.8 9.2 6.3 13.7 8 9.2 9.7 8 14.2 6.8 9.7 2.3 8 6.8 6.3z"/></svg>',
  output: '<svg viewBox="0 0 16 16"><path d="M3 4h10v8H3zM5 6l2 2-2 2M8 10h3"/></svg>',
  warning: '<svg viewBox="0 0 16 16"><path d="M8 2.2 14 13H2z"/><path d="M8 6v3M8 11.5h.1"/></svg>',
  terminal: '<svg viewBox="0 0 16 16"><path d="M3 4h10v8H3zM5 6.5 7 8l-2 1.5M8.5 9.5H11"/></svg>',
  file: '<svg viewBox="0 0 16 16"><path d="M4 2.5h5l3 3v8H4z"/><path d="M9 2.5v3h3"/></svg>',
  markdown: '<svg viewBox="0 0 16 16"><path d="M2.5 4h11v8h-11z"/><path d="M4.2 10V6l1.8 2 1.8-2v4M9.2 6v4M9.2 10l-1.1-1.1M9.2 10l1.1-1.1"/></svg>',
  braces: '<svg viewBox="0 0 16 16"><path d="M6 3.5H5c-.8 0-1.2.4-1.2 1.2v1.8c0 .7-.4 1.1-1.1 1.1.7 0 1.1.4 1.1 1.1v1.8c0 .8.4 1.2 1.2 1.2h1M10 3.5h1c.8 0 1.2.4 1.2 1.2v1.8c0 .7.4 1.1 1.1 1.1-.7 0-1.1.4-1.1 1.1v1.8c0 .8-.4 1.2-1.2 1.2h-1"/></svg>',
  copy: '<svg viewBox="0 0 16 16"><rect x="5" y="5" width="8" height="8" rx="1"/><path d="M3 10V3h7"/></svg>',
  refresh: '<svg viewBox="0 0 16 16"><path d="M12.5 6A4.8 4.8 0 1 0 13 8.2"/><path d="M12.5 2.8V6h-3.2"/></svg>',
  thumbsUp: '<svg viewBox="0 0 16 16"><path d="M5.5 13h6.2c.7 0 1.2-.5 1.3-1.1l.7-4.2c.1-.8-.5-1.5-1.3-1.5H9.5l.4-2.1c.1-.7-.4-1.3-1.1-1.3h-.3L5.5 6.2zM2.5 6.5h3v6h-3z"/></svg>',
  thumbsDown: '<svg viewBox="0 0 16 16"><path d="M10.5 3H4.3C3.6 3 3.1 3.5 3 4.1l-.7 4.2c-.1.8.5 1.5 1.3 1.5h2.9l-.4 2.1c-.1.7.4 1.3 1.1 1.3h.3l3-3.4zM10.5 3.5h3v6h-3z"/></svg>',
  tool: '<svg viewBox="0 0 16 16"><path d="M9.5 2.8a3.5 3.5 0 0 0 3.7 3.7l-6.6 6.6a2 2 0 1 1-2.8-2.8z"/></svg>'
};

function applyUiIcon(target, name, label = '', showLabel = false) {
  const element = typeof target === 'string' ? document.querySelector(target) : target;
  if (!element || !UI_ICONS[name]) return;
  element.classList.add('ui-icon-host');
  element.innerHTML = UI_ICONS[name] + (showLabel ? `<span class="icon-label">${escapeHtml(label)}</span>` : '');
  if (label) {
    element.setAttribute('aria-label', label);
    if (!element.title) element.title = label;
  }
}

function setupUiIcons() {
  document.querySelectorAll('[data-ui-icon]').forEach(element => applyUiIcon(element, element.dataset.uiIcon, element.getAttribute('aria-label') || element.title || ''));
  const activity = { explorer: 'explorer', search: 'search', git: 'source', debug: 'debug', sftp: 'remote', extensions: 'extensions', settings: 'settings' };
  Object.entries(activity).forEach(([view, iconName]) => applyUiIcon(`.activity-item[data-view="${view}"] .activity-icon`, iconName));
  [
    ['#btn-palette', 'terminal', 'コマンドパレット'], ['#btn-run', 'run', '実行'], ['#btn-debug', 'debug', 'デバッグ開始'],
    ['#btn-debug-stop', 'stop', 'デバッグ停止'], ['#btn-debug-breakpoint', 'warning', 'ブレークポイント設定'],
    ['#btn-debug-continue', 'run', '続行'], ['#btn-debug-next', 'refresh', '次へ'], ['#btn-debug-inspect', 'search', 'スタックと変数'],
    ['#btn-save', 'save', '保存'], ['#btn-status', 'info', '診断'], ['#btn-dev-status', 'extensions', '開発環境'],
    ['#btn-diff', 'diff', 'Git差分'], ['#btn-clear', 'trash', '履歴消去'], ['#btn-kill', 'stop', 'キルスイッチ'],
    ['#btn-view-code', 'code', 'コード'], ['#btn-view-diff', 'diff', '差分表示'], ['#btn-go-definition', 'goto', '定義ジャンプ'],
    ['#btn-find-references', 'search', '参照検索'], ['#btn-rename-symbol', 'edit', 'リネーム案'], ['#btn-rename-apply', 'check', 'リネーム適用'],
    ['#btn-review-selection', 'review', '選択範囲レビュー'], ['#btn-commit-suggest', 'sparkle', 'コミットメッセージ提案'],
    ['.bottom-tab[data-tab="output"]', 'output', '出力', true], ['.bottom-tab[data-tab="problems"]', 'warning', '問題', true],
    ['.bottom-tab[data-tab="debug"]', 'debug', 'デバッグコンソール', true], ['.bottom-tab[data-tab="terminal"]', 'terminal', 'ターミナル', true],
    ['#btn-clear-output', 'trash', '出力を消去']
  ].forEach(([selector, iconName, label, showLabel]) => applyUiIcon(selector, iconName, label, Boolean(showLabel)));
  const problemsTab = document.querySelector('.bottom-tab[data-tab="problems"]');
  if (problemsTab && !problemsTab.querySelector('#problems-count')) {
    const badge = document.createElement('span');
    badge.id = 'problems-count';
    badge.className = 'badge problems-badge';
    badge.textContent = '0';
    problemsTab.appendChild(badge);
  }
  const panelIcons = [
    ['[data-view-pane="explorer"] > .panel-header:first-child span', 'explorer', 'ワークスペースファイル'],
    ['[data-view-pane="explorer"] .panel-header.margin-top span', 'history', 'セッション履歴'],
    ['[data-view-pane="search"] .panel-header span', 'search', '検索'],
    ['[data-view-pane="git"] .panel-header span', 'source', 'ソース管理'],
    ['[data-view-pane="debug"] .panel-header span', 'debug', '実行とデバッグ'],
    ['[data-view-pane="sftp"] .panel-header span', 'remote', 'SFTP リモート'],
    ['[data-view-pane="extensions"] .panel-header span', 'extensions', '拡張機能'],
    ['[data-view-pane="settings"] .panel-header span', 'settings', '設定']
  ];
  panelIcons.forEach(([selector, iconName, label]) => applyUiIcon(selector, iconName, label, true));
  applyUiIcon('#btn-refresh-files', 'refresh', 'ファイル一覧を更新');
  applyUiIcon('#btn-refresh-git', 'refresh', 'Git状態を更新');
  applyUiIcon('#btn-mlops-refresh', 'refresh', 'エージェント編成の状態を更新');
}

// Tauri環境ではCookieが発行されないため、ローカルトークンAPIからBearerを取得する
async function initAuth() {
  if (!IS_TAURI) return;
  try {
    const res = await fetch(`${CORE_URL}/api/auth/local-token`);
    const data = await res.json();
    if (data.ok && data.token) authHeader = { 'Authorization': 'Bearer ' + data.token };
  } catch (e) { /* バックエンド未起動時はポーリング側で通知 */ }
}

function showBackendDown() {
  if (backendDown) return;
  backendDown = true;
  showToast('⚠️ バックエンド(GLM Core)に接続できません。py glm_app_launcher.py 等でCoreを先に起動してください。', 'error', 12000);
}

// Toast Notifications (Self-healing & System Alert)
function showToast(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ── Initialize Monaco Editor (Local Offline) ─────────────────────────────────
require.config({ paths: { vs: 'vs' } });

require(['vs/editor/editor.main'], function () {
  monacoEditor = monaco.editor.create(document.getElementById('editor-container'), {
    value: '#!/usr/bin/env python3\n"""GLM Standalone IDE"""\n\ndef main():\n    print("GLM IDE ready.")\n\nif __name__ == "__main__":\n    main()\n',
    language: 'python',
    theme: 'vs-dark',
    automaticLayout: true,
    fontSize: 13,
    minimap: { enabled: false }
  });

  // Ctrl + S Binding in Monaco
  monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
    saveActiveFile();
  });

  // Check syntax on content change (Debounced)
  let syntaxTimeout = null;
  monacoEditor.onDidChangeModelContent(() => {
    if (syntaxTimeout) clearTimeout(syntaxTimeout);
    syntaxTimeout = setTimeout(() => {
      checkActiveFileSyntax();
    }, 800);
  });

  monaco.languages.registerCompletionItemProvider('python', {
    triggerCharacters: ['.', '_'],
    provideCompletionItems: async (model, position) => {
      const word = model.getWordUntilPosition(position);
      const range = new monaco.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn);
      // 本格LSP (pyright-langserver) を優先し、失敗時はAST補完へ退避
      try {
        const res = await fetch(`${CORE_URL}/api/lsp/completions`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: activeTabPath, line: position.lineNumber, character: position.column, content: model.getValue() })
        });
        const data = await res.json();
        if (data.ok && data.engine === 'pyright-lsp') {
          return { suggestions: (data.items || []).map(item => ({
            label: item.label,
            kind: monaco.languages.CompletionItemKind.Variable,
            detail: item.detail || '',
            documentation: item.documentation || '',
            insertText: item.label, range
          })) };
        }
        return { suggestions: (data.items || []).map(item => ({
          label: item.label, kind: monaco.languages.CompletionItemKind.Variable,
          insertText: item.label, range
        })) };
      } catch (error) { return { suggestions: [] }; }
    }
  });

  monaco.languages.registerHoverProvider('python', {
    provideHover: async (model, position) => {
      try {
        const res = await fetch(`${CORE_URL}/api/lsp/hover`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: activeTabPath, line: position.lineNumber, character: position.column, content: model.getValue() })
        });
        const data = await res.json();
        if (!data.ok || !data.hover) return null;
        return { contents: [{ value: '```\n' + String(data.hover).slice(0, 4000) + '\n```' }] };
      } catch (error) { return null; }
    }
  });
});

// ── Initialization & Polling Loops ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await initAuth();
  setupEventListeners();
  startStatusPolling();
  startApprovalPolling();
  fetchWorkspaceFiles();
  fetchSessions();
  fetchGitStatus();
  fetchSftpProfiles();
  fetchProviderStatus();
  fetchIntegrationStatus();
  fetchCustomizations();
  fetchCustomizationFiles();
  fetchModels();
  fetchMarketplaceExtensions();
  fetchPylanceMcp();
});

function setupEventListeners() {
  setupUiIcons();
  document.querySelectorAll('.controls button, .view-toggle button').forEach(button => {
    const label = button.textContent.trim();
    if (label && !button.title) button.title = label;
    if (label && !button.getAttribute('aria-label')) button.setAttribute('aria-label', label);
  });
  const modeSelect = document.getElementById('mode-select');
  modeSelect.addEventListener('change', (e) => {
    document.getElementById('status-mode').textContent = MODE_LABELS[e.target.value] || e.target.value;
  });

  document.querySelectorAll('.menu-item.has-submenu').forEach((item) => {
    item.addEventListener('click', () => {
      const dropdown = document.getElementById('menu-dropdown');
      const menuName = item.dataset.menu;
      const active = item.classList.contains('active');
      document.querySelectorAll('.menu-item.has-submenu').forEach((btn) => btn.classList.remove('active'));
      if (!active) {
        item.classList.add('active');
        dropdown.classList.remove('hidden');
        dropdown.dataset.menu = menuName;
        const rect = item.getBoundingClientRect();
        dropdown.style.left = `${Math.max(6, Math.min(rect.left, window.innerWidth - 246))}px`;
        dropdown.style.top = `${rect.bottom + 4}px`;
        renderApplicationMenu(menuName);
      } else {
        dropdown.classList.add('hidden');
      }
    });
  });

  document.querySelectorAll('.dropdown-item[data-action]').forEach((item) => {
    item.addEventListener('click', () => runMenuAction(item.dataset.action));
  });

  document.addEventListener('click', (event) => {
    if (!event.target.closest('.menu-item.has-submenu') && !event.target.closest('.menu-dropdown')) {
      document.getElementById('menu-dropdown').classList.add('hidden');
      document.querySelectorAll('.menu-item.has-submenu').forEach((btn) => btn.classList.remove('active'));
    }
  });

  document.getElementById('btn-run').addEventListener('click', runActiveFile);
  document.getElementById('btn-debug').addEventListener('click', startDebugSession);
  document.getElementById('btn-debug-stop').addEventListener('click', stopDebugSession);
  document.getElementById('btn-debug-breakpoint').addEventListener('click', setDebugBreakpoint);
  document.getElementById('btn-debug-continue').addEventListener('click', () => dapCommand('continue'));
  document.getElementById('btn-debug-next').addEventListener('click', () => dapCommand('next'));
  document.getElementById('btn-debug-inspect').addEventListener('click', inspectDebugState);
  const debugAliases = {
    'btn-debug2': startDebugSession,
    'btn-debug-stop2': stopDebugSession,
    'btn-debug-breakpoint2': setDebugBreakpoint,
    'btn-debug-continue2': () => dapCommand('continue'),
    'btn-debug-next2': () => dapCommand('next'),
    'btn-debug-inspect2': inspectDebugState,
  };
  Object.entries(debugAliases).forEach(([id, handler]) => {
    const button = document.getElementById(id);
    if (button) button.addEventListener('click', handler);
  });
  document.getElementById('btn-save').addEventListener('click', saveActiveFile);
  document.getElementById('btn-status').addEventListener('click', runDoctor);
  document.getElementById('btn-dev-status').addEventListener('click', showDevStatus);
  document.getElementById('btn-palette').addEventListener('click', () => openPalette('command'));
  const btnAgentStop = document.getElementById('btn-agent-stop');
  if (btnAgentStop) btnAgentStop.addEventListener('click', stopAgent);

  document.querySelectorAll('.bottom-tab').forEach(tab => {
    tab.addEventListener('click', () => switchBottomTab(tab.getAttribute('data-tab')));
  });

  const terminalInput = document.getElementById('terminal-input');
  if (terminalInput) {
    terminalInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const line = terminalInput.value;
        terminalInput.value = '';
        sendTerminalInput(line + '\n');
      }
    });
  }
  document.getElementById('btn-diff').addEventListener('click', toggleDiffView);
  document.getElementById('btn-view-code').addEventListener('click', switchToCodeView);
  document.getElementById('btn-view-diff').addEventListener('click', toggleDiffView);
  document.getElementById('btn-clear').addEventListener('click', clearChat);
  document.getElementById('btn-refresh-files').addEventListener('click', fetchWorkspaceFiles);

  const btnKill = document.getElementById('btn-kill');
  if (btnKill) {
    btnKill.addEventListener('click', async () => {
      if (confirm('🛑 非常用キルスイッチを起動しますか？\nすべてのAI処理・ツール実行・バックエンドプロセスが即時一括停止されます。')) {
        showToast('🛑 キルスイッチ発動。全プロセスを停止中...', 'error', 10000);
        try {
          await fetch(`${CORE_URL}/api/kill`, { method: 'POST', headers: authHeader });
        } catch (e) {}
        document.body.innerHTML = `
          <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;height:100vh;background:#11111b;color:#f38ba8;font-family:sans-serif">
            <h1>🛑 EMERGENCY KILL SWITCH ACTIVATED</h1>
            <p style="color:#cdd6f4">すべてのAIモデル・ツール実行・バックエンドプロセスが即時物理停止されました。</p>
            <p style="color:#a6adc8;font-size:12px">安全確保のためアプリを終了してください。</p>
          </div>
        `;
      }
    });
  }
  
  const btnClearOutput = document.getElementById('btn-clear-output');
  if (btnClearOutput) btnClearOutput.addEventListener('click', () => {
    document.getElementById('output-text').textContent = '待機中...';
  });
  
  const btnGitRefresh = document.getElementById('btn-refresh-git');
  if (btnGitRefresh) btnGitRefresh.addEventListener('click', fetchGitStatus);

  const btnGitCommit = document.getElementById('btn-git-commit');
  if (btnGitCommit) btnGitCommit.addEventListener('click', performGitCommit);

  const btnGitStage = document.getElementById('btn-git-stage');
  if (btnGitStage) btnGitStage.addEventListener('click', performGitStage);

  const btnGitCheckout = document.getElementById('btn-git-checkout');
  if (btnGitCheckout) btnGitCheckout.addEventListener('click', performGitCheckout);

  const btnGitPush = document.getElementById('btn-git-push');
  if (btnGitPush) btnGitPush.addEventListener('click', performGitPush);

  const btnGoDefinition = document.getElementById('btn-go-definition');
  if (btnGoDefinition) btnGoDefinition.addEventListener('click', goToDefinitionAtCursor);
  const btnFindReferences = document.getElementById('btn-find-references');
  if (btnFindReferences) btnFindReferences.addEventListener('click', findReferencesAtCursor);
  const btnRenameSymbol = document.getElementById('btn-rename-symbol');
  if (btnRenameSymbol) btnRenameSymbol.addEventListener('click', proposeRenameAtCursor);
  const btnRenameApply = document.getElementById('btn-rename-apply');
  if (btnRenameApply) btnRenameApply.addEventListener('click', applyRenameAtCursor);
  const btnReviewSelection = document.getElementById('btn-review-selection');
  if (btnReviewSelection) btnReviewSelection.addEventListener('click', reviewSelectedCode);
  const btnCommitSuggest = document.getElementById('btn-commit-suggest');
  if (btnCommitSuggest) btnCommitSuggest.addEventListener('click', suggestCommitMessage);
  const btnSftpList = document.getElementById('btn-sftp-list');
  if (btnSftpList) btnSftpList.addEventListener('click', listSftpRemote);
  const btnSftpUpload = document.getElementById('btn-sftp-upload');
  if (btnSftpUpload) btnSftpUpload.addEventListener('click', uploadSftpActiveFile);
  const btnSftpDownload = document.getElementById('btn-sftp-download');
  if (btnSftpDownload) btnSftpDownload.addEventListener('click', downloadSftpFile);
  const btnSftpProfileSave = document.getElementById('btn-sftp-profile-save');
  if (btnSftpProfileSave) btnSftpProfileSave.addEventListener('click', saveSftpProfile);
  const btnSftpProfileDelete = document.getElementById('btn-sftp-profile-delete');
  if (btnSftpProfileDelete) btnSftpProfileDelete.addEventListener('click', deleteSftpProfile);
  const btnSftpTest = document.getElementById('btn-sftp-test');
  if (btnSftpTest) btnSftpTest.addEventListener('click', testSftpConnection);
  const sftpProfile = document.getElementById('sftp-profile');
  if (sftpProfile) sftpProfile.addEventListener('change', loadSftpProfile);
  const providerSelect = document.getElementById('provider-select');
  if (providerSelect) providerSelect.addEventListener('change', syncProviderModels);
  document.querySelectorAll('[data-provider-save]').forEach(button => {
    button.addEventListener('click', () => saveProviderCredential(button.dataset.providerSave));
  });
  document.querySelectorAll('[data-provider-test]').forEach(button => {
    button.addEventListener('click', () => testProviderConnection(button.dataset.providerTest));
  });
  document.querySelectorAll('[data-integration-save]').forEach(button => {
    button.addEventListener('click', () => saveIntegrationCredential(button.dataset.integrationSave));
  });
  document.querySelectorAll('[data-integration-save-group]').forEach(button => {
    button.addEventListener('click', () => saveIntegrationCredentialGroup(button.dataset.integrationSaveGroup));
  });
  document.querySelectorAll('[data-integration-toggle]').forEach(button => {
    button.addEventListener('click', () => toggleIntegration(button.dataset.integrationToggle));
  });

  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  const voiceButton = document.getElementById('btn-voice');
  const chatHistoryButton = document.getElementById('btn-chat-history');
  if (chatHistoryButton) chatHistoryButton.addEventListener('click', toggleChatHistoryPopover);
  const chatNewButton = document.getElementById('btn-chat-new');
  if (chatNewButton) chatNewButton.addEventListener('click', clearChat);
  const chatAddButton = document.getElementById('btn-chat-add');
  if (chatAddButton) chatAddButton.addEventListener('click', () => openPalette('file'));
  const chatOptionsButton = document.getElementById('btn-chat-options');
  if (chatOptionsButton) chatOptionsButton.addEventListener('click', () => switchSidebarView('settings'));
  const planButton = document.getElementById('btn-orchestration-plan');
  if (planButton) planButton.addEventListener('click', createOrchestrationPlan);
  const mlopsRefresh = document.getElementById('btn-mlops-refresh');
  if (mlopsRefresh) mlopsRefresh.addEventListener('click', refreshMLOpsStatus);
  const orchestrationToggle = document.getElementById('orchestration-toggle');
  if (orchestrationToggle) {
    const toggle = (event) => {
      if (event?.target.closest('#btn-mlops-refresh')) return;
      const body = document.getElementById('orchestration-body');
      if (!body) return;
      const expanded = body.classList.toggle('hidden') === false;
      orchestrationToggle.setAttribute('aria-expanded', String(expanded));
    };
    orchestrationToggle.addEventListener('click', toggle);
    orchestrationToggle.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(event); }
    });
  }

  chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text || isGenerating) return;
    chatInput.value = '';
    sendChatMessage(text);
  });

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event('submit'));
    }
  });

  if (voiceButton) voiceButton.addEventListener('click', () => startVoiceInput(voiceButton, chatInput));

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      saveActiveFile();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'P' || e.key === 'p')) {
      e.preventDefault();
      openPalette('command');
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === 'P' || e.key === 'p')) {
      e.preventDefault();
      openPalette('file');
      return;
    }
    if (e.key === 'F1') {
      e.preventDefault();
      openPalette('command');
      return;
    }
    if (e.key === 'Escape') closePalette();
  });

  // Approval actions
  document.querySelectorAll('.approval-actions button').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const action = e.target.getAttribute('data-action');
      const reqId = e.target.closest('.approval-card').getAttribute('data-id');
      respondApproval(reqId, action);
    });
  });
}

const PROVIDER_MODELS = {
  anthropic: ['claude-haiku-4-5', 'claude-sonnet-5'],
  openai: ['gpt-4.1', 'gpt-5']
};

function syncProviderModels() {
  const provider = document.getElementById('provider-select')?.value || 'anthropic';
  const select = document.getElementById('provider-model');
  if (!select) return;
  select.innerHTML = (PROVIDER_MODELS[provider] || []).map(model => `<option value="${model}">${model}</option>`).join('');
}

async function fetchProviderStatus() {
  syncProviderModels();
  try {
    const response = await fetch(`${CORE_URL}/api/providers/status`, { headers: authHeader });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    Object.entries(data.providers || {}).forEach(([provider, status]) => {
      const target = document.getElementById(`provider-${provider}-status`);
      if (target) target.textContent = status.configured ? '保存済み' : '未接続';
    });
  } catch (error) { showToast(`プロバイダ状態を取得できません: ${error.message}`, 'warning'); }
}

async function saveProviderCredential(provider) {
  const input = document.getElementById(`provider-${provider}-credential`);
  const credential = input?.value.trim();
  if (!credential) { showToast('APIキーまたはPATを入力してください', 'warning'); return; }
  try {
    const response = await fetch(`${CORE_URL}/api/providers/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ provider, credential })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    input.value = '';
    await fetchProviderStatus();
    showToast(`${provider} の資格情報を保存しました`, 'success');
  } catch (error) { showToast(`保存に失敗しました: ${error.message}`, 'error'); }
}

async function testProviderConnection(provider) {
  try {
    const response = await fetch(`${CORE_URL}/api/providers/test`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ provider })
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    showToast(`${provider} の接続を確認しました`, 'success');
  } catch (error) { showToast(`${provider} の接続に失敗しました: ${error.message}`, 'error'); }
}

let integrationStates = {};

async function fetchIntegrationStatus() {
  try {
    const response = await fetch(`${CORE_URL}/api/integrations/status`, { headers: authHeader });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    integrationStates = data.integrations || {};
    Object.entries(integrationStates).forEach(([name, status]) => {
      const target = document.getElementById(`integration-${name}-status`);
      if (target) target.textContent = status.ready ? '利用可能' : (status.enabled ? '資格情報が不足' : '無効');
    });
  } catch (error) { showToast(`外部連携状態を取得できません: ${error.message}`, 'warning'); }
}

async function fetchCustomizations() {
  const status = document.getElementById('customization-summary-status');
  const summary = document.getElementById('customization-summary');
  const items = document.getElementById('customization-items');
  if (!summary || !items) return;
  try {
    const response = await fetch(`${CORE_URL}/api/customizations`, { headers: authHeader });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const documents = data.documents || [];
    const servers = data.mcp_servers || [];
    const hooks = Object.values(data.hooks || {}).reduce((total, value) => total + Number(value || 0), 0);
    summary.textContent = `${documents.length} 文書 / ${servers.length} MCPサーバー / ${hooks} Hook`;
    if (status) status.textContent = '読み込み済み';
    const documentMarkup = documents.map(item =>
      `<div class="customization-item"><strong>${escapeHtml(item.kind)}</strong><span>${escapeHtml(item.name)}</span><small>${escapeHtml(item.path)}</small></div>`
    ).join('');
    const serverMarkup = servers.map(server =>
      `<div class="customization-item"><strong>MCP</strong><span>${escapeHtml(server.name || '')}</span><small>${server.enabled ? '有効' : '無効'}: ${escapeHtml(String(server.command || ''))}</small></div>`
    ).join('');
    items.innerHTML = documentMarkup + serverMarkup || '<div class="setting-help">カスタマイズファイルは未検出です。</div>';
  } catch (error) {
    if (status) status.textContent = '取得失敗';
    summary.textContent = error.message;
  }
}

async function reloadCustomizations() {
  try {
    const response = await fetch(`${CORE_URL}/api/customizations/reload`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: '{}'
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    await fetchCustomizations();
    showToast('Agentカスタマイズを再読み込みしました', 'success');
  } catch (error) { showToast(`カスタマイズの再読み込みに失敗しました: ${error.message}`, 'error'); }
}

async function fetchCustomizationFiles() {
  try {
    const response = await fetch(`${CORE_URL}/api/customizations/files`, { headers: authHeader });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    customizationFiles = data.files || [];
    const select = document.getElementById('customization-file-select');
    if (select) {
      select.innerHTML = '<option value="">編集するファイルを選択</option>' + customizationFiles.map(file =>
        `<option value="${escapeHtml(file.path)}">${escapeHtml(file.kind)}: ${escapeHtml(file.name)}</option>`).join('');
    }
  } catch (error) { showToast(`カスタマイズファイルを取得できません: ${error.message}`, 'warning'); }
}

async function saveCustomizationFile() {
  const path = document.getElementById('customization-file-select')?.value;
  const content = document.getElementById('customization-editor')?.value || '';
  if (!path) { showToast('編集するカスタマイズファイルを選択してください', 'warning'); return; }
  try {
    const response = await fetch(`${CORE_URL}/api/customizations/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: JSON.stringify({ path, content })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    await fetchCustomizations();
    await fetchCustomizationFiles();
    showToast('カスタマイズファイルを保存しました', 'success');
  } catch (error) { showToast(`保存に失敗しました: ${error.message}`, 'error'); }
}

async function validateCustomizations() {
  const target = document.getElementById('customization-validation');
  try {
    const response = await fetch(`${CORE_URL}/api/customizations/validate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: '{}'
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    if (target) target.textContent = data.ok ? '検証成功: エラーはありません。' : data.errors.map(item => `${item.path}: ${item.error}`).join('\n');
    showToast(data.ok ? 'カスタマイズ検証に成功しました' : 'カスタマイズに検証エラーがあります', data.ok ? 'success' : 'warning');
  } catch (error) { if (target) target.textContent = error.message; }
}

async function fetchModels() {
  try {
    const response = await fetch(`${CORE_URL}/api/models`, { headers: authHeader });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const selects = [document.getElementById('settings-model'), document.getElementById('agent-model-select')].filter(Boolean);
    selects.forEach(select => {
      select.innerHTML = '<option value="auto">Auto</option>' + data.models.map(model =>
        `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)} (${escapeHtml(model.execution)})</option>`).join('');
      select.value = data.selection?.model || 'auto';
    });
    const temperature = document.getElementById('model-temperature');
    const maxTokens = document.getElementById('model-max-tokens');
    if (temperature) temperature.value = data.selection?.temperature ?? 0.3;
    if (maxTokens) maxTokens.value = data.selection?.max_tokens ?? 2048;
    const status = document.getElementById('model-selection-status');
    if (status) status.textContent = `${data.models.length}モデルを検出。未接続クラウドは選択できますが実行時に接続確認されます。`;
  } catch (error) { const status = document.getElementById('model-selection-status'); if (status) status.textContent = error.message; }
}

async function saveModelSelection() {
  const model = document.getElementById('settings-model')?.value || 'auto';
  const temperature = document.getElementById('model-temperature')?.value || 0.3;
  const max_tokens = document.getElementById('model-max-tokens')?.value || 2048;
  try {
    const response = await fetch(`${CORE_URL}/api/models/set`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: JSON.stringify({ model, temperature, max_tokens })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    showToast('モデル設定を保存しました', 'success');
  } catch (error) { showToast(`モデル設定を保存できません: ${error.message}`, 'error'); }
}

async function fetchMarketplaceExtensions(query = '') {
  const list = document.getElementById('marketplace-list');
  if (!list) return;
  try {
    const response = await fetch(`${CORE_URL}/api/marketplace/extensions?q=${encodeURIComponent(query)}`, { headers: authHeader });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    list.innerHTML = (data.extensions || []).map(item => `<div class="ext-item marketplace-item"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.description)}</span><small>${escapeHtml(item.publisher)} ${escapeHtml(item.version)} ${item.installed ? '・インストール済み' : ''}</small>${item.installed ? '' : `<button class="btn secondary" data-marketplace-install="${escapeHtml(item.id)}">インストール</button>`}</div>`).join('') || '<div class="setting-help">一致する拡張機能はありません。</div>';
  } catch (error) { list.innerHTML = `<div class="setting-help">${escapeHtml(error.message)}</div>`; }
}

async function installMarketplaceExtension(id) {
  try {
    const response = await fetch(`${CORE_URL}/api/marketplace/install`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: JSON.stringify({ id }) });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    await fetchMarketplaceExtensions(document.getElementById('marketplace-search')?.value || '');
    showToast('拡張機能を有効化しました', 'success');
  } catch (error) { showToast(`拡張機能を有効化できません: ${error.message}`, 'error'); }
}

async function fetchPylanceMcp() {
  const status = document.getElementById('pylance-mcp-status');
  const tools = document.getElementById('pylance-mcp-tools');
  if (!status || !tools) return;
  try {
    const response = await fetch(`${CORE_URL}/api/pylance/mcp/status`, { headers: authHeader });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    status.textContent = `${data.engine}: ${data.status?.running ? '稼働中' : '必要時起動'}（VS Code内Pylanceの代替ブリッジ）`;
    tools.innerHTML = (data.tools || []).map(tool => `<div class="customization-item"><strong>MCP</strong><span>${escapeHtml(tool)}</span></div>`).join('');
  } catch (error) { status.textContent = error.message; }
}

async function saveIntegrationCredential(secretName) {
  const input = document.querySelector(`[data-integration-secret="${secretName}"]`);
  const credential = input?.value.trim();
  if (!credential) { showToast('資格情報を入力してください', 'warning'); return; }
  try {
    await sendIntegrationCredential(secretName, credential);
    input.value = '';
  } catch (error) { showToast(`資格情報の保存に失敗しました: ${error.message}`, 'error'); }
}

async function saveIntegrationCredentialGroup(name) {
  const states = integrationStates[name];
  const inputs = [...document.querySelectorAll(`[data-integration-secret]`)];
  const required = states?.missing_secrets || [];
  const values = inputs.filter(input => required.includes(input.dataset.integrationSecret) && input.value.trim());
  if (values.length !== required.length) { showToast('表示されている必須資格情報をすべて入力してください', 'warning'); return; }
  try {
    for (const input of values) {
      await sendIntegrationCredential(input.dataset.integrationSecret, input.value.trim());
      input.value = '';
    }
  } catch (error) { showToast(`資格情報の保存に失敗しました: ${error.message}`, 'error'); }
}

async function sendIntegrationCredential(secretName, credential) {
  const response = await fetch(`${CORE_URL}/api/integrations/credential/save`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
    body: JSON.stringify({ secret_name: secretName, credential })
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  await fetchIntegrationStatus();
  showToast('資格情報を保存しました', 'success');
}

async function toggleIntegration(name) {
  const current = integrationStates[name];
  if (!current) return;
  try {
    const response = await fetch(`${CORE_URL}/api/integrations/set-enabled`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ name, enabled: !current.enabled })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    await fetchIntegrationStatus();
    showToast(`${name} を${data.status.enabled ? '有効化' : '無効化'}しました`, 'success');
  } catch (error) { showToast(`${name} の設定変更に失敗しました: ${error.message}`, 'error'); }
}

async function refreshMLOpsStatus() {
  try {
    const response = await fetch(`${CORE_URL}/api/mlops/status`, { headers: authHeader });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const target = document.getElementById('mlops-status');
    let profileText = '';
    try {
      const profileResponse = await fetch(`${CORE_URL}/api/orchestrator/profiles`, { headers: authHeader });
      const profileData = await profileResponse.json();
      profileText = ` / ${Object.keys(profileData.profiles || {}).length}エージェント`;
    } catch (error) { profileText = ''; }
    if (target) target.textContent = `Airflow: ${data.airflow_enabled ? '有効' : '無効'} / MLflow: ${data.mlflow_enabled ? '有効' : 'ローカル記録'}${profileText}`;
  } catch (error) {
    showToast(`MLOps状態を取得できません: ${error.message}`, 'warning');
  }
}

async function createOrchestrationPlan() {
  const input = document.getElementById('orchestration-objective');
  const target = document.getElementById('orchestration-status');
  const objective = input?.value.trim();
  if (!objective) {
    showToast('作業目的を入力してください', 'warning');
    return;
  }
  try {
    target.textContent = 'Coordinatorが計画を作成中...';
    const response = await fetch(`${CORE_URL}/api/orchestrator/plan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ objective, session_id: agentSessionId })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const roles = (data.plan.tasks || []).map(task => task.role).join(' → ');
    target.textContent = `計画済み: ${roles}（自動マージ無効）`;
    showToast('安全なエージェント計画を作成しました', 'success');
  } catch (error) {
    target.textContent = 'Coordinatorエラー';
    showToast(`計画作成に失敗しました: ${error.message}`, 'error');
  }
}

const APPLICATION_MENUS = {
  file: [
    { action: 'new-file', label: '新しいテキスト ファイル', key: 'Ctrl+N' },
    { action: 'new-folder', label: '新しいフォルダー' },
    { action: 'new-window', label: '新しいウィンドウ', key: 'Ctrl+Shift+N', disabled: true },
    { type: 'separator' },
    { action: 'open-file', label: 'ファイルを開く...', key: 'Ctrl+O' },
    { action: 'open-folder', label: 'フォルダーを開く...' },
    { action: 'open-recent', label: '最近使用した項目を開く', submenu: true, disabled: true },
    { type: 'separator' },
    { action: 'save', label: '保存', key: 'Ctrl+S' },
    { action: 'save-as', label: '名前を付けて保存...', key: 'Ctrl+Shift+S', disabled: true },
    { action: 'auto-save', label: '自動保存', checked: false, disabled: true },
    { type: 'separator' },
    { action: 'settings', label: 'ユーザー設定', key: 'Ctrl+,' },
    { action: 'close-workspace', label: 'フォルダーを閉じる', disabled: true },
  ],
  edit: [
    { action: 'undo', label: '元に戻す', key: 'Ctrl+Z' },
    { action: 'redo', label: 'やり直し', key: 'Ctrl+Y' },
    { type: 'separator' },
    { action: 'cut', label: '切り取り', key: 'Ctrl+X' },
    { action: 'copy', label: 'コピー', key: 'Ctrl+C' },
    { action: 'paste', label: '貼り付け', key: 'Ctrl+V' },
    { type: 'separator' },
    { action: 'find', label: '検索', key: 'Ctrl+F' },
    { action: 'replace', label: '置換', key: 'Ctrl+H' },
    { action: 'find-in-files', label: 'ファイル内を検索', key: 'Ctrl+Shift+F' },
    { type: 'separator' },
    { action: 'select-all', label: 'すべて選択', key: 'Ctrl+A' },
  ],
  selection: [
    { action: 'select-all', label: 'すべて選択', key: 'Ctrl+A' },
    { action: 'expand-selection', label: '選択範囲を拡張', key: 'Shift+Alt+Right', disabled: true },
    { action: 'shrink-selection', label: '選択範囲を縮小', key: 'Shift+Alt+Left', disabled: true },
    { type: 'separator' },
    { action: 'copy-line-up', label: '行を上へコピー', key: 'Shift+Alt+Up', disabled: true },
    { action: 'copy-line-down', label: '行を下へコピー', key: 'Shift+Alt+Down', disabled: true },
    { action: 'move-line-up', label: '行を上へ移動', key: 'Alt+Up', disabled: true },
    { action: 'move-line-down', label: '行を下へ移動', key: 'Alt+Down', disabled: true },
    { type: 'separator' },
    { action: 'format-document', label: 'ドキュメントのフォーマット', key: 'Shift+Alt+F' },
  ],
  view: [
    { action: 'command-palette', label: 'コマンド パレット...', key: 'Ctrl+Shift+P' },
    { action: 'quick-open', label: 'ファイルを開く...', key: 'Ctrl+P' },
    { type: 'separator' },
    { action: 'explorer', label: 'エクスプローラー', key: 'Ctrl+Shift+E' },
    { action: 'search', label: '検索', key: 'Ctrl+Shift+F' },
    { action: 'source-control', label: 'ソース管理', key: 'Ctrl+Shift+G' },
    { action: 'debug-view', label: '実行とデバッグ', key: 'Ctrl+Shift+D' },
    { action: 'extensions', label: '拡張機能', key: 'Ctrl+Shift+X' },
    { type: 'separator' },
    { action: 'terminal', label: 'ターミナル', key: 'Ctrl+`' },
    { action: 'problems', label: '問題', key: 'Ctrl+Shift+M' },
    { action: 'toggle-bottom', label: '下部パネルの表示切替' },
    { action: 'toggle-sidebar', label: 'プライマリ サイド バーの表示切替', key: 'Ctrl+B' },
    { action: 'toggle-ai', label: 'セカンダリ サイド バーの表示切替' },
    { type: 'separator' },
    { action: 'zoom-in', label: '拡大', key: 'Ctrl+=' },
    { action: 'zoom-out', label: '縮小', key: 'Ctrl+-' },
    { action: 'zoom-reset', label: 'ズームのリセット', key: 'Ctrl+0' },
  ],
  go: [
    { action: 'back', label: '戻る', key: 'Alt+Left', disabled: true },
    { action: 'forward', label: '進む', key: 'Alt+Right', disabled: true },
    { type: 'separator' },
    { action: 'quick-open', label: 'ファイルへ移動...', key: 'Ctrl+P' },
    { action: 'symbol', label: 'ワークスペース内のシンボルへ移動...', key: 'Ctrl+T', disabled: true },
    { type: 'separator' },
    { action: 'definition', label: '定義へ移動', key: 'F12' },
    { action: 'references', label: '参照へ移動', key: 'Shift+F12' },
    { action: 'go-line', label: '行/列へ移動...', key: 'Ctrl+G', disabled: true },
  ],
  run: [
    { action: 'run-file', label: 'デバッグなしで実行', key: 'Ctrl+F5' },
    { action: 'debug-start', label: 'デバッグの開始', key: 'F5' },
    { action: 'debug-stop', label: 'デバッグの停止', key: 'Shift+F5' },
    { type: 'separator' },
    { action: 'debug-continue', label: '続行', key: 'F5' },
    { action: 'debug-next', label: 'ステップ オーバー', key: 'F10' },
    { action: 'debug-inspect', label: 'スタック/変数を確認' },
    { type: 'separator' },
    { action: 'problems', label: '問題を表示' },
  ],
  terminal: [
    { action: 'terminal', label: '新しいターミナル', key: 'Ctrl+Shift+`' },
    { action: 'terminal', label: 'ターミナルを表示', key: 'Ctrl+`' },
    { action: 'terminal-stop', label: '実行中のターミナル タスクを停止' },
    { type: 'separator' },
    { action: 'terminal-profile', label: '既定のプロファイルを選択', submenu: true, disabled: true },
    { action: 'terminal-settings', label: 'ターミナル設定' },
  ],
  help: [
    { action: 'command-palette', label: 'すべてのコマンドを表示', key: 'Ctrl+Shift+P' },
    { action: 'doctor', label: 'システム診断を開く' },
    { action: 'dev-status', label: '開発環境の状態' },
    { type: 'separator' },
    { action: 'provider-settings', label: 'AIプロバイダ接続設定' },
    { action: 'about', label: 'GLM Standalone IDE について' },
  ]
};

function renderApplicationMenu(menuName) {
  const dropdown = document.getElementById('menu-dropdown');
  const items = APPLICATION_MENUS[menuName] || APPLICATION_MENUS.file;
  dropdown.innerHTML = items.map(item => {
    if (item.type === 'separator') return '<div class="dropdown-separator" role="separator"></div>';
    const checked = item.checked ? '<span class="dropdown-check">✓</span>' : '<span class="dropdown-check"></span>';
    const key = item.key ? `<span class="dropdown-key">${escapeHtml(item.key)}</span>` : '';
    const chevron = item.submenu ? '<span class="dropdown-submenu">›</span>' : '';
    const disabled = item.disabled ? ' aria-disabled="true"' : '';
    return `<button type="button" class="dropdown-item${item.disabled ? ' disabled' : ''}" data-action="${escapeHtml(item.action)}"${disabled}>${checked}<span class="dropdown-label">${escapeHtml(item.label)}</span>${key}${chevron}</button>`;
  }).join('');
  dropdown.querySelectorAll('.dropdown-item[data-action]:not(.disabled)').forEach(item => {
    item.addEventListener('click', () => runMenuAction(item.dataset.action));
  });
}

function startVoiceInput(button, input) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    showToast('このWebViewでは音声入力を利用できません。', 'warning');
    return;
  }
  const recognition = new SpeechRecognition();
  recognition.lang = 'ja-JP';
  recognition.interimResults = false;
  recognition.onstart = () => { button.classList.add('recording'); button.innerHTML = '<span class="loader-ring"></span>'; };
  recognition.onresult = event => {
    input.value = `${input.value}${input.value ? ' ' : ''}${event.results[0][0].transcript}`;
    input.focus();
  };
  recognition.onerror = () => showToast('音声入力を取得できませんでした。', 'warning');
  recognition.onend = () => { button.classList.remove('recording'); applyUiIcon(button, 'mic', '音声入力'); };
  recognition.start();
}

async function runMenuAction(action) {
  document.getElementById('menu-dropdown')?.classList.add('hidden');
  document.querySelectorAll('.menu-item.has-submenu').forEach(btn => btn.classList.remove('active'));
  if (action === 'new-file') return createWorkspaceFile();
  if (action === 'new-folder') return createWorkspaceFolder();
  if (action === 'open-file') {
    const relPath = await requestWorkspacePath('開くファイル', workspaceFiles[0] || '');
    if (relPath?.trim()) openFileInEditor(relPath.trim());
    return;
  }
  if (action === 'open-folder') {
    showToast('このIDEは起動時ワークスペースを使用します。別フォルダーは再起動時に指定してください。', 'info', 4500);
    return;
  }
  if (action === 'settings' || action === 'workbench-settings') return switchSidebarView('settings');
  if (action === 'ai-panel') return toggleAIPanel();
  if (action === 'theme') return showToast('テーマ切替は現在のダークテーマを使用しています。', 'info', 3000);
  if (action === 'save') return saveActiveFile();
  if (action === 'find') return monacoEditor?.getAction('actions.find')?.run();
  if (action === 'replace') return monacoEditor?.getAction('editor.action.startFindReplaceAction')?.run();
  if (action === 'find-in-files') return switchSidebarView('search');
  if (action === 'undo') return monacoEditor?.trigger('glm', 'undo', null);
  if (action === 'redo') return monacoEditor?.trigger('glm', 'redo', null);
  if (action === 'select-all') return monacoEditor?.trigger('glm', 'editor.action.selectAll', null);
  if (action === 'copy') return document.execCommand('copy');
  if (action === 'cut') return document.execCommand('cut');
  if (action === 'paste') return navigator.clipboard?.readText().then(text => {
    if (monacoEditor && text) monacoEditor.trigger('glm', 'type', { text });
  });
  if (action === 'format-document') return monacoEditor?.getAction('editor.action.formatDocument')?.run();
  if (action === 'explorer' || action === 'search') return switchSidebarView(action);
  if (action === 'source-control') return switchSidebarView('git');
  if (action === 'debug-view') return switchSidebarView('debug');
  if (action === 'extensions') return switchSidebarView('extensions');
  if (action === 'toggle-sidebar') return toggleSidebar();
  if (action === 'toggle-ai') return toggleAIPanel();
  if (action === 'toggle-bottom') return toggleBottomPanel();
  if (action === 'definition') return goToDefinitionAtCursor();
  if (action === 'references') return findReferencesAtCursor();
  if (action === 'quick-open') return openPalette('file');
  if (action === 'command-palette') return openPalette('command');
  if (action === 'run-file') return runActiveFile();
  if (action === 'debug-start') return startDebugSession();
  if (action === 'debug-stop') return stopDebugSession();
  if (action === 'debug-continue') return dapCommand('continue');
  if (action === 'debug-next') return dapCommand('next');
  if (action === 'debug-inspect') return inspectDebugState();
  if (action === 'problems') return switchBottomTab('problems');
  if (action === 'terminal') return switchBottomTab('terminal');
  if (action === 'terminal-settings') return switchSidebarView('settings');
  if (action === 'provider-settings') return switchSidebarView('settings');
  if (action === 'dev-status') return showDevStatus();
  if (action === 'zoom-in' || action === 'zoom-out' || action === 'zoom-reset') return adjustWorkbenchZoom(action);
  if (action === 'terminal-stop') return fetch(`${CORE_URL}/api/terminal/stop`, { method: 'POST', headers: authHeader });
  if (action === 'doctor') return runDoctor();
  if (action === 'about') return showToast('GLM Standalone IDE v1.1 · Local-first development environment', 'info', 4500);
  showToast('このメニュー項目は現在のGLMでは未接続です。', 'info', 2500);
}

let workbenchZoom = 1;
function adjustWorkbenchZoom(action) {
  if (action === 'zoom-reset') workbenchZoom = 1;
  else workbenchZoom = Math.max(0.8, Math.min(1.25, workbenchZoom + (action === 'zoom-in' ? 0.05 : -0.05)));
  document.documentElement.style.setProperty('--workbench-zoom', String(workbenchZoom));
  document.body.style.fontSize = `${Math.round(12 * workbenchZoom)}px`;
  showToast(`ズーム: ${Math.round(workbenchZoom * 100)}%`, 'info', 1200);
}

async function createWorkspaceFile(basePath = '') {
  const initial = basePath ? `${basePath}/new-file.py` : 'new-file.py';
  const relPath = await requestWorkspacePath('新しいファイル', initial);
  if (!relPath?.trim()) return;
  try {
    const res = await fetch(`${CORE_URL}/api/workspace/create`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ path: relPath.trim(), content: '' })
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
    await fetchWorkspaceFiles();
    await openFileInEditor(relPath.trim());
    showToast(`ファイルを作成しました: ${relPath.trim()}`, 'success');
  } catch (error) { showToast(`ファイル作成失敗: ${error.message}`, 'error'); }
}

async function createWorkspaceFolder(basePath = '') {
  const initial = basePath ? `${basePath}/new-folder` : 'new-folder';
  const relPath = await requestWorkspacePath('新しいフォルダー', initial);
  if (!relPath?.trim()) return;
  try {
    const res = await fetch(`${CORE_URL}/api/workspace/create-folder`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ path: relPath.trim() })
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
    await fetchWorkspaceFiles();
    showToast(`フォルダーを作成しました: ${relPath.trim()}`, 'success');
  } catch (error) { showToast(`フォルダー作成失敗: ${error.message}`, 'error'); }
}

async function deleteWorkspaceEntry(relPath) {
  if (!relPath || !confirm(`「${relPath}」を削除しますか？`)) return;
  try {
    const res = await fetch(`${CORE_URL}/api/workspace/delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ path: relPath })
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
    await fetchWorkspaceFiles();
    if (currentActivePath === relPath) {
      currentActivePath = '';
      activeTabPath = '';
      document.getElementById('current-filename').textContent = 'ファイルが選択されていません';
      monacoEditor?.setValue('');
      renderTabs();
    }
    showToast(`削除しました: ${relPath}`, 'success');
  } catch (error) { showToast(`削除失敗: ${error.message}`, 'error'); }
}

async function renameWorkspaceEntry(source) {
  const destination = await requestWorkspacePath('名前の変更', source);
  if (!destination || destination === source) return;
  try {
    const res = await fetch(`${CORE_URL}/api/workspace/move`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ source, destination })
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
    await fetchWorkspaceFiles();
    if (currentActivePath === source) await openFileInEditor(destination);
    showToast(`名前を変更しました: ${destination}`, 'success');
  } catch (error) { showToast(`名前変更失敗: ${error.message}`, 'error'); }
}

function requestWorkspacePath(title, initialValue) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'path-dialog-overlay';
    overlay.innerHTML = `<form class="path-dialog" role="dialog" aria-modal="true">
      <h3>${escapeHtml(title)}</h3>
      <label>ワークスペース相対パス<input class="path-dialog-input" value="${escapeHtml(initialValue)}" autocomplete="off"></label>
      <div class="path-dialog-actions"><button type="button" data-cancel>キャンセル</button><button type="submit" class="btn primary">実行</button></div>
    </form>`;
    document.body.appendChild(overlay);
    const form = overlay.querySelector('form');
    const input = overlay.querySelector('input');
    const finish = value => { overlay.remove(); resolve(value); };
    overlay.querySelector('[data-cancel]').addEventListener('click', () => finish(''));
    form.addEventListener('submit', event => { event.preventDefault(); finish(input.value.trim()); });
    overlay.addEventListener('click', event => { if (event.target === overlay) finish(''); });
    input.focus(); input.select();
  });
}

async function showDevStatus() {
  const panel = document.getElementById('dev-status-panel');
  if (!panel) return;
  try {
    const res = await fetch(`${CORE_URL}/api/dev/status`);
    const data = await res.json();
    const row = (name, value) => `<div><strong>${name}</strong>: ${value}</div>`;
    panel.innerHTML = row('Jupyter', data.jupyter.available ? (data.jupyter.kernel_running ? '稼働中' : '利用可能') : '未導入') +
      row('DAP/debugpy', data.dap.available ? '利用可能' : '未導入') +
      row('SFTP/OpenSSH', data.sftp.available ? '利用可能' : '未導入') +
      '<div>外部ツールは未導入の場合、設定後に有効化されます。</div>';
    panel.classList.remove('hidden');
    setTimeout(() => panel.classList.add('hidden'), 6000);
  } catch (error) {
    showToast(`開発環境の取得エラー: ${error.message}`, 'error');
  }
}

// ── Status Polling (/status) ────────────────────────────────────────────────
async function startStatusPolling() {
  const poll = async () => {
    try {
      const res = await fetch(`${ROUTER_URL}/status`);
      if (res.ok) {
        backendDown = false;
        const data = await res.json();
        document.getElementById('stat-gpu-temp').textContent = `${data.gpu_temp}℃`;
        document.getElementById('stat-gpu-util').textContent = `${data.gpu_util}%`;
        document.getElementById('stat-vram').textContent = `${data.vram_used_gb} / ${data.vram_used_gb + data.vram_free_gb} GB`;
        
        const budgetRatio = Math.round(data.budget_ratio * 100);
        document.getElementById('stat-budget').textContent = `$${data.budget_spent} (${budgetRatio}%)`;

        const warnEl = document.getElementById('stat-throttle-warning');
        if (data.throttling) warnEl.classList.remove('hidden');
        else warnEl.classList.add('hidden');
      }
    } catch (e) {
      showBackendDown();
    }
  };
  poll();
  setInterval(poll, 5000);
}

// ── Approval Polling (/pending) ──────────────────────────────────────────────
async function startApprovalPolling() {
  const poll = async () => {
    try {
      const res = await fetch(`${BROKER_URL}/pending`, { headers: authHeader });
      if (res.ok) {
        const data = await res.json();
        const pending = data.requests || [];
        const container = document.getElementById('approval-container');
        if (pending.length > 0) {
          const req = pending[0];
          const card = container.querySelector('.approval-card');
          card.setAttribute('data-id', req.id);
          document.getElementById('approval-details').textContent = `${req.tool}: ${JSON.stringify(req.params)}`;
          container.classList.remove('hidden');
        } else {
          container.classList.add('hidden');
        }
      }
    } catch (e) {
      // Broker unreachable
    }
  };
  poll();
  setInterval(poll, 1500);
}

async function respondApproval(reqId, actionCode) {
  const decisions = {
    'y': true,
    'a': 'allow_all',
    'n': false,
    'd': 'deny_all'
  };
  const decision = decisions[actionCode] !== undefined ? decisions[actionCode] : false;
  try {
    await fetch(`${BROKER_URL}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ id: reqId, decision })
    });
    document.getElementById('approval-container').classList.add('hidden');
  } catch (e) {
    showToast('承認送信エラー', 'error');
  }
}

// ── Syntax Check & Diagnostics ──────────────────────────────────────────────
async function checkActiveFileSyntax() {
  if (!activeTabPath || !monacoEditor) return;
  const content = monacoEditor.getValue();
  try {
    const res = await fetch(`${CORE_URL}/api/workspace/syntax`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: activeTabPath, content })
    });
    if (res.ok) {
      const data = await res.json();
      const model = monacoEditor.getModel();
      if (!model) return;
      if (!data.ok && data.errors && data.errors.length > 0) {
        const markers = data.errors.map(err => ({
          startLineNumber: err.line,
          startColumn: err.column,
          endLineNumber: err.line,
          endColumn: err.column + 10,
          message: err.message,
          severity: monaco.MarkerSeverity.Error
        }));
        monaco.editor.setModelMarkers(model, 'glm-syntax', markers);
      } else {
        monaco.editor.setModelMarkers(model, 'glm-syntax', []);
      }
      if (activeTabPath.endsWith('.py')) {
        const typeResponse = await fetch(`${CORE_URL}/api/language/type-diagnostics`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: activeTabPath })
        });
        if (typeResponse.ok) {
          const typeData = await typeResponse.json();
          const typeMarkers = (typeData.diagnostics || []).map(error => ({
            startLineNumber: error.line, startColumn: error.column,
            endLineNumber: error.line, endColumn: error.column + 1,
            message: `[Pyright] ${error.message}`,
            severity: error.severity === 'warning' ? monaco.MarkerSeverity.Warning : monaco.MarkerSeverity.Error
          }));
          monaco.editor.setModelMarkers(model, 'glm-pyright', typeMarkers);
        }
      }
      refreshProblems();
    }
  } catch (e) {
    // Syntax check error ignore
  }
}

// ── Git Operations (/api/git/status & /commit) ──────────────────────────────
async function fetchGitStatus() {
  const container = document.getElementById('git-changes');
  if (!container) return;
  try {
    const res = await fetch(`${CORE_URL}/api/git/status`);
    if (res.ok) {
      const data = await res.json();
      const files = data.files || [];
      if (files.length === 0) {
        container.innerHTML = '変更なし (クリーン)';
        await fetchGitBranches();
        return;
      }
      container.innerHTML = files.map(f => `<div><label><input type="checkbox" value="${f.path}" checked> ${f.status} ${f.path}</label></div>`).join('');
      await fetchGitBranches();
    }
  } catch (e) {
    container.innerHTML = 'Git オフライン';
  }
}

async function fetchGitBranches() {
  const select = document.getElementById('git-branch-select');
  if (!select) return;
  try {
    const res = await fetch(`${CORE_URL}/api/git/branches`);
    if (!res.ok) return;
    const data = await res.json();
    const branches = data.branches || [];
    const current = data.current || '';
    select.innerHTML = branches.map(branch => `<option value="${branch}" ${branch === current ? 'selected' : ''}>${branch}</option>`).join('');
    if (!branches.length) {
      select.innerHTML = '<option value="">ブランチなし</option>';
    }
  } catch (e) {
    select.innerHTML = '<option value="">Git オフライン</option>';
  }
}

async function performGitStage() {
  const container = document.getElementById('git-changes');
  if (!container) return;
  const checked = [...container.querySelectorAll('input[type="checkbox"]:checked')].map(el => el.value);
  const paths = checked.length ? checked : (await fetch(`${CORE_URL}/api/git/status`, { headers: authHeader }).then(r => r.json()).then(d => (d.files || []).map(f => f.path)));
  try {
    const res = await fetch(`${CORE_URL}/api/git/stage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths })
    });
    const data = await res.json();
    if (data.ok) {
      showToast('Git 変更をステージしました', 'success');
      fetchGitStatus();
    } else {
      showToast(`ステージ失敗: ${data.error || 'unknown error'}`, 'error');
    }
  } catch (e) {
    showToast(`ステージ失敗: ${e.message}`, 'error');
  }
}

async function performGitCheckout() {
  const select = document.getElementById('git-branch-select');
  const branch = select ? select.value : '';
  if (!branch) { showToast('切替先ブランチを選択してください', 'warning'); return; }
  if (!confirm(`ブランチを ${branch} に切り替えますか？`)) return;
  try {
    const res = await fetch(`${CORE_URL}/api/git/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch })
    });
    const data = await res.json();
    if (data.ok) { showToast(`ブランチ切替: ${branch}`, 'success'); fetchGitStatus(); }
    else { showToast(`切替失敗: ${data.error || 'unknown error'}`, 'error'); }
  } catch (e) {
    showToast(`切替失敗: ${e.message}`, 'error');
  }
}

async function performGitPush() {
  const select = document.getElementById('git-branch-select');
  const branch = select ? select.value : '';
  if (!branch) { showToast('PUSH先ブランチを選択してください', 'warning'); return; }
  if (!confirm(`現在のブランチ ${branch} を origin に push しますか？`)) return;
  try {
    const res = await fetch(`${CORE_URL}/api/git/push`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remote: 'origin', branch })
    });
    const data = await res.json();
    if (data.ok) { showToast(`Push 成功: ${branch}`, 'success'); }
    else { showToast(`Push 失敗: ${data.error || 'unknown error'}`, 'error'); }
  } catch (e) { showToast(`Push 失敗: ${e.message}`, 'error'); }
}

async function performGitCommit() {
  const msgInput = document.getElementById('git-commit-msg');
  const message = msgInput ? msgInput.value.trim() : '';
  if (!message) {
    showToast('コミットメッセージを入力してください', 'warning');
    return;
  }
  try {
    const res = await fetch(`${CORE_URL}/api/git/commit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    });
    if (res.ok) {
      const data = await res.json();
      if (data.ok) {
        showToast('🌿 Git コミット成功', 'success');
        if (msgInput) msgInput.value = '';
        fetchGitStatus();
      } else {
        showToast(`コミットエラー: ${data.error}`, 'error');
      }
    }
  } catch (e) {
    showToast(`コミット接続エラー: ${e.message}`, 'error');
  }
}

// ── Sessions (/sessions) ─────────────────────────────────────────────────────
async function fetchSessions() {
  try {
    const res = await fetch(`${ROUTER_URL}/sessions`);
    if (res.ok) {
      const list = await res.json();
      latestSessions = Array.isArray(list) ? list : [];
      const container = document.getElementById('session-list');
      renderChatHistoryList();
      if (list.length === 0) {
        container.innerHTML = '<div class="session-item">履歴なし</div>';
        return;
      }
      container.innerHTML = list.slice(0, 15).map((s, index) => `
        <button class="session-item" data-session-index="${index}" title="${escapeHtml(s.title || '無題')}">
          <strong>${escapeHtml(s.title || '無題')}</strong><span>${escapeHtml(String(s.turns || 0))} turns</span>
        </button>
      `).join('');
      container.querySelectorAll('.session-item').forEach(item => item.addEventListener('click', () => {
        const session = latestSessions[Number(item.dataset.sessionIndex)];
        if (session?.id) loadSessionIntoChat(session.id);
      }));
    }
  } catch (e) {
    document.getElementById('session-list').innerHTML = '<div class="session-item">オフライン</div>';
  }
}

function toggleChatHistoryPopover() {
  const popover = document.getElementById('chat-history-popover');
  if (!popover) return;
  renderChatHistoryList();
  popover.classList.toggle('hidden');
}

function renderChatHistoryList() {
  const list = document.getElementById('chat-history-list');
  if (!list) return;
  if (!latestSessions.length) {
    list.innerHTML = '<button class="chat-history-item" type="button">履歴なし</button>';
    return;
  }
  list.innerHTML = latestSessions.slice(0, 12).map(session => `
    <button class="chat-history-item" type="button" data-session-id="${escapeHtml(session.id || '')}" title="${escapeHtml(session.title || '無題')}">
      <span>${escapeHtml(session.title || '無題')}</span><small>${escapeHtml(String(session.turns || 0))} turns</small>
    </button>
  `).join('');
  list.querySelectorAll('[data-session-id]').forEach(button => button.addEventListener('click', () => loadSessionIntoChat(button.dataset.sessionId)));
}

async function loadSessionIntoChat(sessionId) {
  if (!sessionId) return;
  try {
    const response = await fetch(`${ROUTER_URL}/sessions/${encodeURIComponent(sessionId)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const messages = Array.isArray(data.messages) ? data.messages : [];
    chatHistory = messages.filter(message => ['user', 'assistant', 'system'].includes(message.role) && typeof message.content === 'string').slice(-20);
    const container = document.getElementById('chat-messages');
    container.innerHTML = '';
    for (const message of chatHistory) appendMessage(message.role, message.content);
    updateContextMeter();
    document.getElementById('chat-history-popover')?.classList.add('hidden');
    showToast(`チャット履歴を復元しました: ${data.title || '無題'}`, 'success', 1800);
  } catch (error) {
    showToast(`チャット履歴を読み込めません: ${error.message}`, 'error');
  }
}

// ── Chat & Streaming ────────────────────────────────────────────────────────
function appendMessage(role, text) {
  const container = document.getElementById('chat-messages');
  const msgDiv = document.createElement('div');
  msgDiv.className = `message ${role}`;
  
  const senderDiv = document.createElement('div');
  senderDiv.className = `sender sender-${role}`;
  senderDiv.textContent = role === 'user' ? 'あなた' : (role === 'assistant' ? 'GLM' : 'システム');

  const metaDiv = document.createElement('div');
  metaDiv.className = 'message-meta';
  metaDiv.textContent = role === 'user' ? 'あなたの指示' : (role === 'assistant' ? 'ローカルAI応答' : 'システム通知');

  const contentDiv = document.createElement('div');
  contentDiv.className = 'content';
  contentDiv.textContent = text;

  msgDiv.appendChild(senderDiv);
  msgDiv.appendChild(metaDiv);
  msgDiv.appendChild(contentDiv);
  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
  return contentDiv;
}

// ── 軽量マークダウン描画（コードブロック/インライン/見出し/リスト）─────────
function renderMarkdown(target, text) {
  target.innerHTML = '';
  const blocks = [];
  // コードブロックを先に分離
  const placeholder = text.replace(/```(\w*)\n?([\s\S]*?)(?:```|$)/g, (m, lang, code) => {
    blocks.push({ lang: lang || 'text', code: code.replace(/\n$/, '') });
    return `\u0000CB${blocks.length - 1}\u0000`;
  });
  const inline = (s) => escapeHtml(s)
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  const lines = placeholder.split('\n');
  let html = '';
  let inList = null;
  for (const line of lines) {
    const cbMatch = line.match(/^\u0000CB(\d+)\u0000\s*$/);
    if (cbMatch) {
      if (inList) { html += `</${inList}>`; inList = null; }
      const block = blocks[Number(cbMatch[1])];
      html += `<div class="code-block"><div class="code-block-header"><span>${escapeHtml(block.lang)}</span>
        <span class="code-block-actions">
        <button data-cb-act="copy" data-cb="${cbMatch[1]}" title="コピー">コピー</button>
        <button data-cb-act="apply" data-cb="${cbMatch[1]}" title="エディタへ挿入">適用</button>
        </span></div><pre><code>${escapeHtml(block.code)}</code></pre></div>`;
      continue;
    }
    if (/^###\s/.test(line)) { if (inList) { html += `</${inList}>`; inList = null; } html += `<h3>${inline(line.replace(/^###\s*/, ''))}</h3>`; continue; }
    if (/^##\s/.test(line)) { if (inList) { html += `</${inList}>`; inList = null; } html += `<h2>${inline(line.replace(/^##\s*/, ''))}</h2>`; continue; }
    if (/^#\s/.test(line)) { if (inList) { html += `</${inList}>`; inList = null; } html += `<h1>${inline(line.replace(/^#\s*/, ''))}</h1>`; continue; }
    if (/^\s*[-*]\s+/.test(line)) {
      if (inList !== 'ul') { if (inList) html += `</${inList}>`; html += '<ul>'; inList = 'ul'; }
      html += `<li>${inline(line.replace(/^\s*[-*]\s+/, ''))}</li>`; continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      if (inList !== 'ol') { if (inList) html += `</${inList}>`; html += '<ol>'; inList = 'ol'; }
      html += `<li>${inline(line.replace(/^\s*\d+\.\s+/, ''))}</li>`; continue;
    }
    if (inList) { html += `</${inList}>`; inList = null; }
    if (line.trim() === '') { html += ''; continue; }
    html += `<p>${inline(line)}</p>`;
  }
  if (inList) html += `</${inList}>`;
  target.innerHTML = `<div class="msg-md">${html}</div>`;
  // コードブロックのアクション
  target.querySelectorAll('[data-cb-act]').forEach(btn => {
    btn.addEventListener('click', () => {
      const block = blocks[Number(btn.getAttribute('data-cb'))];
      if (!block) return;
      if (btn.getAttribute('data-cb-act') === 'copy') {
        copyText(block.code).then(() => showToast('コードをコピーしました', 'success', 1500));
      } else if (btn.getAttribute('data-cb-act') === 'apply') {
        if (monacoEditor) {
          const sel = monacoEditor.getSelection();
          monacoEditor.executeEdits('chat-apply', [{ range: sel, text: block.code }]);
          showToast('エディタへ挿入しました', 'success', 1500);
        } else {
          showToast('エディタが開いていません', 'warning');
        }
      }
    });
  });
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
  }
}

// ── アシスタントメッセージのアクションバー ───────────────────────────────
function attachAssistantActions(msgDiv, contentDiv, getText) {
  const actions = document.createElement('div');
  actions.className = 'msg-actions';
  const mk = (label, title, onClick, cls = '') => {
    const b = document.createElement('button');
    b.className = `msg-action ${cls}`;
    b.textContent = label;
    b.title = title;
    b.addEventListener('click', () => onClick(b));
    return b;
  };
  const copyButton = mk('', 'コピー', async (b) => {
    await copyText(getText());
    b.classList.add('copied'); b.textContent = '✓';
    setTimeout(() => { b.classList.remove('copied'); applyUiIcon(b, 'copy'); }, 1200);
  }, 'icon-button');
  actions.appendChild(copyButton);
  applyUiIcon(copyButton, 'copy');
  actions.appendChild(mk('', '再生成', () => regenerateLastResponse(), 'icon-button'));
  applyUiIcon(actions.lastChild, 'refresh');
  const up = mk('', '良い応答', (b) => {
    const on = b.classList.toggle('active-up');
    down.classList.remove('active-down');
    sendFeedback(on ? 'up' : null, getText());
  }, 'icon-button');
  applyUiIcon(up, 'thumbsUp');
  const down = mk('', '悪い応答', (b) => {
    const on = b.classList.toggle('active-down');
    up.classList.remove('active-up');
    sendFeedback(on ? 'down' : null, getText());
  }, 'icon-button');
  applyUiIcon(down, 'thumbsDown');
  actions.appendChild(up);
  actions.appendChild(down);
  msgDiv.appendChild(actions);
}

function sendFeedback(rating, text) {
  if (!rating) return;
  fetch(`${CORE_URL}/api/feedback`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
    body: JSON.stringify({ rating, text: String(text).slice(0, 500), session_id: agentSessionId })
  }).catch(() => {});
}

function regenerateLastResponse() {
  if (isGenerating) return;
  const lastUser = [...chatHistory].reverse().find(m => m.role === 'user');
  if (!lastUser) { showToast('再生成する質問がありません', 'warning'); return; }
  sendChatMessage(lastUser.content);
}

// ── タイピングインジケーター ──────────────────────────────────────────────
function appendTypingMessage() {
  const container = document.getElementById('chat-messages');
  const msgDiv = document.createElement('div');
  msgDiv.className = 'message assistant';
  const senderDiv = document.createElement('div');
  senderDiv.className = 'sender';
  senderDiv.textContent = 'GLM';
  const contentDiv = document.createElement('div');
  contentDiv.className = 'content';
  contentDiv.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
  msgDiv.appendChild(senderDiv);
  msgDiv.appendChild(contentDiv);
  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
  return { msgDiv, contentDiv };
}

// ── Agentツール呼び出しカード（toolCallsView）───────────────────────────
function renderToolTrace(trace) {
  if (!trace || !trace.length) return;
  const container = document.getElementById('chat-messages');
  const wrap = document.createElement('div');
  wrap.className = 'message assistant';
  const senderDiv = document.createElement('div');
  senderDiv.className = 'sender';
  senderDiv.textContent = 'エージェントのツール実行';
  const list = document.createElement('div');
  trace.forEach(item => {
    const card = document.createElement('div');
    card.className = 'tool-call-card' + (item.is_error ? ' is-error' : '');
    const head = document.createElement('div');
    head.className = 'tool-head';
    head.innerHTML = `<span class="tool-badge">#${item.step}</span><span class="tool-icon">${UI_ICONS.tool}</span><span>${escapeHtml(item.tool)}</span><span class="tool-chevron">▸</span>`;
    const body = document.createElement('div');
    body.className = 'tool-body';
    body.textContent = String(item.result ?? '（結果なし）');
    head.addEventListener('click', () => card.classList.toggle('open'));
    card.appendChild(head);
    card.appendChild(body);
    list.appendChild(card);
  });
  wrap.appendChild(senderDiv);
  wrap.appendChild(list);
  container.appendChild(wrap);
  container.scrollTop = container.scrollHeight;
}

// ── コンテキスト使用量メーター ────────────────────────────────────────────
function updateContextMeter() {
  const chars = chatHistory.reduce((sum, m) => sum + (m.content || '').length, 0);
  const approxTokens = Math.round(chars / 2);
  const maxTokens = 22000; // RTX3070 8GB快適上限
  const pct = Math.min(100, Math.round(approxTokens / maxTokens * 100));
  const fill = document.getElementById('ctx-meter-fill');
  const label = document.getElementById('ctx-meter-label');
  if (fill) {
    fill.style.width = pct + '%';
    fill.style.background = pct > 85 ? 'var(--accent-red)' : (pct > 60 ? 'var(--accent-yellow)' : 'var(--accent-green)');
  }
  if (label) label.textContent = pct + '%';
}

function updateSendButton() {
  const btn = document.getElementById('btn-send');
  if (!btn) return;
  btn.disabled = isGenerating;
  if (isGenerating) btn.innerHTML = '<span class="loader-dot"></span>';
  else applyUiIcon(btn, 'send', '送信');
}

// ── チャット送信 ──────────────────────────────────────────────────────────
async function sendChatMessage(prompt) {
  const selectedRole = document.getElementById('chat-role')?.value || 'user';
  const message = { role: selectedRole, content: prompt };
  appendMessage(selectedRole, prompt);
  chatHistory.push(message);
  lastChatRequest = { prompt, role: selectedRole };
  if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);
  updateContextMeter();

  const chatMode = document.getElementById('chat-mode')?.value || 'chat';
  if (chatMode === 'agent') return sendAgentMessage(prompt);

  const { msgDiv, contentDiv: assistantContentEl } = appendTypingMessage();
  isGenerating = true;
  updateSendButton();

  try {
    const res = await fetch(`${ROUTER_URL}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ messages: chatHistory, stream: true,
        provider: document.getElementById('provider-select')?.value || undefined,
        model: document.getElementById('provider-model')?.value || undefined })
    });

    if (!res.ok) {
      assistantContentEl.textContent = `エラー: HTTP ${res.status}`;
      showToast(`AI生成リクエストエラー: HTTP ${res.status}`, 'error');
      isGenerating = false;
      updateSendButton();
      return '';
    }

    if (!res.body) throw new Error('ストリーム本文がありません');
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let responseText = '';
    let pendingLine = '';
    let usage = null;
    assistantContentEl.textContent = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      const lines = (pendingLine + chunk).split('\n');
      pendingLine = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim();
          if (dataStr === '[DONE]') continue;
          try {
            const json = JSON.parse(dataStr);
            const choice = json.choices?.[0] || {};
            const content = choice.delta?.content || choice.message?.content || json.delta?.text || '';
            responseText += content;
            usage = json.usage || usage;
            assistantContentEl.textContent = responseText;
          } catch (e) {}
        }
      }
    }

    if (pendingLine.startsWith('data:')) {
      try {
        const json = JSON.parse(pendingLine.slice(5).trim());
        responseText += json.choices?.[0]?.delta?.content || json.choices?.[0]?.message?.content || '';
        usage = json.usage || usage;
      } catch (e) {}
    }

    if (!responseText) {
      responseText = assistantContentEl.textContent || '応答が空でした。';
    }
    renderMarkdown(assistantContentEl, responseText);
    attachAssistantActions(msgDiv, assistantContentEl, () => responseText);
    chatHistory.push({ role: 'assistant', content: responseText });
    if (usage) {
      const meta = document.createElement('div');
      meta.className = 'message-meta';
      meta.textContent = `応答完了 · ${usage.total_tokens || usage.completion_tokens || '?'} トークン`;
      msgDiv.appendChild(meta);
    }
    updateContextMeter();
    return responseText;
  } catch (e) {
    assistantContentEl.textContent = `接続エラー: ${e.message}`;
    return '';
  } finally {
    isGenerating = false;
    updateSendButton();
  }
}

async function sendAgentMessage(prompt) {
  const { msgDiv, contentDiv: assistantContentEl } = appendTypingMessage();
  const status = document.getElementById('agent-status');
  const stopBtn = document.getElementById('btn-agent-stop');
  if (status) { status.textContent = '実行中'; status.classList.add('running'); status.classList.remove('error'); }
  if (stopBtn) stopBtn.classList.remove('hidden');
  isGenerating = true;
  updateSendButton();
  try {
    const model = document.getElementById('agent-model-select')?.value || 'auto';
    const res = await fetch(`${CORE_URL}/api/agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ messages: chatHistory, requested_by: 'standalone-ui', max_steps: 8, max_seconds: 180, session_id: agentSessionId, model })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || data.reason || `HTTP ${res.status}`);
    const answer = data.message?.content || 'エージェントの応答が空でした。';
    renderMarkdown(assistantContentEl, answer);
    attachAssistantActions(msgDiv, assistantContentEl, () => answer);
    chatHistory.push({ role: 'assistant', content: answer });
    updateContextMeter();
    renderToolTrace(data.trace);
    if (status) status.textContent = `完了（${data.steps || 0} ステップ）`;
    return answer;
  } catch (error) {
    assistantContentEl.textContent = `エージェントエラー: ${error.message}`;
    if (status) { status.textContent = 'エラー'; status.classList.add('error'); status.classList.remove('running'); }
    return '';
  } finally {
    isGenerating = false;
    updateSendButton();
    if (stopBtn) stopBtn.classList.add('hidden');
    if (status && status.textContent === '実行中') status.textContent = '待機中';
  }
}

async function stopAgent() {
  try {
    const res = await fetch(`${CORE_URL}/api/agent/cancel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ session_id: agentSessionId })
    });
    const data = await res.json();
    if (data.ok) {
      showToast('Agentへ停止シグナルを送信しました', 'warning');
      const status = document.getElementById('agent-status');
      if (status) status.textContent = '停止要求中';
    } else {
      showToast(`Agent停止失敗: ${data.error || 'unknown'}`, 'error');
    }
  } catch (error) {
    showToast(`Agent停止失敗: ${error.message}`, 'error');
  }
}

function clearChat() {
  chatHistory = [];
  lastChatRequest = null;
  document.getElementById('chat-messages').innerHTML = `
    <div class="message system">
      <div class="sender">GLM System</div>
      <div class="content">会話履歴をクリアしました。</div>
    </div>
  `;
}

function runDoctor() {
  appendMessage('system', '診断コマンドを実行中...');
  window.open(`${ROUTER_URL}/status`, '_blank');
}

// ── Workspace Files (/api/workspace/files & /read) ──────────────────────────
async function fetchWorkspaceFiles() {
  const treeEl = document.getElementById('file-tree');
  try {
    const res = await fetch(`${CORE_URL}/api/workspace/files`);
    if (res.ok) {
      const data = await res.json();
      const files = data.files || [];
      workspaceFiles = files;
      if (files.length === 0) {
        treeEl.innerHTML = '<div class="tree-item">ファイルなし</div>';
        return;
      }
      renderExplorerTree(treeEl, files);
    }
  } catch (e) {
    // Daemon offline — fallback to static tree
  }
}

function renderExplorerTree(treeEl, files) {
  const root = { folders: new Map(), files: [] };
  for (const file of files) {
    const parts = file.split('/').filter(Boolean);
    let node = root;
    parts.forEach((part, index) => {
      const last = index === parts.length - 1;
      if (last) node.files.push({ name: part, path: file });
      else {
        if (!node.folders.has(part)) node.folders.set(part, { folders: new Map(), files: [] });
        node = node.folders.get(part);
      }
    });
  }
  const extOf = name => (name.includes('.') ? name.split('.').pop().toLowerCase() : '');
  const renderNode = (node, depth = 0) => {
    const folders = [...node.folders.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    const entries = [...node.files].sort((a, b) => a.name.localeCompare(b.name));
    return folders.map(([name, child]) => {
      const key = `folder:${depth}:${name}`;
      return `<div class="tree-node" data-tree-key="${escapeHtml(key)}">
        <div class="tree-item tree-folder" role="treeitem" tabindex="0" data-folder="${escapeHtml(name)}"><span class="tree-arrow">▸</span><span class="tree-icon">${UI_ICONS.explorer}</span><span class="tree-label">${escapeHtml(name)}</span></div>
        <div class="tree-children collapsed">${renderNode(child, depth + 1)}</div>
      </div>`;
    }).join('') + entries.map(item => {
      const ext = extOf(item.name);
      return `<div class="tree-item tree-file" role="treeitem" tabindex="0" data-path="${escapeHtml(item.path)}" data-ext="${escapeHtml(ext)}" style="padding-left:${12 + depth * 16}px"><span class="tree-arrow"></span><span class="tree-icon">${fileGlyph(ext)}</span><span class="tree-label">${escapeHtml(item.name)}</span></div>`;
    }).join('');
  };
  treeEl.setAttribute('role', 'tree');
  treeEl.innerHTML = renderNode(root) || '<div class="tree-item">ファイルなし</div>';
  treeEl.querySelectorAll('.tree-file').forEach(item => {
    const open = () => {
      const path = item.dataset.path;
      openFileInEditor(path);
      treeEl.querySelectorAll('.tree-file').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
    };
    item.addEventListener('click', open);
    item.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
    item.addEventListener('contextmenu', event => showTreeContextMenu(event, item.dataset.path));
  });
  treeEl.querySelectorAll('.tree-folder').forEach(item => {
    const toggle = () => {
      const children = item.parentElement.querySelector(':scope > .tree-children');
      const collapsed = children.classList.toggle('collapsed');
      item.querySelector('.tree-arrow').textContent = collapsed ? '▸' : '▾';
    };
    item.addEventListener('click', toggle);
    item.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } });
    item.addEventListener('contextmenu', event => { event.preventDefault(); showTreeContextMenu(event, item.dataset.folder, true); });
  });
}

function fileGlyph(ext) {
  if (ext === 'json') return UI_ICONS.braces;
  if (ext === 'md') return UI_ICONS.markdown;
  if (['py', 'js', 'ts', 'html', 'css', 'cpp', 'c', 'java', 'ps1', 'sh', 'sql'].includes(ext)) return UI_ICONS.code;
  return UI_ICONS.file;
}

function showTreeContextMenu(event, path, folder = false) {
  document.querySelector('.tree-context-menu')?.remove();
  const menu = document.createElement('div');
  menu.className = 'tree-context-menu';
  const actions = folder ? [['new-file-here', '新しいファイル'], ['new-folder-here', '新しいフォルダー'], ['rename-folder', '名前の変更']] : [['open-file', '開く'], ['rename-file', '名前の変更'], ['delete-file', '削除']];
  menu.innerHTML = actions.map(([action, label]) => `<button type="button" data-action="${action}">${label}</button>`).join('');
  menu.style.left = `${Math.min(event.clientX, window.innerWidth - 190)}px`;
  menu.style.top = `${Math.min(event.clientY, window.innerHeight - actions.length * 34)}px`;
  document.body.appendChild(menu);
  menu.querySelectorAll('button').forEach(button => button.addEventListener('click', async () => {
    menu.remove();
    const action = button.dataset.action;
    if (action === 'open-file') return openFileInEditor(path);
    if (action === 'delete-file') return deleteWorkspaceEntry(path);
    if (action === 'rename-file' || action === 'rename-folder') return renameWorkspaceEntry(path);
    if (action === 'new-file-here') return createWorkspaceFile(path);
    if (action === 'new-folder-here') return createWorkspaceFolder(path);
  }));
  setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
}

async function openFileInEditor(relPath) {
  currentActivePath = relPath;
  activeTabPath = relPath;
  document.getElementById('current-filename').textContent = relPath;
  
  const ipynbPanel = document.getElementById('ipynb-container');
  const editorPanel = document.getElementById('editor-container');

  if (relPath.endsWith('.ipynb')) {
    openIpynbFile(relPath);
    return;
  } else if (ipynbPanel && editorPanel) {
    editorPanel.style.display = 'block';
    ipynbPanel.classList.add('hidden');
  }

  try {
    const res = await fetch(`${CORE_URL}/api/workspace/read`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: relPath })
    });
    if (res.ok) {
      const data = await res.json();
      const content = data.content || '';
      const ext = relPath.split('.').pop().toLowerCase();
      const langMap = {
        py: 'python', json: 'json', js: 'javascript', ts: 'typescript',
        md: 'markdown', html: 'html', css: 'css', cpp: 'cpp', c: 'cpp',
        java: 'java', ps1: 'powershell', sh: 'shell', xml: 'xml', sql: 'sql'
      };
      const language = langMap[ext] || 'plaintext';

      const existing = openTabs.find(tab => tab.path === relPath);
      if (existing) {
        existing.content = content;
        existing.language = language;
      } else {
        openTabs.push({ path: relPath, content, language, isDirty: false });
      }
      activeTabPath = relPath;
      renderTabs();

      if (monacoEditor) {
        monaco.editor.setModelLanguage(monacoEditor.getModel(), language);
        monacoEditor.setValue(content);
      }
    }
  } catch (e) {
    console.error('Failed to open file:', e);
  }
}

function renderTabs() {
  const tabBar = document.getElementById('tab-bar');
  if (!tabBar) return;
  tabBar.innerHTML = openTabs.map(tab => {
    const filename = tab.path.split('/').pop();
    const active = tab.path === activeTabPath ? 'active' : '';
    return `<div class="tab ${active}" data-path="${tab.path}"><span>${filename}</span><span class="tab-close" data-close="${tab.path}">x</span></div>`;
  }).join('');
  tabBar.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', event => {
    const closePath = event.target.getAttribute('data-close');
    if (closePath) {
      event.stopPropagation();
      openTabs = openTabs.filter(item => item.path !== closePath);
      if (activeTabPath === closePath) {
        activeTabPath = openTabs.length ? openTabs[openTabs.length - 1].path : '';
        if (activeTabPath) openFileInEditor(activeTabPath);
        else if (monacoEditor) monacoEditor.setValue('');
      }
      renderTabs();
      return;
    }
    openFileInEditor(tab.getAttribute('data-path'));
  }));
}

async function saveActiveFile() {
  if (!currentActivePath || !monacoEditor) {
    showToast('保存対象のファイルが開かれていません', 'warning');
    return;
  }
  const content = monacoEditor.getValue();
  try {
    const response = await fetch(`${CORE_URL}/api/workspace/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ path: currentActivePath, content })
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const activeTab = openTabs.find(tab => tab.path === currentActivePath);
    if (activeTab) activeTab.content = content;
    showToast(`保存完了: ${currentActivePath}`, 'success');
  } catch (error) {
    showToast(`保存エラー: ${error.message}`, 'error');
  }
}

async function runActiveFile() {
  if (!currentActivePath) {
    showToast('実行対象のファイルが開かれていません', 'warning');
    return;
  }
  const outText = document.getElementById('output-text');
  if (outText) outText.textContent = `▶ 実行中... (${currentActivePath})\n`;
  showToast(`▶ 実行開始: ${currentActivePath}`, 'info');

  try {
    const res = await fetch(`${CORE_URL}/api/workspace/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ path: currentActivePath })
    });
    if (res.ok) {
      const data = await res.json();
      if (data.ok) {
        if (outText) outText.textContent = data.stdout || '(出力なし)';
        showToast('実行成功', 'success');
      } else {
        if (outText) outText.textContent = data.error || data.stderr || 'エラー発生';
        showToast('実行エラー', 'error');
      }
    } else {
      if (outText) outText.textContent = `サーバーエラー: HTTP ${res.status}`;
    }
  } catch (e) {
    if (outText) outText.textContent = `接続エラー: ${e.message}`;
  }
}

async function startDebugSession() {
  if (!currentActivePath || !currentActivePath.endsWith('.py')) {
    showToast('Pythonファイルを開いてください', 'warning');
    return;
  }
  const outText = document.getElementById('output-text');
  try {
    const res = await fetch(`${CORE_URL}/api/dap/launch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ path: currentActivePath, wait_for_client: true })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (outText) outText.textContent = `DAP待受中\n${data.host}:${data.port}\nPID: ${data.pid}\nDAPクライアントから接続してください。\nブレークポイント操作は接続したDAPクライアントで行えます。`;
    debugLog(`DAP待受開始: ${data.host}:${data.port} (PID: ${data.pid})`);
    switchBottomTab('debug');
    showToast(`デバッグ待受開始: ${data.port}`, 'success');
  } catch (error) {
    showToast(`デバッグ開始失敗: ${error.message}`, 'error');
  }
}

async function reviewSelectedCode() {
  if (!monacoEditor || !currentActivePath) { showToast('レビュー対象のファイルを開いてください', 'warning'); return; }
  const selection = monacoEditor.getSelection();
  const selected = monacoEditor.getModel().getValueInRange(selection).slice(0, 8000);
  if (!selected.trim()) { showToast('コードを選択してください', 'warning'); return; }
  sendChatMessage(`次のコードだけをレビューしてください。重大な問題、修正案、テスト案を簡潔に示してください。\nファイル: ${currentActivePath}\n\n\
${selected}`);
}

async function suggestCommitMessage() {
  try {
    const res = await fetch(`${CORE_URL}/api/git/diff`);
    const data = await res.json();
    const diff = (data.diff || '').slice(0, 12000);
    if (!diff.trim()) { showToast('コミット対象の差分がありません', 'warning'); return; }
    const suggestion = await sendChatMessage(`次のGit差分から、短い日本語のコミットメッセージを1つだけ提案してください。説明や箇条書きは不要です。\n\n${diff}`);
    if (suggestion) document.getElementById('git-commit-msg').value = suggestion.split('\n')[0].replace(/^[-*#` ]+/, '').trim();
  } catch (error) { showToast(`差分取得失敗: ${error.message}`, 'error'); }
}

async function applyRenameAtCursor() {
  if (!pendingRename || !pendingRename.edits.length) { showToast('先にリネーム案を作成してください', 'warning'); return; }
  if (!confirm(`${pendingRename.name} を ${pendingRename.newName} に ${pendingRename.edits.length} 箇所変更しますか？`)) return;
  const grouped = {};
  pendingRename.edits.forEach(edit => { (grouped[edit.path] ||= []).push(edit); });
  try {
    for (const path of Object.keys(grouped)) {
      const response = await fetch(`${CORE_URL}/api/workspace/read`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path })
      });
      const file = await response.json();
      if (!response.ok || typeof file.content !== 'string') throw new Error(file.error || path);
      const updated = file.content.replace(new RegExp(`\\b${pendingRename.name}\\b`, 'g'), pendingRename.newName);
      const saved = await fetch(`${CORE_URL}/api/workspace/save`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: JSON.stringify({ path, content: updated })
      });
      if (!saved.ok) throw new Error(`保存失敗: ${path}`);
      if (path === currentActivePath && monacoEditor) monacoEditor.setValue(updated);
    }
    pendingRename = null;
    showToast('リネームを適用しました', 'success');
    fetchWorkspaceFiles();
  } catch (error) { showToast(`リネーム適用失敗: ${error.message}`, 'error'); }
}

async function stopDebugSession() {
  try {
    const res = await fetch(`${CORE_URL}/api/dap/stop`, { method: 'POST', headers: authHeader });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const outText = document.getElementById('output-text');
    if (outText) outText.textContent = 'デバッグセッションを停止しました。';
    debugLog('デバッグセッションを停止しました。');
    showToast('デバッグ停止', 'info');
  } catch (error) {
    showToast(`デバッグ停止失敗: ${error.message}`, 'error');
  }
}

async function dapCommand(endpoint, body = {}) {
  try {
    const res = await fetch(`${CORE_URL}/api/dap/${endpoint}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: JSON.stringify(body)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    debugLog(JSON.stringify(data.body || data.breakpoints || data, null, 2));
    return data;
  } catch (error) { showToast(`DAP操作失敗: ${error.message}`, 'error'); return null; }
}

async function setDebugBreakpoint() {
  const line = Number(document.getElementById('debug-breakpoint-line').value);
  if (!currentActivePath || !line) { showToast('Pythonファイルと行番号を指定してください', 'warning'); return; }
  const data = await dapCommand('breakpoints', { path: currentActivePath, lines: [line] });
  if (data) showToast(`ブレークポイント設定: ${line}行`, 'success');
}

async function inspectDebugState() {
  const eventResponse = await fetch(`${CORE_URL}/api/dap/events`);
  const eventData = await eventResponse.json();
  const stopped = (eventData.events || []).find(event => event.event === 'stopped');
  const threads = await dapCommand('threads');
  const thread = threads && threads.body && threads.body.threads && threads.body.threads.find(item => item.id === (stopped && stopped.body.threadId)) ||
    (threads && threads.body && threads.body.threads && threads.body.threads[0]);
  if (!thread) { showToast('デバッグスレッドがありません', 'warning'); return; }
  const stack = await dapCommand('stack-trace', { threadId: thread.id });
  const frame = stack && stack.body && stack.body.stackFrames && stack.body.stackFrames[0];
  if (!frame || !frame.id) return;
  const scopes = await dapCommand('scopes', { frameId: frame.id });
  const locals = scopes && scopes.body && scopes.body.scopes && scopes.body.scopes.find(scope => /local/i.test(scope.name));
  if (locals && locals.variablesReference) {
    await dapCommand('variables', { variablesReference: locals.variablesReference });
  }
}

function sftpPayload() {
  return {
    host: document.getElementById('sftp-host').value.trim(),
    user: document.getElementById('sftp-user').value.trim() || null,
    port: Number(document.getElementById('sftp-port').value || 22),
    remote_path: document.getElementById('sftp-remote-path').value.trim()
  };
}

async function fetchSftpProfiles() {
  try {
    const res = await fetch(`${CORE_URL}/api/sftp/profiles`);
    const data = await res.json();
    if (!res.ok || !data.ok) return;
    const select = document.getElementById('sftp-profile');
    if (!select) return;
    select.innerHTML = '<option value="">プロファイルなし</option>';
    (data.profiles || []).forEach(profile => {
      const option = document.createElement('option');
      option.value = profile.name;
      option.textContent = profile.name;
      select.appendChild(option);
    });
  } catch (error) {}
}

async function saveSftpProfile() {
  const payload = sftpPayload();
  payload.name = document.getElementById('sftp-profile-name').value.trim();
  if (!payload.name) { showToast('プロファイル名を入力してください', 'warning'); return; }
  try {
    const res = await fetch(`${CORE_URL}/api/sftp/profile/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await fetchSftpProfiles();
    document.getElementById('sftp-profile').value = payload.name;
    showToast('SFTPプロファイルを保存しました', 'success');
  } catch (error) { showToast(`プロファイル保存失敗: ${error.message}`, 'error'); }
}

async function deleteSftpProfile() {
  const name = document.getElementById('sftp-profile').value;
  if (!name) { showToast('削除するプロファイルを選択してください', 'warning'); return; }
  try {
    const res = await fetch(`${CORE_URL}/api/sftp/profile/delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await fetchSftpProfiles();
    showToast('SFTPプロファイルを削除しました', 'info');
  } catch (error) { showToast(`プロファイル削除失敗: ${error.message}`, 'error'); }
}

async function loadSftpProfile(event) {
  const name = event.target.value;
  if (!name) return;
  try {
    const res = await fetch(`${CORE_URL}/api/sftp/profiles`);
    const data = await res.json();
    const profile = (data.profiles || []).find(item => item.name === name);
    if (!profile) return;
    document.getElementById('sftp-profile-name').value = profile.name;
    document.getElementById('sftp-host').value = profile.host;
    document.getElementById('sftp-user').value = profile.user || '';
    document.getElementById('sftp-port').value = profile.port;
    document.getElementById('sftp-remote-path').value = profile.remote_path || '.';
  } catch (error) {}
}

function showSftpOutput(text) {
  const output = document.getElementById('sftp-output');
  if (output) output.textContent = text;
}

async function listSftpRemote() {
  const payload = sftpPayload();
  if (!payload.remote_path) payload.remote_path = '.';
  try {
    const res = await fetch(`${CORE_URL}/api/sftp/list`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    showSftpOutput(data.entries.join('\n') || '(空)');
  } catch (error) {
    showSftpOutput(`SFTPエラー: ${error.message}`);
  }
}

async function testSftpConnection() {
  const payload = sftpPayload();
  try {
    const res = await fetch(`${CORE_URL}/api/sftp/test`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || data.stderr || `HTTP ${res.status}`);
    showSftpOutput(data.stdout || '接続成功');
    showToast('SFTP接続成功', 'success');
  } catch (error) {
    showSftpOutput(`SFTP接続エラー: ${error.message}`);
    showToast('SFTP接続失敗', 'error');
  }
}

async function uploadSftpActiveFile() {
  if (!currentActivePath) { showToast('アップロードするファイルを開いてください', 'warning'); return; }
  const payload = sftpPayload();
  if (!payload.remote_path) { showToast('リモートパスを入力してください', 'warning'); return; }
  payload.local_path = currentActivePath;
  try {
    const res = await fetch(`${CORE_URL}/api/sftp/upload`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    showSftpOutput(data.stdout || 'アップロード完了');
    showToast('SFTPアップロード完了', 'success');
  } catch (error) {
    showSftpOutput(`SFTPエラー: ${error.message}`);
  }
}

async function downloadSftpFile() {
  const payload = sftpPayload();
  payload.local_path = document.getElementById('sftp-local-path').value.trim();
  if (!payload.remote_path || !payload.local_path) { showToast('リモートパスとローカルパスを入力してください', 'warning'); return; }
  try {
    const res = await fetch(`${CORE_URL}/api/sftp/download`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader }, body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    showSftpOutput(data.stdout || 'ダウンロード完了');
    showToast('SFTPダウンロード完了', 'success');
    await fetchWorkspaceFiles();
  } catch (error) {
    showSftpOutput(`SFTPエラー: ${error.message}`);
  }
}

async function openIpynbFile(relPath) {
  const ipynbPanel = document.getElementById('ipynb-container');
  const editorPanel = document.getElementById('editor-container');
  if (!ipynbPanel || !editorPanel) return;

  try {
    const res = await fetch(`${CORE_URL}/api/workspace/ipynb`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ path: relPath })
    });
    if (res.ok) {
      const data = await res.json();
      if (data.ok && data.cells) {
        editorPanel.style.display = 'none';
        ipynbPanel.classList.remove('hidden');
        ipynbPanel.innerHTML = data.cells.map((cell, idx) => `
          <div class="ipynb-cell ${cell.cell_type}">
            <div style="font-size:10px; color:var(--text-muted); margin-bottom:4px;">[${cell.cell_type.toUpperCase()} Cell #${idx + 1}]</div>
            <div>${escapeHtml(cell.source)}</div>
          </div>
        `).join('');
        return;
      }
    }
  } catch (e) {}
  editorPanel.style.display = 'block';
  ipynbPanel.classList.add('hidden');
}

function escapeHtml(str) {
  return (str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function goToDefinitionAtCursor() {
  if (!activeTabPath || !monacoEditor) {
    showToast('定義ジャンプ先がありません。ファイルを開いてください。', 'warning');
    return;
  }
  const model = monacoEditor.getModel();
  const pos = monacoEditor.getPosition();
  const word = model.getWordAtPosition(pos);
  const name = word ? word.word : '';
  if (!name) {
    showToast('カーソル位置にシンボルがありません', 'warning');
    return;
  }
  // 本格LSP (pyright-langserver) を優先
  try {
    const lspRes = await fetch(`${CORE_URL}/api/lsp/definition`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: activeTabPath, line: pos.lineNumber, character: pos.column, content: model.getValue() })
    });
    const lspData = await lspRes.json();
    const locations = lspData.locations || [];
    if (lspData.ok && locations.length) {
      const target = locations[0];
      await openFileInEditor(target.path || activeTabPath);
      if (monacoEditor) {
        monacoEditor.setPosition({ lineNumber: Number(target.line || 1), column: Number(target.column || 1) });
        monacoEditor.revealLineInCenter({ lineNumber: Number(target.line || 1), column: Number(target.column || 1) });
      }
      showToast(`定義へ移動 (LSP): ${name}`, 'success');
      return;
    }
  } catch (e) { /* LSP unavailable → AST fallback */ }
  try {
    const res = await fetch(`${CORE_URL}/api/workspace/definitions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: activeTabPath, name, content: monacoEditor.getValue() })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const definitions = data.definitions || [];
    if (!definitions.length) {
      showToast(`定義が見つかりません: ${name}`, 'warning');
      return;
    }
    const target = definitions[0];
    await openFileInEditor(target.path || activeTabPath);
    if (monacoEditor) {
      monacoEditor.setPosition({ lineNumber: Number(target.line || 1), column: Number(target.column || 1) });
      monacoEditor.revealLineInCenter({ lineNumber: Number(target.line || 1), column: Number(target.column || 1) });
    }
    showToast(`定義へ移動: ${name}`, 'success');
  } catch (error) {
    showToast(`定義ジャンプ失敗: ${error.message}`, 'error');
  }
}

function cursorSymbol() {
  if (!activeTabPath || !monacoEditor) return '';
  const word = monacoEditor.getModel().getWordAtPosition(monacoEditor.getPosition());
  return word ? word.word : '';
}

async function findReferencesAtCursor() {
  const name = cursorSymbol();
  if (!name) { showToast('カーソル位置にシンボルがありません', 'warning'); return; }
  try {
    const res = await fetch(`${CORE_URL}/api/language/references`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: activeTabPath, name })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    showSftpOutput((data.references || []).map(item => `${item.path}:${item.line}:${item.column}`).join('\n') || '参照なし');
    showToast(`参照 ${data.references.length} 件`, 'success');
  } catch (error) {
    showToast(`参照検索失敗: ${error.message}`, 'error');
  }
}

async function proposeRenameAtCursor() {
  const name = cursorSymbol();
  if (!name) { showToast('カーソル位置にシンボルがありません', 'warning'); return; }
  const newName = window.prompt(`新しい名前を入力: ${name}`, name);
  if (!newName || newName === name) return;
  try {
    const res = await fetch(`${CORE_URL}/api/language/rename`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: activeTabPath, name, new_name: newName })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    pendingRename = { name, newName, edits: data.edits || [] };
    showSftpOutput(`${name} -> ${newName}\n編集件数: ${data.edits.length}\n適用前に内容を確認してください。`);
    showToast(`リネーム案を作成: ${data.edits.length} 件`, 'success');
  } catch (error) {
    showToast(`リネーム案の作成失敗: ${error.message}`, 'error');
  }
}

// ── View Toggle (Code vs Diff Editor) ────────────────────────────────────────
function switchToCodeView() {
  if (!isDiffMode) return;
  isDiffMode = false;
  document.getElementById('btn-view-code').classList.add('active');
  document.getElementById('btn-view-diff').classList.remove('active');

  const container = document.getElementById('editor-container');
  if (monacoDiffEditor) {
    monacoDiffEditor.dispose();
    monacoDiffEditor = null;
  }
  container.innerHTML = '';
  monacoEditor = monaco.editor.create(container, {
    value: currentModifiedModel ? currentModifiedModel.getValue() : '',
    language: 'python',
    theme: 'vs-dark',
    automaticLayout: true,
    fontSize: 13,
    minimap: { enabled: false }
  });
}

async function toggleDiffView() {
  isDiffMode = true;
  document.getElementById('btn-view-code').classList.remove('active');
  document.getElementById('btn-view-diff').classList.add('active');

  let diffText = '';
  try {
    const res = await fetch(`${CORE_URL}/api/git/diff`);
    if (res.ok) {
      const data = await res.json();
      diffText = data.diff || '未コミットの差分はありません。';
    }
  } catch (e) {
    diffText = 'Git 差分を取得できません（IDE Daemon オフライン）。';
  }

  const container = document.getElementById('editor-container');
  if (monacoEditor) {
    monacoEditor.dispose();
    monacoEditor = null;
  }
  if (monacoDiffEditor) {
    monacoDiffEditor.dispose();
  }
  container.innerHTML = '';

  monacoDiffEditor = monaco.editor.createDiffEditor(container, {
    theme: 'vs-dark',
    automaticLayout: true,
    readOnly: true,
    fontSize: 13
  });

  currentOriginalModel = monaco.editor.createModel('/* 元の状態 */\n', 'diff');
  currentModifiedModel = monaco.editor.createModel(diffText, 'diff');

  monacoDiffEditor.setModel({
    original: currentOriginalModel,
    modified: currentModifiedModel
  });
}

// ── Bottom Tab Panel ─────────────────────────────────────────────────────────
function switchBottomTab(name) {
  document.querySelectorAll('.bottom-tab').forEach(tab => {
    tab.classList.toggle('active', tab.getAttribute('data-tab') === name);
  });
  ['output', 'problems', 'debug', 'terminal'].forEach(tab => {
    const pane = document.getElementById(`panel-${tab}`);
    if (pane) pane.classList.toggle('hidden', tab !== name);
  });
  if (name === 'problems') refreshProblems();
  if (name === 'terminal') ensureTerminal();
}

// ── Debug Console ────────────────────────────────────────────────────────────
function debugLog(text) {
  const el = document.getElementById('debug-console');
  if (!el) return;
  if (el.textContent === 'デバッグ待機中...') el.textContent = '';
  el.textContent += (el.textContent ? '\n' : '') + text;
  el.scrollTop = el.scrollHeight;
}

// ── Problems Panel ───────────────────────────────────────────────────────────
async function refreshProblems() {
  const list = document.getElementById('problems-list');
  const count = document.getElementById('problems-count');
  if (!list) return;
  let problems = {};
  let engine = '';
  try {
    const res = await fetch(`${CORE_URL}/api/lsp/problems`);
    const data = await res.json();
    if (data.ok) { problems = data.problems || {}; engine = data.engine || ''; }
  } catch (e) {}
  const rows = [];
  for (const [path, items] of Object.entries(problems)) {
    for (const item of items) {
      rows.push({ path, ...item });
    }
  }
  if (count) count.textContent = String(rows.length);
  if (!rows.length) {
    list.innerHTML = `<div class="problem-item"><span class="problem-loc">問題は検出されていません${engine ? ` (${engine})` : ''}</span></div>`;
    return;
  }
  list.innerHTML = rows.map(item => {
    const sev = item.severity || 'information';
    const icon = sev === 'error' ? '⛔' : (sev === 'warning' ? '⚠️' : 'ℹ️');
    return `<div class="problem-item" data-path="${escapeHtml(item.path)}" data-line="${item.line}" data-column="${item.column}">
      <span class="sev-${sev}">${icon}</span>
      <span>${escapeHtml(item.message || '')}</span>
      <span class="problem-loc">${escapeHtml(item.path)}:${item.line}:${item.column}</span>
    </div>`;
  }).join('');
  list.querySelectorAll('.problem-item[data-path]').forEach(el => {
    el.addEventListener('click', async () => {
      await openFileInEditor(el.getAttribute('data-path'));
      if (monacoEditor) {
        const line = Number(el.getAttribute('data-line')) || 1;
        const column = Number(el.getAttribute('data-column')) || 1;
        monacoEditor.setPosition({ lineNumber: line, column });
        monacoEditor.revealLineInCenter(line);
        monacoEditor.focus();
      }
    });
  });
}

// ── Integrated Terminal ──────────────────────────────────────────────────────
async function ensureTerminal() {
  try {
    const res = await fetch(`${CORE_URL}/api/terminal/start`, { method: 'POST', headers: { ...authHeader } });
    const data = await res.json();
    if (!data.ok) {
      const view = document.getElementById('terminal-view');
      if (view) view.textContent = `ターミナル起動失敗: ${data.error || 'unknown'}`;
      return;
    }
    startTerminalPolling();
  } catch (error) {
    const view = document.getElementById('terminal-view');
    if (view) view.textContent = `ターミナル接続エラー: ${error.message}`;
  }
}

function startTerminalPolling() {
  if (terminalTimer) return;
  terminalTimer = setInterval(pollTerminal, 800);
  pollTerminal();
}

async function pollTerminal() {
  try {
    const res = await fetch(`${CORE_URL}/api/terminal/output?since=${terminalCursor}`, { headers: { ...authHeader } });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.ok) return;
    terminalCursor = data.cursor;
    if (data.data) {
      const view = document.getElementById('terminal-view');
      if (view) {
        view.textContent += data.data;
        view.scrollTop = view.scrollHeight;
      }
    }
    if (!data.running && terminalTimer) {
      clearInterval(terminalTimer);
      terminalTimer = null;
    }
  } catch (e) {}
}

async function sendTerminalInput(data) {
  try {
    await fetch(`${CORE_URL}/api/terminal/input`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ data })
    });
    setTimeout(pollTerminal, 200);
  } catch (error) {
    showToast(`ターミナル入力エラー: ${error.message}`, 'error');
  }
}

// ── Command Palette / Quick Open ─────────────────────────────────────────────
const PALETTE_COMMANDS = [
  { id: 'save', title: 'ファイルを保存', hint: 'Ctrl+S', run: () => saveActiveFile() },
  { id: 'run', title: '現在のファイルを実行', hint: '', run: () => runActiveFile() },
  { id: 'debug-start', title: 'デバッグ開始', hint: '', run: () => startDebugSession() },
  { id: 'debug-stop', title: 'デバッグ停止', hint: '', run: () => stopDebugSession() },
  { id: 'debug-inspect', title: 'デバッグ: スタック/変数を表示', hint: '', run: () => inspectDebugState() },
  { id: 'go-def', title: '定義へ移動', hint: '', run: () => goToDefinitionAtCursor() },
  { id: 'find-refs', title: '参照を検索', hint: '', run: () => findReferencesAtCursor() },
  { id: 'rename', title: 'シンボルをリネーム', hint: '', run: () => proposeRenameAtCursor() },
  { id: 'problems', title: '問題パネルを表示', hint: '', run: () => switchBottomTab('problems') },
  { id: 'terminal', title: 'ターミナルを表示', hint: '', run: () => switchBottomTab('terminal') },
  { id: 'debug-console', title: 'デバッグコンソールを表示', hint: '', run: () => switchBottomTab('debug') },
  { id: 'output', title: '出力パネルを表示', hint: '', run: () => switchBottomTab('output') },
  { id: 'git-refresh', title: 'Git: 状態を更新', hint: '', run: () => fetchGitStatus() },
  { id: 'git-stage', title: 'Git: 変更をステージ', hint: '', run: () => performGitStage() },
  { id: 'git-commit', title: 'Git: コミット', hint: '', run: () => performGitCommit() },
  { id: 'git-push', title: 'Git: Push', hint: '', run: () => performGitPush() },
  { id: 'git-diff', title: 'Git: 差分表示', hint: '', run: () => toggleDiffView() },
  { id: 'commit-suggest', title: 'AI: コミットメッセージ提案', hint: '', run: () => suggestCommitMessage() },
  { id: 'review', title: 'AI: 選択範囲をレビュー', hint: '', run: () => reviewSelectedCode() },
  { id: 'agent-stop', title: 'Agent: 停止', hint: '', run: () => stopAgent() },
  { id: 'agent-new', title: 'Agent: 新規セッション', hint: '', run: () => {
      agentSessionId = 'ui-' + Date.now().toString(36);
      showToast('Agentセッションを新規作成しました', 'info');
    } },
  { id: 'files-refresh', title: 'ファイル一覧を更新', hint: '', run: () => fetchWorkspaceFiles() },
  { id: 'diagnostics', title: '診断 (status) を開く', hint: '', run: () => runDoctor() },
  { id: 'clear-chat', title: 'チャット履歴を消去', hint: '', run: () => clearChat() },
];

let paletteMode = 'command';
let paletteIndex = 0;

function openPalette(mode) {
  paletteMode = mode;
  paletteIndex = 0;
  const overlay = document.getElementById('palette-overlay');
  const input = document.getElementById('palette-input');
  if (!overlay || !input) return;
  overlay.classList.remove('hidden');
  input.value = '';
  input.placeholder = mode === 'command' ? 'コマンドを検索...' : 'ファイル名で検索...';
  renderPalette('');
  setTimeout(() => input.focus(), 0);
}

function closePalette() {
  const overlay = document.getElementById('palette-overlay');
  if (overlay) overlay.classList.add('hidden');
}

function paletteItems(query) {
  const q = query.trim().toLowerCase();
  if (paletteMode === 'file') {
    return workspaceFiles
      .filter(path => !q || path.toLowerCase().includes(q))
      .slice(0, 50)
      .map(path => ({ title: path, hint: '', run: () => openFileInEditor(path) }));
  }
  return PALETTE_COMMANDS.filter(cmd => !q || cmd.title.toLowerCase().includes(q)).slice(0, 50);
}

function renderPalette(query) {
  const list = document.getElementById('palette-list');
  if (!list) return;
  const items = paletteItems(query);
  paletteIndex = Math.min(paletteIndex, Math.max(0, items.length - 1));
  list.innerHTML = items.map((item, index) =>
    `<div class="palette-item ${index === paletteIndex ? 'selected' : ''}" data-index="${index}">
      <span>${escapeHtml(item.title)}</span><span class="palette-hint">${escapeHtml(item.hint || '')}</span>
    </div>`).join('') || '<div class="palette-item"><span class="palette-hint">一致なし</span></div>';
  list.querySelectorAll('.palette-item[data-index]').forEach(el => {
    el.addEventListener('click', () => {
      const item = paletteItems(query)[Number(el.getAttribute('data-index'))];
      closePalette();
      if (item) item.run();
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('palette-input');
  const overlay = document.getElementById('palette-overlay');
  if (!input || !overlay) return;
  input.addEventListener('input', () => { paletteIndex = 0; renderPalette(input.value); });
  input.addEventListener('keydown', (e) => {
    const items = paletteItems(input.value);
    if (e.key === 'ArrowDown') { e.preventDefault(); paletteIndex = Math.min(paletteIndex + 1, items.length - 1); renderPalette(input.value); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); paletteIndex = Math.max(paletteIndex - 1, 0); renderPalette(input.value); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const item = items[paletteIndex];
      closePalette();
      if (item) item.run();
    } else if (e.key === 'Escape') { closePalette(); }
  });
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closePalette(); });
});

// ═══════════════════════════════════════════════════════════════════════════
// VS Code準拠レイアウト: Activity Bar / リサイズ / 表示トグル / 設定 / 永続化
// ═══════════════════════════════════════════════════════════════════════════
const LAYOUT_KEY = 'glm-layout-v1';

function loadLayout() {
  try { return JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}'); }
  catch (e) { return {}; }
}
function saveLayout(patch) {
  const next = { ...loadLayout(), ...patch };
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(next)); } catch (e) {}
}

// ── Activity Bar (左アイコン列) ───────────────────────────────────────────
function switchSidebarView(name) {
  document.querySelectorAll('.activity-item[data-view]').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-view') === name);
  });
  document.querySelectorAll('.sidebar-view').forEach(pane => {
    pane.classList.toggle('hidden', pane.getAttribute('data-view-pane') !== name);
  });
  const sidebar = document.getElementById('sidebar');
  if (sidebar && sidebar.style.display === 'none') toggleSidebar(); // 隠れていれば開く
  saveLayout({ activeView: name });
  if (name === 'search') setTimeout(() => document.getElementById('search-input')?.focus(), 50);
  if (name === 'explorer') fetchWorkspaceFiles();
  if (name === 'git') fetchGitStatus();
  if (name === 'sftp') fetchSftpProfiles();
  if (name === 'debug') showDevStatus();
  if (name === 'extensions') fetchExtensionStatus();
  if (name === 'settings') loadSettingsForm();
}

async function fetchExtensionStatus() {
  const list = document.getElementById('ext-list');
  if (!list) return;
  try {
    const res = await fetch(`${CORE_URL}/api/dev/status`);
    const data = await res.json();
    const entries = [
      ['GLM Core', true, 'ルーティング・ワークスペースAPI'],
      ['co-vibe Agent', true, '承認付きエージェント実行'],
      ['Pyright LSP', Boolean(data.lsp?.running || data.lsp?.available), '型診断・定義・補完'],
      ['Jupyter', Boolean(data.jupyter?.available), 'ノートブック実行'],
      ['DAP', Boolean(data.dap?.available), 'Pythonデバッグ'],
      ['SFTP', Boolean(data.sftp?.available), 'リモートファイル操作'],
    ];
    list.innerHTML = entries.map(([name, enabled, detail]) => `
      <div class="ext-item"><strong>${name}</strong><span>${detail} · ${enabled ? '利用可能' : '未導入'}</span></div>
    `).join('');
  } catch (error) {
    list.innerHTML = '<div class="ext-item"><strong>GLM Core</strong><span>バックエンドに接続できません</span></div>';
  }
}

// ── 表示/非表示トグル ─────────────────────────────────────────────────────
function toggleSidebar() {
  const el = document.getElementById('sidebar');
  const sash = document.getElementById('sash-left');
  const activity = document.getElementById('activity-bar');
  if (!el) return;
  const hidden = el.style.display === 'none';
  el.style.display = hidden ? '' : 'none';
  if (sash) sash.style.display = hidden ? '' : 'none';
  if (activity) activity.style.display = hidden ? '' : 'none';
  saveLayout({ sidebarHidden: !hidden });
}

function toggleAIPanel() {
  const el = document.getElementById('ai-panel');
  const sash = document.getElementById('sash-right');
  if (!el) return;
  const hidden = el.style.display === 'none';
  el.style.display = hidden ? '' : 'none';
  if (sash) sash.style.display = hidden ? '' : 'none';
  saveLayout({ aiPanelHidden: !hidden });
}

function toggleBottomPanel() {
  const el = document.getElementById('output-panel');
  const sash = document.getElementById('sash-bottom');
  if (!el) return;
  const hidden = el.style.display === 'none';
  el.style.display = hidden ? '' : 'none';
  if (sash) sash.style.display = hidden ? '' : 'none';
  saveLayout({ bottomHidden: !hidden });
}

// ── リサイズ（sashドラッグ）─────────────────────────────────────────────
function makeResizable(sashId, getSize, setSize, axis, min, max, storageKey) {
  const sash = document.getElementById(sashId);
  if (!sash) return;
  sash.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const startPos = axis === 'x' ? e.clientX : e.clientY;
    const startSize = getSize();
    document.body.classList.add('resizing', axis === 'x' ? 'col' : 'row');
    sash.classList.add('dragging');
    const onMove = (ev) => {
      const pos = axis === 'x' ? ev.clientX : ev.clientY;
      let size = startSize + (pos - startPos);
      size = Math.max(min, Math.min(max, size));
      setSize(size);
    };
    const onUp = () => {
      document.body.classList.remove('resizing', 'col', 'row');
      sash.classList.remove('dragging');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      saveLayout({ [storageKey]: getSize() });
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

function setupResizers() {
  const sidebar = document.getElementById('sidebar');
  const aiPanel = document.getElementById('ai-panel');
  const bottom = document.getElementById('output-panel');
  if (sidebar) {
    makeResizable('sash-left',
      () => sidebar.getBoundingClientRect().width,
      (v) => { sidebar.style.width = v + 'px'; },
      'x', 170, 600, 'sidebarWidth');
  }
  if (aiPanel) {
    // 右側はドラッグ方向が逆（左へ動かすと広がる）
    const sash = document.getElementById('sash-right');
    if (sash) {
      sash.addEventListener('mousedown', (e) => {
        e.preventDefault();
        const startX = e.clientX;
        const startW = aiPanel.getBoundingClientRect().width;
        document.body.classList.add('resizing', 'col');
        sash.classList.add('dragging');
        const onMove = (ev) => {
          let w = startW - (ev.clientX - startX);
          w = Math.max(260, Math.min(700, w));
          aiPanel.style.width = w + 'px';
        };
        const onUp = () => {
          document.body.classList.remove('resizing', 'col');
          sash.classList.remove('dragging');
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          saveLayout({ aiPanelWidth: aiPanel.getBoundingClientRect().width });
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
      });
    }
  }
  if (bottom) {
    // 下部は上方向へドラッグで広がる
    const sash = document.getElementById('sash-bottom');
    if (sash) {
      sash.addEventListener('mousedown', (e) => {
        e.preventDefault();
        const startY = e.clientY;
        const startH = bottom.getBoundingClientRect().height;
        document.body.classList.add('resizing', 'row');
        sash.classList.add('dragging');
        const onMove = (ev) => {
          let h = startH - (ev.clientY - startY);
          h = Math.max(90, Math.min(window.innerHeight * 0.7, h));
          bottom.style.height = h + 'px';
        };
        const onUp = () => {
          document.body.classList.remove('resizing', 'row');
          sash.classList.remove('dragging');
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          saveLayout({ bottomHeight: bottom.getBoundingClientRect().height });
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
      });
    }
  }
}

// ── レイアウト復元 ───────────────────────────────────────────────────────
function restoreLayout() {
  const saved = loadLayout();
  const sidebar = document.getElementById('sidebar');
  const aiPanel = document.getElementById('ai-panel');
  const bottom = document.getElementById('output-panel');
  if (saved.sidebarWidth && sidebar) sidebar.style.width = saved.sidebarWidth + 'px';
  if (saved.aiPanelWidth && aiPanel) aiPanel.style.width = saved.aiPanelWidth + 'px';
  if (saved.bottomHeight && bottom) bottom.style.height = saved.bottomHeight + 'px';
  if (saved.sidebarHidden) { if (sidebar) sidebar.style.display = 'none'; const s = document.getElementById('sash-left'); if (s) s.style.display = 'none'; const a = document.getElementById('activity-bar'); if (a) a.style.display = 'none'; }
  if (saved.aiPanelHidden) { if (aiPanel) aiPanel.style.display = 'none'; const s = document.getElementById('sash-right'); if (s) s.style.display = 'none'; }
  if (saved.bottomHidden) { if (bottom) bottom.style.display = 'none'; const s = document.getElementById('sash-bottom'); if (s) s.style.display = 'none'; }
  if (saved.activeView) switchSidebarView(saved.activeView);
}

function resetLayout() {
  localStorage.removeItem(LAYOUT_KEY);
  location.reload();
}

// ── 設定適用 ─────────────────────────────────────────────────────────────
function applySettings() {
  const fontSize = Number(document.getElementById('settings-font-size')?.value || 13);
  const mode = document.getElementById('settings-mode')?.value;
  const model = document.getElementById('settings-model')?.value;
  const sidePos = document.getElementById('settings-sidebar-pos')?.value;
  if (monacoEditor) monacoEditor.updateOptions({ fontSize });
  if (mode) {
    const modeSelect = document.getElementById('mode-select');
    if (modeSelect) { modeSelect.value = mode; modeSelect.dispatchEvent(new Event('change')); }
  }
  if (model) {
    const modelSelect = document.getElementById('agent-model-select');
    if (modelSelect) modelSelect.value = model;
  }
  if (sidePos) applySidebarPosition(sidePos);
  saveLayout({ fontSize, mode, model, sidePos });
  showToast('設定を適用しました', 'success');
}

function loadSettingsForm() {
  const saved = loadLayout();
  const mode = document.getElementById('settings-mode');
  const model = document.getElementById('settings-model');
  const fontSize = document.getElementById('settings-font-size');
  const sidePos = document.getElementById('settings-sidebar-pos');
  if (mode && saved.mode) mode.value = saved.mode;
  if (model && saved.model) model.value = saved.model;
  if (fontSize && saved.fontSize) fontSize.value = saved.fontSize;
  if (sidePos && saved.sidePos) sidePos.value = saved.sidePos;
}

function applySidebarPosition(pos) {
  const main = document.querySelector('.main-layout');
  const activity = document.getElementById('activity-bar');
  const sidebar = document.getElementById('sidebar');
  const sashLeft = document.getElementById('sash-left');
  if (!main || !activity || !sidebar || !sashLeft) return;
  if (pos === 'right') {
    // 左側グループを右端へ移動
    main.appendChild(sashLeft);
    main.appendChild(sidebar);
    main.appendChild(activity);
  } else {
    main.insertBefore(sashLeft, main.children[1]);
    main.insertBefore(sidebar, main.children[1]);
    main.insertBefore(activity, main.children[0]);
    main.insertBefore(sidebar, sashLeft);
  }
}

// ── 初期化（既存DOMContentLoadedに追加）─────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Activity Bar
  document.querySelectorAll('.activity-item[data-view]').forEach(btn => {
    btn.addEventListener('click', () => switchSidebarView(btn.getAttribute('data-view')));
  });
  setupResizers();
  restoreLayout();

  // 設定
  const applyBtn = document.getElementById('btn-settings-apply');
  if (applyBtn) applyBtn.addEventListener('click', applySettings);
  const resetBtn = document.getElementById('btn-layout-reset');
  if (resetBtn) resetBtn.addEventListener('click', resetLayout);
  const customizationReload = document.getElementById('btn-customization-reload');
  if (customizationReload) customizationReload.addEventListener('click', reloadCustomizations);

  // デバッグビューのボタン（トップバーと同じ動作を割当）
  const map = { 'btn-debug2': 'btn-debug', 'btn-debug-stop2': 'btn-debug-stop',
    'btn-debug-breakpoint2': 'btn-debug-breakpoint', 'btn-debug-continue2': 'btn-debug-continue',
    'btn-debug-next2': 'btn-debug-next', 'btn-debug-inspect2': 'btn-debug-inspect' };
  Object.entries(map).forEach(([id, target]) => {
    const el = document.getElementById(id);
    const tgt = document.getElementById(target);
    if (el && tgt) el.addEventListener('click', () => tgt.click());
  });
  // デバッグビューの行番号入力をトップバーのものと同期
  const line2 = document.getElementById('debug-breakpoint-line2');
  const line1 = document.getElementById('debug-breakpoint-line');
  if (line2 && line1) line2.addEventListener('input', () => { line1.value = line2.value; });

  // 検索ビュー
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    let searchTimer = null;
    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => runSidebarSearch(searchInput.value), 300);
    });
  }

  const extensionSearch = document.getElementById('ext-search');
  if (extensionSearch) {
    extensionSearch.addEventListener('input', () => {
      const query = extensionSearch.value.trim().toLowerCase();
      document.querySelectorAll('#ext-list .ext-item').forEach(item => {
        item.classList.toggle('hidden', query && !item.textContent.toLowerCase().includes(query));
      });
    });
  }
  const marketplaceSearch = document.getElementById('marketplace-search');
  if (marketplaceSearch) marketplaceSearch.addEventListener('input', () => fetchMarketplaceExtensions(marketplaceSearch.value));
  const marketplaceList = document.getElementById('marketplace-list');
  if (marketplaceList) marketplaceList.addEventListener('click', event => {
    const button = event.target.closest('[data-marketplace-install]');
    if (button) installMarketplaceExtension(button.dataset.marketplaceInstall);
  });
  const modelSave = document.getElementById('btn-model-selection-save');
  if (modelSave) modelSave.addEventListener('click', saveModelSelection);
  const customizationSelect = document.getElementById('customization-file-select');
  if (customizationSelect) customizationSelect.addEventListener('change', () => {
    const file = customizationFiles.find(item => item.path === customizationSelect.value);
    const editor = document.getElementById('customization-editor');
    if (editor) editor.value = file?.content || '';
  });
  const customizationSave = document.getElementById('btn-customization-save');
  if (customizationSave) customizationSave.addEventListener('click', saveCustomizationFile);
  const customizationValidate = document.getElementById('btn-customization-validate');
  if (customizationValidate) customizationValidate.addEventListener('click', validateCustomizations);
  const pylanceRefresh = document.getElementById('btn-pylance-mcp-refresh');
  if (pylanceRefresh) pylanceRefresh.addEventListener('click', fetchPylanceMcp);

  // レイアウトのキーボードショートカット（Ctrl+B左、Ctrl+J下、Ctrl+Shift+Y右）
  window.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    const k = e.key.toLowerCase();
    if (k === 'b' && !e.shiftKey) { e.preventDefault(); toggleSidebar(); }
    else if (k === 'j' && !e.shiftKey) { e.preventDefault(); toggleBottomPanel(); }
    else if (k === 'y' && e.shiftKey) { e.preventDefault(); toggleAIPanel(); }
  });
});

// サイドバー検索（ワークスペース内ファイル内容）
async function runSidebarSearch(query) {
  const list = document.getElementById('search-results');
  if (!list) return;
  if (!query || query.trim().length < 2) { list.innerHTML = ''; return; }
  try {
    const res = await fetch(`${CORE_URL}/api/workspace/search`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader },
      body: JSON.stringify({ query: query.trim() })
    });
    const data = await res.json();
    const results = data.results || [];
    list.innerHTML = results.slice(0, 30).map(r =>
      `<div class="tree-item" data-path="${r.path}" data-line="${r.line}">${r.path}:${r.line} <span style="color:var(--text-muted)">${escapeHtml((r.text||'').trim().slice(0,60))}</span></div>`
    ).join('') || '<div class="tree-item">一致なし</div>';
    list.querySelectorAll('.tree-item').forEach(el => {
      el.addEventListener('click', async () => {
        await openFileInEditor(el.getAttribute('data-path'));
        if (monacoEditor) {
          const line = Number(el.getAttribute('data-line')) || 1;
          monacoEditor.setPosition({ lineNumber: line, column: 1 });
          monacoEditor.revealLineInCenter(line);
          monacoEditor.focus();
        }
      });
    });
  } catch (e) {
    list.innerHTML = '<div class="tree-item">検索エラー</div>';
  }
}
