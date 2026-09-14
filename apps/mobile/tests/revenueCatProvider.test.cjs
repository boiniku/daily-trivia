const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const load = require('./loadTypescript.cjs');
const identityModule = load(path.resolve(__dirname, '../managers/revenueCatIdentity.ts'));
const resultModule = load(path.resolve(__dirname, '../managers/purchaseRestoreResult.ts'));
const pro = () => ({ entitlements: { active: { pro: { isActive: true } } } });
const free = () => ({ entitlements: { active: {} } });
const flush = () => new Promise(resolve => setImmediate(resolve));

function setup() {
    const state = [], effects = [], alerts = [];
    const auth = { currentUser: { uid: 'apple' } };
    let authCallback, foreground;
    let customer = pro();
    let getInfo = async () => customer;
    let restore = async () => customer;
    const react = {
        createContext: () => ({ Provider: 'Provider' }),
        createElement: (_type, props) => ({ props }),
        useState: initial => {
            const index = state.length;
            state.push(initial);
            return [initial, value => { state[index] = value; }];
        },
        useMemo: factory => factory(),
        useEffect: effect => { effects.push(effect); },
    };
    const purchases = {
        configure: async () => {}, logIn: async () => ({ customerInfo: customer }),
        logOut: async () => free(), isAnonymous: async () => false,
        getCustomerInfo: () => getInfo(), getOfferings: async () => ({ current: null }),
        addCustomerInfoUpdateListener: () => {}, removeCustomerInfoUpdateListener: () => {},
        restorePurchases: () => restore(),
    };
    const key = process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY;
    process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY = 'mock-public-key';
    let provider;
    try {
        const module = load(path.resolve(__dirname, '../contexts/RevenueCatContext.tsx'), {
            react: { __esModule: true, default: react, ...react },
            'react-native': {
                Platform: { OS: 'ios' }, Alert: { alert: (...args) => alerts.push(args) },
                AppState: { addEventListener: (_name, callback) => { foreground = callback; return { remove() {} }; } },
            },
            'react-native-purchases': { __esModule: true, default: purchases },
            '@react-native-firebase/auth': {
                getAuth: () => auth, onAuthStateChanged: (_auth, callback) => { authCallback = callback; return () => {}; },
            },
            '../managers/revenueCatIdentity': identityModule,
            '../managers/purchaseRestoreResult': resultModule,
        });
        provider = module.RevenueCatProvider({ children: null });
    } finally {
        if (key === undefined) delete process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY;
        else process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY = key;
    }
    const cleanup = effects.map(effect => effect());
    return {
        state, alerts, actions: provider.props.value,
        async start() { authCallback(auth.currentUser); await flush(); },
        foreground: () => foreground('active'),
        getInfo: fn => { getInfo = fn; },
        restore: fn => { restore = fn; },
        customer: info => { customer = info; },
        close: () => cleanup.forEach(fn => fn?.()),
    };
}

test('provider retains Pro on a failed same-user foreground refresh', async t => {
    const app = setup(); t.after(app.close);
    await app.start();
    assert.equal(app.state[0], true);
    app.getInfo(async () => { throw new Error('offline'); });
    app.foreground();
    await flush();
    assert.equal(app.state[0], true);
    assert.equal(app.state[2], false);
    await app.actions.restorePurchases();
    assert.equal(app.alerts.at(-1)[0], '復元完了');
});

test('provider shows successful restoration when foreground event arrives during restore', async t => {
    const app = setup(); t.after(app.close);
    app.customer(free());
    await app.start();
    let release;
    app.restore(() => new Promise(resolve => { release = resolve; }));
    const operation = app.actions.restorePurchases();
    await flush();
    app.customer(pro());
    app.foreground();
    release(pro());
    await operation;
    await flush();
    assert.equal(app.state[0], true);
    assert.deepEqual(app.alerts.map(item => item[0]), ['復元完了']);
});

test('provider reports no active purchase instead of success when restore returns no Pro', async t => {
    const app = setup(); t.after(app.close);
    await app.start();
    app.restore(async () => free());
    await app.actions.restorePurchases();
    assert.equal(app.state[0], false);
    assert.equal(app.alerts.at(-1)[0], '有効な購入が見つかりませんでした');
});

test('provider reports restore network failure without dropping confirmed Pro', async t => {
    const app = setup(); t.after(app.close);
    await app.start();
    app.restore(async () => { throw new Error('offline'); });
    await app.actions.restorePurchases();
    assert.equal(app.state[0], true);
    assert.deepEqual(app.alerts.map(item => item[0]), ['復元エラー']);
});
