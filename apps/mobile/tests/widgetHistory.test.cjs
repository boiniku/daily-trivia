const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');

const trivia = [
    { id: 1, title: 'First', content: 'First fact' },
    { id: 2, title: 'Second', content: 'Second fact' },
    { id: 3, title: 'Third', content: 'Third fact' },
];

function freezeLocalTime(t, hour = 12, minute = 0) {
    t.mock.timers.enable({ apis: ['Date'], now: new Date(2026, 9, 22, hour, minute).getTime() });
}

function setupWidget({ platform = 'ios', installed = true, nativeAvailable = true } = {}) {
    const state = {
        installed,
        installationChecks: 0,
        auth: { currentUser: { uid: 'user-a' } },
        requests: [],
        writes: [],
        preferences: new Map(),
        response: { ok: true, json: async () => trivia },
        token: async () => 'firebase-token',
    };
    const preferences = {
        async setName(value) { state.group = value; },
        async set(key, value) {
            state.writes.push({ key, value });
            state.preferences.set(key, value);
        },
    };
    const native = nativeAvailable ? {
        async getIsWidgetInstalled() {
            state.installationChecks++;
            if (state.installed instanceof Error) throw state.installed;
            return typeof state.installed === 'function' ? state.installed() : state.installed;
        },
    } : {};
    state.utility = load(path.resolve(__dirname, '../utils/widgetSync.ts'), {
        'react-native': { Platform: { OS: platform } },
        'react-native-default-preference': { __esModule: true, default: preferences },
        '@react-native-firebase/auth': {
            getAuth: () => state.auth,
            getIdToken: (...args) => state.token(...args),
        },
        '../modules/widget-control': native,
        '../constants/Config': { Config: { BACKEND_URL: 'https://example.test' } },
        './apiClient': {
            async fetchWithToken(url, options, expectedUserId) {
                state.requests.push({ url, options, expectedUserId });
                return typeof state.response === 'function' ? state.response() : state.response;
            },
        },
    });
    return state;
}

test('an installed widget registers its daily batch and saves the same batch to its shared cache', async (t) => {
    freezeLocalTime(t);
    const app = setupWidget();
    app.auth.currentUser.uid = 'user / a';

    assert.equal(await app.utility.syncInstalledWidgetTrivia('user / a'), true);
    assert.equal(app.requests.length, 1);
    const request = app.requests[0];
    const url = new URL(request.url);
    assert.equal(url.pathname, '/trivia/widget');
    assert.equal(url.searchParams.get('user_id'), 'user / a');
    assert.equal(url.searchParams.get('date'), '2026-10-22');
    assert.equal(url.searchParams.get('widget_installed'), 'true');
    assert.deepEqual(request.options, { headers: { 'Cache-Control': 'no-cache' } });
    assert.equal(request.expectedUserId, 'user / a');
    assert.equal(app.group, 'group.com.dailytrivia.app');
    assert.equal(app.preferences.get('user_id'), 'user / a');
    assert.equal(app.preferences.get('firebase_token'), 'firebase-token');
    assert.deepEqual(JSON.parse(app.preferences.get('daily_trivia')),
        trivia.map(item => ({ ...item, date: '2026-10-22' })));
});

test('an absent widget, Android, an older native build, and a failed installation check never register history', async (t) => {
    freezeLocalTime(t);
    for (const config of [
        { installed: false },
        { platform: 'android' },
        { nativeAvailable: false },
        { installed: new Error('Native lookup failed') },
    ]) {
        const app = setupWidget(config);
        assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), false);
        assert.equal(app.requests.length, 0);
        assert.equal(app.writes.length, 0);
    }
});

test('missing, signed-out, or different users cannot register widget history', async (t) => {
    freezeLocalTime(t);
    for (const [userId, currentUser] of [
        ['', { uid: 'user-a' }],
        ['user-a', null],
        ['user-a', { uid: 'user-b' }],
    ]) {
        const app = setupWidget();
        app.auth.currentUser = currentUser;
        assert.equal(await app.utility.syncInstalledWidgetTrivia(userId), false);
        assert.equal(app.requests.length, 0);
        assert.equal(app.writes.length, 0);
    }
});

test('an account change while checking installed widgets prevents the API request', async (t) => {
    freezeLocalTime(t);
    const app = setupWidget();
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    app.installed = () => gate;
    const syncing = app.utility.syncInstalledWidgetTrivia('user-a');
    assert.equal(app.installationChecks, 1);
    app.auth.currentUser = { uid: 'user-b' };
    release(true);
    assert.equal(await syncing, false);
    assert.equal(app.requests.length, 0);
    assert.equal(app.writes.length, 0);
    assert.equal(app.group, undefined);
});

test('widget history uses the local 2 AM date boundary and refuses historical dates', async (t) => {
    freezeLocalTime(t, 1, 59);
    const app = setupWidget();
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a', '2026-10-22'), false);
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a', '2026-10-20'), false);
    assert.equal(app.requests.length, 0);
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), true);
    assert.equal(new URL(app.requests[0].url).searchParams.get('date'), '2026-10-21');
    assert.ok(JSON.parse(app.preferences.get('daily_trivia')).every(item => item.date === '2026-10-21'));
});

test('2 AM begins the new widget history day', async (t) => {
    freezeLocalTime(t, 2);
    const app = setupWidget();
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), true);
    assert.equal(new URL(app.requests[0].url).searchParams.get('date'), '2026-10-22');
});

test('simultaneous widget registrations share a request and later calls recheck widget removal', async (t) => {
    freezeLocalTime(t);
    const app = setupWidget();
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    app.response = async () => {
        await gate;
        return { ok: true, json: async () => trivia };
    };
    const first = app.utility.syncInstalledWidgetTrivia('user-a');
    const second = app.utility.syncInstalledWidgetTrivia('user-a', '2026-10-22');
    await new Promise(resolve => setImmediate(resolve));
    try {
        assert.equal(app.requests.length, 1);
    } finally {
        release();
    }
    assert.deepEqual(await Promise.all([first, second]), [true, true]);
    app.installed = false;
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), false);
    assert.equal(app.installationChecks, 3);
    assert.equal(app.requests.length, 1);
    app.installed = true;
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), true);
    assert.equal(app.requests.length, 2);
});

test('HTTP failures and malformed widget responses remain retryable without caching them', async (t) => {
    freezeLocalTime(t);
    for (const response of [
        { ok: false, status: 503 },
        { ok: true, json: async () => { throw new Error('Invalid JSON'); } },
        { ok: true, json: async () => ({ trivia }) },
        { ok: true, json: async () => [{ id: 1, title: 'Missing content' }] },
    ]) {
        const app = setupWidget();
        app.response = response;
        await assert.rejects(app.utility.syncInstalledWidgetTrivia('user-a'));
        assert.equal(app.writes.length, 0);
        app.response = { ok: true, json: async () => trivia };
        assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), true);
        assert.equal(app.requests.length, 2);
    }
});

test('an empty widget batch reports no data and is retried on the next call', async (t) => {
    freezeLocalTime(t);
    const app = setupWidget();
    app.response = { ok: true, json: async () => [] };
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), false);
    assert.equal(app.writes.length, 0);
    app.response = { ok: true, json: async () => trivia };
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), true);
    assert.equal(app.requests.length, 2);
});

test('an account change during a widget request cannot overwrite the new account cache', async (t) => {
    freezeLocalTime(t);
    const app = setupWidget();
    app.preferences.set('daily_trivia', 'new-account-cache');
    app.response = { ok: true, json: async () => {
        app.auth.currentUser = { uid: 'user-b' };
        return trivia;
    } };
    assert.equal(await app.utility.syncInstalledWidgetTrivia('user-a'), false);
    assert.equal(app.writes.length, 0);
    assert.equal(app.preferences.get('daily_trivia'), 'new-account-cache');
});

test('cache preparation alone does not register history and preserves an explicit batch date', async (t) => {
    freezeLocalTime(t);
    const app = setupWidget({ installed: false });
    await app.utility.syncTriviaToWidget([...trivia, { id: 4, title: 'Fourth', content: 'Fourth fact' }], 'user-a', '2026-10-21');
    assert.equal(app.requests.length, 0);
    assert.equal(app.installationChecks, 0);
    assert.deepEqual(JSON.parse(app.preferences.get('daily_trivia')),
        trivia.map(item => ({ ...item, date: '2026-10-21' })));
});

test('cache preparation also defaults to the local 2 AM day', async (t) => {
    freezeLocalTime(t, 1, 59);
    const app = setupWidget();
    await app.utility.syncTriviaToWidget(trivia, 'user-a');
    assert.ok(JSON.parse(app.preferences.get('daily_trivia')).every(item => item.date === '2026-10-21'));
});

test('an account change while obtaining the widget token prevents every native cache write', async (t) => {
    freezeLocalTime(t);
    const app = setupWidget();
    app.preferences.set('daily_trivia', 'new-account-cache');
    app.preferences.set('user_id', 'user-b');
    app.preferences.set('firebase_token', 'new-account-token');
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    app.token = () => gate;
    const syncing = app.utility.syncTriviaToWidget(trivia, 'user-a');
    app.auth.currentUser = { uid: 'user-b' };
    release('old-account-token');
    await syncing;
    assert.equal(app.group, undefined);
    assert.deepEqual(app.writes, []);
    assert.equal(app.preferences.get('daily_trivia'), 'new-account-cache');
    assert.equal(app.preferences.get('user_id'), 'user-b');
    assert.equal(app.preferences.get('firebase_token'), 'new-account-token');
});

for (const [name, nativeModule, expected] of [
    ['a missing native module', null, false],
    ['an older binary without installation detection', {}, false],
    ['an installed-widget false result', { getIsWidgetInstalled: async () => false }, false],
    ['an installed-widget true result', { getIsWidgetInstalled: async () => true }, true],
    ['a native lookup exception', { getIsWidgetInstalled: async () => { throw new Error('Native lookup failed'); } }, false],
]) {
    test(`the real widget bridge safely handles ${name}`, async () => {
        const bridge = load(path.resolve(__dirname, '../modules/widget-control/index.ts'), {
            'expo-modules-core': { requireOptionalNativeModule(name) {
                assert.equal(name, 'WidgetControl');
                return nativeModule;
            } },
        });
        assert.equal(await bridge.getIsWidgetInstalled(), expected);
    });
}

test('the real widget bridge accepts only a boolean true from native installation detection', async () => {
    for (const value of ['true', 'false', 1, 0, {}, null, undefined]) {
        const bridge = load(path.resolve(__dirname, '../modules/widget-control/index.ts'), {
            'expo-modules-core': { requireOptionalNativeModule: () => ({
                getIsWidgetInstalled: async () => value,
            }) },
        });
        assert.equal(await bridge.getIsWidgetInstalled(), false);
    }
});

function setupBackground({ userId = 'user-a', syncResult = false, error = null } = {}) {
    const app = { calls: [], directRequests: [] };
    const results = { NoData: 'no-data', NewData: 'new-data', Failed: 'failed' };
    load(path.resolve(__dirname, '../tasks/backgroundFetch.ts'), {
        'expo-task-manager': { defineTask(name, callback) { app.name = name; app.run = callback; } },
        'expo-background-fetch': { BackgroundFetchResult: results },
        '@react-native-async-storage/async-storage': { __esModule: true, default: {
            async getItem(key) { assert.equal(key, 'user_id'); return userId; },
        } },
        '../utils/widgetSync': { async syncInstalledWidgetTrivia(...args) {
            app.calls.push(args);
            if (error) throw error;
            return syncResult;
        } },
        '../utils/apiClient': { async fetchWithToken(...args) {
            app.directRequests.push(args);
            throw new Error('Background task must use the installed-widget gate');
        } },
        '../constants/Config': { Config: { BACKEND_URL: 'https://example.test' } },
    });
    return { ...app, results };
}

test('background refresh without a widget returns NoData without a direct today request', async () => {
    const app = setupBackground();
    assert.equal(app.name, 'BACKGROUND_TRIVIA_FETCH');
    assert.equal(await app.run(), app.results.NoData);
    assert.deepEqual(app.calls, [['user-a']]);
    assert.deepEqual(app.directRequests, []);
});

test('background refresh reports NewData only when installed-widget synchronization succeeds', async () => {
    const app = setupBackground({ syncResult: true });
    assert.equal(await app.run(), app.results.NewData);
    assert.deepEqual(app.calls, [['user-a']]);
    assert.deepEqual(app.directRequests, []);
});

test('background refresh reports Failed when widget synchronization fails', async () => {
    const app = setupBackground({ error: new Error('Offline') });
    assert.equal(await app.run(), app.results.Failed);
    assert.deepEqual(app.calls, [['user-a']]);
    assert.deepEqual(app.directRequests, []);
});

test('background refresh without a stored user skips widget synchronization', async () => {
    const app = setupBackground({ userId: null });
    assert.equal(await app.run(), app.results.NoData);
    assert.deepEqual(app.calls, []);
    assert.deepEqual(app.directRequests, []);
});
