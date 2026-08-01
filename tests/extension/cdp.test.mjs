import assert from 'node:assert/strict';
import test from 'node:test';


function createEvent() {
  return {
    listeners: [],
    addListener(listener) {
      this.listeners.push(listener);
    },
  };
}


test('captures every completed Kuaishou liked response and retries an early body read', async () => {
  const onEvent = createEvent();
  const onDetach = createEvent();
  const onRemoved = createEvent();
  const onUpdated = createEvent();
  const calls = [];
  const bodyAttempts = new Map();

  globalThis.chrome = {
    tabs: {
      get: async () => ({ url: 'https://www.kuaishou.com/profile/test' }),
      onRemoved,
      onUpdated,
    },
    debugger: {
      attach: async () => {},
      detach: async () => {},
      onEvent,
      onDetach,
      sendCommand: async (_target, method, params = {}) => {
        calls.push({ method, params });
        if (method !== 'Network.getResponseBody') return {};
        const attempts = (bodyAttempts.get(params.requestId) ?? 0) + 1;
        bodyAttempts.set(params.requestId, attempts);
        if (params.requestId === 'retry' && attempts === 1) throw new Error('Body is not ready');
        return {
          body: JSON.stringify({ feeds: [{ photo: { id: params.requestId } }] }),
          base64Encoded: false,
        };
      },
    },
  };

  const cdp = await import(new URL('../../extension/cdp.js?capture-test', import.meta.url));
  cdp.registerListeners();
  await cdp.startKuaishouLikedCapture(7);

  const emit = async (method, params) => {
    await Promise.all(onEvent.listeners.map((listener) => listener({ tabId: 7 }, method, params)));
  };
  const likedUrl = 'https://www.kuaishou.com/rest/v/feed/liked?pcursor=1';

  await emit('Network.responseReceived', {
    requestId: 'first',
    response: { url: likedUrl, status: 200 },
  });
  await emit('Network.responseReceived', {
    requestId: 'ignored',
    response: { url: 'https://www.kuaishou.com/rest/v/feed/list', status: 200 },
  });

  assert.equal(calls.filter((call) => call.method === 'Network.getResponseBody').length, 0);
  assert.equal(cdp.readKuaishouLikedCapture(7).pending, 1);

  await emit('Network.loadingFinished', { requestId: 'first' });
  await emit('Network.responseReceived', {
    requestId: 'retry',
    response: { url: likedUrl, status: 200 },
  });
  await emit('Network.loadingFinished', { requestId: 'retry' });

  const capture = cdp.readKuaishouLikedCapture(7);
  assert.equal(capture.matched, 2);
  assert.equal(capture.completed, 2);
  assert.equal(capture.pending, 0);
  assert.equal(capture.failed, 0);
  assert.deepEqual(capture.responses.map((item) => item.data.feeds[0].photo.id), ['first', 'retry']);
  assert.equal(bodyAttempts.get('retry'), 2);

  for (const listener of onDetach.listeners) listener({ tabId: 7 });
  assert.equal(cdp.readKuaishouLikedCapture(7).detached, true);
  assert.equal(cdp.readKuaishouLikedCapture(7).responses.length, 2);
});
