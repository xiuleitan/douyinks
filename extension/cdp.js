/**
 * CDP execution via chrome.debugger API.
 *
 * Provides evaluate() to run JS in any http/https tab,
 * plus attach/detach lifecycle management.
 */

const attached = new Set();
const kuaishouLikedCaptures = new Map();

const BLANK_PAGE = 'data:text/html,<html></html>';
const KUAISHOU_LIKED_PATH = '/rest/v/feed/liked';
const MAX_KUAISHOU_LIKED_RESPONSES = 1000;
const MAX_KUAISHOU_CAPTURE_ERRORS = 1000;
const RESPONSE_BODY_RETRY_DELAYS_MS = [0, 50, 200];
const NETWORK_TOTAL_BUFFER_BYTES = 64 * 1024 * 1024;
const NETWORK_RESOURCE_BUFFER_BYTES = 4 * 1024 * 1024;

function isDebuggableUrl(url) {
  if (!url) return true;
  return url.startsWith('http://') || url.startsWith('https://') || url === BLANK_PAGE;
}

async function ensureAttached(tabId) {
  // Verify the tab URL is debuggable
  try {
    const tab = await chrome.tabs.get(tabId);
    if (!isDebuggableUrl(tab.url)) {
      attached.delete(tabId);
      throw new Error(`Cannot debug tab ${tabId}: URL is ${tab.url ?? 'unknown'}`);
    }
  } catch (e) {
    if (e instanceof Error && e.message.startsWith('Cannot debug tab')) throw e;
    attached.delete(tabId);
    throw new Error(`Tab ${tabId} no longer exists`);
  }

  if (attached.has(tabId)) {
    // Verify debugger is still actually attached
    try {
      await chrome.debugger.sendCommand({ tabId }, 'Runtime.evaluate', {
        expression: '1',
        returnByValue: true,
      });
      return;
    } catch {
      attached.delete(tabId);
    }
  }

  try {
    await chrome.debugger.attach({ tabId }, '1.3');
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes('Another debugger is already attached')) {
      try { await chrome.debugger.detach({ tabId }); } catch { /* ignore */ }
      try {
        await chrome.debugger.attach({ tabId }, '1.3');
      } catch {
        throw new Error(`attach failed: ${msg}`);
      }
    } else {
      throw new Error(`attach failed: ${msg}`);
    }
  }
  attached.add(tabId);

  try {
    await chrome.debugger.sendCommand({ tabId }, 'Runtime.enable');
  } catch {
    // Some pages may not need explicit enable
  }
}

export async function evaluate(tabId, expression) {
  await ensureAttached(tabId);

  const result = await chrome.debugger.sendCommand({ tabId }, 'Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });

  if (result.exceptionDetails) {
    const errMsg =
      result.exceptionDetails.exception?.description ||
      result.exceptionDetails.text ||
      'Eval error';
    throw new Error(errMsg);
  }

  return result.result?.value;
}

export async function click(tabId, x, y) {
  await ensureAttached(tabId);
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x,
    y,
    button: 'left',
    clickCount: 1,
  });
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x,
    y,
    button: 'left',
    clickCount: 1,
  });
  return { clicked: true, x, y };
}

export async function startKuaishouLikedCapture(tabId, { clear = true } = {}) {
  await ensureAttached(tabId);
  const existing = normalizeKuaishouLikedCapture(kuaishouLikedCaptures.get(tabId));
  if (clear) {
    existing.responses = [];
    existing.errors = [];
    existing.pending.clear();
    existing.matched = 0;
    existing.completed = 0;
    existing.failed = 0;
    existing.dropped = 0;
    existing.generation += 1;
  }
  existing.startedAt = Date.now();
  existing.detached = false;
  existing.detachedAt = null;
  kuaishouLikedCaptures.set(tabId, existing);
  await enableKuaishouNetworkCapture(tabId);
  return captureSnapshot(tabId, existing);
}

export function readKuaishouLikedCapture(tabId) {
  const capture = normalizeKuaishouLikedCapture(kuaishouLikedCaptures.get(tabId));
  kuaishouLikedCaptures.set(tabId, capture);
  return captureSnapshot(tabId, capture);
}

export function clearKuaishouLikedCapture(tabId) {
  const capture = normalizeKuaishouLikedCapture(kuaishouLikedCaptures.get(tabId));
  capture.responses = [];
  capture.errors = [];
  capture.pending.clear();
  capture.matched = 0;
  capture.completed = 0;
  capture.failed = 0;
  capture.dropped = 0;
  capture.generation += 1;
  capture.startedAt = Date.now();
  capture.detached = false;
  capture.detachedAt = null;
  kuaishouLikedCaptures.set(tabId, capture);
  return captureSnapshot(tabId, capture);
}

function normalizeKuaishouLikedCapture(capture) {
  const result = capture ?? {};
  if (!Array.isArray(result.responses)) result.responses = [];
  if (!Array.isArray(result.errors)) result.errors = [];
  if (!(result.pending instanceof Map)) result.pending = new Map();
  if (!Number.isInteger(result.matched)) result.matched = 0;
  if (!Number.isInteger(result.completed)) result.completed = 0;
  if (!Number.isInteger(result.failed)) result.failed = 0;
  if (!Number.isInteger(result.dropped)) result.dropped = 0;
  if (!Number.isInteger(result.generation)) result.generation = 0;
  if (typeof result.detached !== 'boolean') result.detached = false;
  if (!Number.isFinite(result.detachedAt)) result.detachedAt = null;
  return result;
}

function captureSnapshot(tabId, capture) {
  return {
    tabId,
    responses: capture.responses,
    errors: capture.errors,
    startedAt: capture.startedAt ?? null,
    matched: capture.matched,
    completed: capture.completed,
    failed: capture.failed,
    pending: capture.pending.size,
    dropped: capture.dropped,
    detached: capture.detached,
    detachedAt: capture.detachedAt,
  };
}

async function enableKuaishouNetworkCapture(tabId) {
  const params = {
    maxTotalBufferSize: NETWORK_TOTAL_BUFFER_BYTES,
    maxResourceBufferSize: NETWORK_RESOURCE_BUFFER_BYTES,
    enableDurableMessages: true,
  };
  try {
    await chrome.debugger.sendCommand({ tabId }, 'Network.enable', params);
  } catch {
    // Older Chromium versions do not support durable network messages.
    await chrome.debugger.sendCommand({ tabId }, 'Network.enable');
  }
}

function isKuaishouLikedUrl(url) {
  try {
    const parsed = new URL(url);
    const isKuaishouHost = parsed.hostname === 'kuaishou.com' || parsed.hostname.endsWith('.kuaishou.com');
    return isKuaishouHost && parsed.pathname === KUAISHOU_LIKED_PATH;
  } catch {
    return String(url).includes(KUAISHOU_LIKED_PATH);
  }
}

function recordCaptureError(capture, details) {
  capture.failed += 1;
  capture.errors.push({ ts: Date.now(), ...details });
  if (capture.errors.length > MAX_KUAISHOU_CAPTURE_ERRORS) capture.errors.shift();
}

async function getResponseBodyWhenReady(tabId, requestId) {
  let lastError;
  for (const retryDelay of RESPONSE_BODY_RETRY_DELAYS_MS) {
    if (retryDelay) await new Promise((resolve) => setTimeout(resolve, retryDelay));
    try {
      return await chrome.debugger.sendCommand({ tabId }, 'Network.getResponseBody', { requestId });
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError ?? new Error('Unable to read response body');
}

async function storeKuaishouLikedResponse(tabId, capture, requestId) {
  const pending = capture.pending.get(requestId);
  if (!pending) return;
  try {
    const bodyResult = await getResponseBodyWhenReady(tabId, requestId);
    const text = bodyResult.base64Encoded ? atob(bodyResult.body) : bodyResult.body;
    const data = JSON.parse(text);
    if (kuaishouLikedCaptures.get(tabId) !== capture || capture.generation !== pending.generation) return;
    capture.responses.push({
      url: pending.url,
      status: pending.status,
      ts: pending.ts,
      data,
    });
    capture.completed += 1;
    if (capture.responses.length > MAX_KUAISHOU_LIKED_RESPONSES) {
      capture.responses.shift();
      capture.dropped += 1;
    }
  } catch (err) {
    if (kuaishouLikedCaptures.get(tabId) === capture && capture.generation === pending.generation) {
      recordCaptureError(capture, {
        requestId,
        url: pending.url,
        stage: 'getResponseBody',
        error: err instanceof Error ? err.message : String(err),
      });
    }
  } finally {
    if (capture.pending.get(requestId) === pending) capture.pending.delete(requestId);
  }
}

export async function detach(tabId) {
  if (!attached.has(tabId)) return;
  attached.delete(tabId);
  try { await chrome.debugger.detach({ tabId }); } catch { /* ignore */ }
}

export function registerListeners() {
  chrome.debugger.onEvent.addListener(async (source, method, params) => {
    const tabId = source.tabId;
    if (!tabId) return;
    const capture = kuaishouLikedCaptures.get(tabId);
    if (!capture) return;
    if (method === 'Network.responseReceived') {
      const response = params?.response;
      const url = response?.url ?? '';
      const requestId = params?.requestId;
      if (!requestId || !isKuaishouLikedUrl(url) || capture.pending.has(requestId)) return;
      capture.matched += 1;
      capture.pending.set(requestId, {
        generation: capture.generation,
        url,
        status: response.status,
        ts: Date.now(),
      });
      return;
    }

    const requestId = params?.requestId;
    const pending = requestId ? capture.pending.get(requestId) : null;
    if (!pending) return;
    if (method === 'Network.loadingFinished') {
      await storeKuaishouLikedResponse(tabId, capture, requestId);
      return;
    }
    if (method === 'Network.loadingFailed') {
      capture.pending.delete(requestId);
      recordCaptureError(capture, {
        requestId,
        url: pending.url,
        stage: 'loadingFailed',
        error: params?.errorText || 'Request failed before the response body was available',
      });
    }
  });
  chrome.tabs.onRemoved.addListener((tabId) => {
    attached.delete(tabId);
    kuaishouLikedCaptures.delete(tabId);
  });
  chrome.debugger.onDetach.addListener((source) => {
    if (source.tabId) {
      attached.delete(source.tabId);
      const capture = kuaishouLikedCaptures.get(source.tabId);
      if (capture) {
        capture.detached = true;
        capture.detachedAt = Date.now();
      }
    }
  });
  chrome.tabs.onUpdated.addListener(async (tabId, info) => {
    if (info.url && !isDebuggableUrl(info.url)) {
      await detach(tabId);
    }
  });
}
