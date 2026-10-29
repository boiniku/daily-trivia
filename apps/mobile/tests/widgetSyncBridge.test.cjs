const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');
const flush = () => new Promise(resolve => setImmediate(resolve));

function setup({ loading = false, userId = 'user-a', identity = async () => true } = {}) {
    const app = { prepared: [], synced: [], cleared: 0, removed: 0 };
    let effect;
    const { WidgetSyncBridge } = load(path.resolve(__dirname, '../components/WidgetSyncBridge.tsx'), {
        react: { useEffect(fn) { effect = fn; } },
        'react-native': { Platform: { OS: 'ios' }, AppState: { addEventListener(event, fn) { app.foreground = fn; return { remove() { app.removed++; } }; } } },
        '@react-native-firebase/auth': { getAuth: () => ({}), onIdTokenChanged(auth, fn) { app.tokenChanged = fn; return () => { app.removed++; }; } },
        '../contexts/AuthContext': { useAuth: () => ({ loading, userId }) },
        '../utils/widgetSync': {
            async syncWidgetIdentity(id) { app.prepared.push(id); return await identity(id); },
            async syncInstalledWidgetTrivia(id) { app.synced.push(id); return true; },
            async clearSignedOutWidgetIdentity() { app.cleared++; },
        },
    });
    WidgetSyncBridge();
    app.cleanup = effect();
    return app;
}

test('widget credentials are prepared on startup without opening Home, and refreshed on foreground/token events', async () => {
    const app = setup();
    await flush();
    assert.deepEqual(app.prepared, ['user-a']);
    assert.deepEqual(app.synced, ['user-a']);
    app.foreground('background');
    assert.equal(app.prepared.length, 1);
    app.foreground('active');
    await flush();
    app.tokenChanged({ uid: 'user-a' });
    await flush();
    assert.equal(app.prepared.length, 3);
    assert.equal(app.synced.length, 3);
    app.cleanup();
    app.foreground('active');
    assert.equal(app.prepared.length, 3);
    assert.equal(app.removed, 2);
});

test('overlapping foreground/token events share synchronization and an old account cannot continue after cleanup', async () => {
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    const app = setup({ identity: () => gate });
    app.foreground('active');
    app.tokenChanged({ uid: 'user-a' });
    assert.equal(app.prepared.length, 1);
    app.cleanup();
    release(true);
    await flush();
    assert.deepEqual(app.synced, []);
});

test('loading and signed-out users never fetch widget history', async () => {
    const waiting = setup({ loading: true });
    assert.deepEqual(waiting.prepared, []);
    const signedOut = setup({ userId: null });
    await flush();
    assert.equal(signedOut.cleared, 1);
    assert.deepEqual(signedOut.synced, []);
});
