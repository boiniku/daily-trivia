const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const { createRevenueCatIdentity } = require('./loadTypescript.cjs')(path.resolve(__dirname, '../managers/revenueCatIdentity.ts'));

function setup(overrides = {}) {
    const calls = [], published = [];
    const sdk = {
        configure: async () => { calls.push('configure'); },
        logIn: async (id) => { calls.push(id); return { customerInfo: id }; },
        logOut: async () => 'anonymous', isAnonymous: async () => false,
        getCustomerInfo: async () => 'anonymous', ...overrides,
    };
    return { calls, published, identity: createRevenueCatIdentity(sdk, 'public-sdk-key', info => published.push(info)) };
}

test('restored Apple identity waits for configure and precedes purchase requests', async () => {
    const { identity, calls, published } = setup();
    const login = identity.setIdentity('apple');
    const purchase = identity.run(async () => { calls.push('purchase'); });
    await Promise.all([login, purchase]);
    assert.deepEqual(calls, ['configure', 'apple', 'purchase']);
    assert.deepEqual(published, [null, 'apple']);
});

test('late results from an old account never publish its entitlements', async () => {
    let release;
    const { identity, published } = setup({ logIn: (id) => id === 'a'
        ? new Promise(resolve => { release = () => resolve({ customerInfo: 'a-pro' }); })
        : Promise.resolve({ customerInfo: 'b-free' }) });
    const a = identity.setIdentity('a');
    while (!release) await new Promise(resolve => setImmediate(resolve));
    const b = identity.setIdentity('b');
    release();
    await Promise.all([a, b]);
    assert.equal(published.includes('a-pro'), false);
    assert.equal(published.at(-1), 'b-free');
});

test('failed identity sync rejects purchases and a subsequent retry recovers', async () => {
    let fail = true;
    const { identity } = setup({ logIn: async () => {
        if (fail) throw new Error('offline');
        return { customerInfo: 'pro' };
    } });
    await assert.rejects(identity.setIdentity('apple'), /offline/);
    let purchased = false;
    await assert.rejects(identity.run(async () => { purchased = true; }), /購入情報の連携/);
    assert.equal(purchased, false);
    fail = false;
    await identity.setIdentity('apple');
    assert.equal(await identity.run(async () => 'restored'), 'restored');
});

test('SDK identity cannot change during an in-progress purchase', async () => {
    const { identity, calls } = setup();
    await identity.setIdentity('a');
    let release;
    const purchase = identity.run(() => new Promise(resolve => { release = resolve; }));
    while (!release) await new Promise(resolve => setImmediate(resolve));
    const switchAccount = identity.setIdentity('b');
    const rejected = assert.rejects(purchase, /アカウントが切り替わりました/);
    assert.equal(calls.includes('b'), false);
    release('purchase-finished');
    await Promise.all([rejected, switchAccount]);
    assert.equal(calls.at(-1), 'b');
});

test('same-user refresh failure preserves confirmed Pro and allows restore retry', async () => {
    const { identity, published, calls } = setup({
        logIn: async () => ({ customerInfo: 'pro' }),
        getCustomerInfo: async () => { throw new Error('offline'); },
    });
    await identity.setIdentity('apple');
    await assert.rejects(identity.setIdentity('apple'), /offline/);
    assert.deepEqual(published, [null, 'pro']);
    assert.equal(await identity.run(async () => 'restored-pro'), 'restored-pro');
    assert.deepEqual(calls, ['configure']);
});

test('same-user foreground during restore does not invalidate its successful result', async () => {
    const { identity, published } = setup({
        getCustomerInfo: async () => 'pro',
    });
    await identity.setIdentity('apple');
    let release;
    const restore = identity.run(() => new Promise(resolve => { release = resolve; }));
    while (!release) await new Promise(resolve => setImmediate(resolve));
    const foreground = identity.setIdentity('apple');
    release('pro');
    const result = await restore;
    identity.accept(result);
    await foreground;
    assert.equal(result, 'pro');
    assert.equal(published.at(-1), 'pro');
    assert.equal(published.filter(info => info === null).length, 1);
});

test('a confirmed expiry on same-user refresh still removes Pro', async () => {
    const { identity, published } = setup({
        logIn: async () => ({ customerInfo: 'pro' }),
        getCustomerInfo: async () => 'expired',
    });
    await identity.setIdentity('apple');
    await identity.setIdentity('apple');
    assert.deepEqual(published, [null, 'pro', 'expired']);
});

test('switching accounts clears Pro even when the new account cannot be loaded', async () => {
    const { identity, published } = setup({ logIn: async id => {
        if (id === 'b') throw new Error('offline');
        return { customerInfo: 'a-pro' };
    } });
    await identity.setIdentity('a');
    await assert.rejects(identity.setIdentity('b'), /offline/);
    assert.deepEqual(published, [null, 'a-pro', null]);
    await assert.rejects(identity.run(async () => 'must not run'), /購入情報の連携/);
});

test('repeated auth notification during initial login does not invalidate queued restore', async () => {
    let release;
    const { identity, published } = setup({
        logIn: () => new Promise(resolve => { release = () => resolve({ customerInfo: 'pro' }); }),
        getCustomerInfo: async () => 'pro',
    });
    const login = identity.setIdentity('apple');
    while (!release) await new Promise(resolve => setImmediate(resolve));
    const restore = identity.run(async () => 'restored');
    const repeat = identity.setIdentity('apple');
    release();
    assert.equal(await restore, 'restored');
    await Promise.all([login, repeat]);
    assert.equal(published.filter(info => info === null).length, 1);
});

test('logout cannot reuse the previous account entitlement', async () => {
    const { identity, published } = setup();
    await identity.setIdentity('apple');
    await identity.setIdentity(null);
    assert.deepEqual(published, [null, 'apple', null, 'anonymous']);
});
