/**
 * Douyinks service worker.
 *
 * Connects to the local Douyinks daemon via WebSocket, receives commands,
 * dispatches them to Chrome APIs, and returns results.
 */

import * as executor from './cdp.js';

const DAEMON_PORT = 19826;
const DAEMON_WS_URL = `ws://localhost:${DAEMON_PORT}/ext`;
const DAEMON_PING_URL = `http://localhost:${DAEMON_PORT}/ping`;
const WS_RECONNECT_BASE_DELAY = 2000;
const WS_RECONNECT_MAX_DELAY = 60000;
const MAX_EAGER_ATTEMPTS = 6;
const WINDOW_IDLE_TIMEOUT = 30000;
const BLANK_PAGE = 'data:text/html,<html></html>';

let ws = null;
let reconnectTimer = null;
let reconnectAttempts = 0;
const automationSessions = new Map();

async function connect() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;
  try {
    const res = await fetch(DAEMON_PING_URL, { signal: AbortSignal.timeout(1000) });
    if (!res.ok) return;
  } catch {
    return;
  }

  try {
    ws = new WebSocket(DAEMON_WS_URL);
  } catch {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    reconnectAttempts = 0;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    ws?.send(JSON.stringify({ type: 'hello', version: chrome.runtime.getManifest().version }));
  };

  ws.onmessage = async (event) => {
    try {
      const command = JSON.parse(event.data);
      const result = await handleCommand(command);
      ws?.send(JSON.stringify(result));
    } catch (err) {
      console.error('[douyinks] Message handling error:', err);
    }
  };

  ws.onclose = () => {
    ws = null;
    scheduleReconnect();
  };
  ws.onerror = () => ws?.close();
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectAttempts++;
  if (reconnectAttempts > MAX_EAGER_ATTEMPTS) return;
  const delay = Math.min(WS_RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts - 1), WS_RECONNECT_MAX_DELAY);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function getWorkspaceKey(workspace) {
  return workspace?.trim() || 'default';
}

function resetWindowIdleTimer(workspace) {
  const session = automationSessions.get(workspace);
  if (!session) return;
  if (session.idleTimer) clearTimeout(session.idleTimer);
  session.idleTimer = setTimeout(async () => {
    const current = automationSessions.get(workspace);
    if (!current) return;
    try {
      await chrome.windows.remove(current.windowId);
    } catch { /* already gone */ }
    automationSessions.delete(workspace);
  }, WINDOW_IDLE_TIMEOUT);
}

async function getAutomationWindow(workspace) {
  const existing = automationSessions.get(workspace);
  if (existing) {
    try {
      await chrome.windows.get(existing.windowId);
      return existing.windowId;
    } catch {
      automationSessions.delete(workspace);
    }
  }
  const win = await chrome.windows.create({
    url: BLANK_PAGE,
    focused: false,
    width: 1280,
    height: 900,
    type: 'normal',
  });
  automationSessions.set(workspace, { windowId: win.id, idleTimer: null });
  resetWindowIdleTimer(workspace);
  await new Promise((resolve) => setTimeout(resolve, 200));
  return win.id;
}

chrome.windows.onRemoved.addListener((windowId) => {
  for (const [workspace, session] of automationSessions.entries()) {
    if (session.windowId === windowId) {
      if (session.idleTimer) clearTimeout(session.idleTimer);
      automationSessions.delete(workspace);
    }
  }
});

let initialized = false;

function initialize() {
  if (initialized) return;
  initialized = true;
  chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
  executor.registerListeners();
  connect();
}

chrome.runtime.onInstalled.addListener(() => initialize());
chrome.runtime.onStartup.addListener(() => initialize());
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepalive') connect();
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'getStatus') {
    sendResponse({
      connected: ws?.readyState === WebSocket.OPEN,
      reconnecting: reconnectTimer !== null,
    });
  }
  return false;
});

function isDebuggableUrl(url) {
  if (!url) return true;
  return url.startsWith('http://') || url.startsWith('https://') || url === BLANK_PAGE;
}

function isSafeNavigationUrl(url) {
  return url.startsWith('http://') || url.startsWith('https://');
}

function normalizeUrlForComparison(url) {
  if (!url) return '';
  try {
    const parsed = new URL(url);
    if ((parsed.protocol === 'https:' && parsed.port === '443') || (parsed.protocol === 'http:' && parsed.port === '80')) {
      parsed.port = '';
    }
    const pathname = parsed.pathname === '/' ? '' : parsed.pathname;
    return `${parsed.protocol}//${parsed.host}${pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return url;
  }
}

function isTargetUrl(currentUrl, targetUrl) {
  return normalizeUrlForComparison(currentUrl) === normalizeUrlForComparison(targetUrl);
}

async function resolveTabId(tabId, workspace) {
  if (tabId !== undefined) {
    try {
      const tab = await chrome.tabs.get(tabId);
      const session = automationSessions.get(workspace);
      if (isDebuggableUrl(tab.url) && session && tab.windowId === session.windowId) return tabId;
    } catch { /* tab was closed */ }
  }

  const windowId = await getAutomationWindow(workspace);
  const tabs = await chrome.tabs.query({ windowId });
  const debuggableTab = tabs.find((t) => t.id && isDebuggableUrl(t.url));
  if (debuggableTab?.id) return debuggableTab.id;

  const newTab = await chrome.tabs.create({ windowId, url: BLANK_PAGE, active: true });
  if (!newTab.id) throw new Error('Failed to create tab in automation window');
  return newTab.id;
}

async function handleCommand(cmd) {
  const workspace = getWorkspaceKey(cmd.workspace);
  resetWindowIdleTimer(workspace);
  try {
    switch (cmd.action) {
      case 'exec':
        return await handleExec(cmd, workspace);
      case 'navigate':
        return await handleNavigate(cmd, workspace);
      case 'tabs':
        return await handleTabs(cmd, workspace);
      case 'cookies':
        return await handleCookies(cmd);
      default:
        return { id: cmd.id, ok: false, error: `Unknown action: ${cmd.action}` };
    }
  } catch (err) {
    return { id: cmd.id, ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

async function handleExec(cmd, workspace) {
  if (!cmd.code) return { id: cmd.id, ok: false, error: 'Missing code' };
  const tabId = await resolveTabId(cmd.tabId, workspace);
  try {
    const data = await executor.evaluate(tabId, cmd.code);
    return { id: cmd.id, ok: true, data };
  } catch (err) {
    return { id: cmd.id, ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

async function handleNavigate(cmd, workspace) {
  if (!cmd.url) return { id: cmd.id, ok: false, error: 'Missing url' };
  if (!isSafeNavigationUrl(cmd.url)) return { id: cmd.id, ok: false, error: 'Blocked URL scheme' };
  const tabId = await resolveTabId(cmd.tabId, workspace);
  const beforeTab = await chrome.tabs.get(tabId);
  const beforeNormalized = normalizeUrlForComparison(beforeTab.url);
  const targetUrl = cmd.url;

  if (beforeTab.status === 'complete' && isTargetUrl(beforeTab.url, targetUrl)) {
    return { id: cmd.id, ok: true, data: { title: beforeTab.title, url: beforeTab.url, tabId, timedOut: false } };
  }

  await executor.detach(tabId);
  await chrome.tabs.update(tabId, { url: targetUrl });
  let timedOut = false;
  await new Promise((resolve) => {
    let settled = false;
    let timeoutTimer = null;
    const finish = () => {
      if (settled) return;
      settled = true;
      chrome.tabs.onUpdated.removeListener(listener);
      if (timeoutTimer) clearTimeout(timeoutTimer);
      resolve();
    };
    const isNavigationDone = (url) => isTargetUrl(url, targetUrl) || normalizeUrlForComparison(url) !== beforeNormalized;
    const listener = (id, info, tab) => {
      if (id === tabId && info.status === 'complete' && isNavigationDone(tab.url ?? info.url)) finish();
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(async () => {
      try {
        const currentTab = await chrome.tabs.get(tabId);
        if (currentTab.status === 'complete' && isNavigationDone(currentTab.url)) finish();
      } catch { /* tab gone */ }
    }, 100);
    timeoutTimer = setTimeout(() => {
      timedOut = true;
      finish();
    }, 15000);
  });
  const tab = await chrome.tabs.get(tabId);
  return { id: cmd.id, ok: true, data: { title: tab.title, url: tab.url, tabId, timedOut } };
}

async function handleTabs(cmd, workspace) {
  switch (cmd.op) {
    case 'list': {
      const session = automationSessions.get(workspace);
      if (!session) return { id: cmd.id, ok: true, data: [] };
      const tabs = await chrome.tabs.query({ windowId: session.windowId });
      return { id: cmd.id, ok: true, data: tabs.filter((t) => isDebuggableUrl(t.url)).map((t, i) => ({
        index: i, tabId: t.id, url: t.url, title: t.title, active: t.active,
      })) };
    }
    case 'new': {
      if (cmd.url && !isSafeNavigationUrl(cmd.url)) return { id: cmd.id, ok: false, error: 'Blocked URL scheme' };
      const windowId = await getAutomationWindow(workspace);
      const tab = await chrome.tabs.create({ windowId, url: cmd.url ?? BLANK_PAGE, active: true });
      return { id: cmd.id, ok: true, data: { tabId: tab.id, url: tab.url } };
    }
    case 'close': {
      const tabId = await resolveTabId(cmd.tabId, workspace);
      await chrome.tabs.remove(tabId);
      await executor.detach(tabId);
      return { id: cmd.id, ok: true, data: { closed: tabId } };
    }
    default:
      return { id: cmd.id, ok: false, error: `Unknown tabs op: ${cmd.op}` };
  }
}

async function handleCookies(cmd) {
  if (!cmd.domain && !cmd.url) return { id: cmd.id, ok: false, error: 'Cookie scope required' };
  const details = {};
  if (cmd.domain) details.domain = cmd.domain;
  if (cmd.url) details.url = cmd.url;
  const cookies = await chrome.cookies.getAll(details);
  return { id: cmd.id, ok: true, data: cookies.map((c) => ({
    name: c.name, value: c.value, domain: c.domain, path: c.path,
    secure: c.secure, httpOnly: c.httpOnly, expirationDate: c.expirationDate,
  })) };
}
