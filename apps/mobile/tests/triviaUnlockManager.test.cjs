const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');

const values = new Map();
const requests = [];
const serverRecords = new Map();
let failNextRequest = false;
let failWriteKey = null;
let responseGate = null;
let responsePayload = null;
const AsyncStorage = {
    async getItem(key) { return values.get(key) ?? null; },
    async setItem(key, value) {
        if (key === failWriteKey) { failWriteKey = null; throw new Error('storage failure'); }
        values.set(key, value);
    },
    async removeItem(key) { values.delete(key); },
};

const originalLoad = Module._load;
const originalTsLoader = require.extensions['.ts'];
Module._load = function load(request, parent, isMain) {
    if (request === '@react-native-async-storage/async-storage') {
        return { __esModule: true, default: AsyncStorage };
    }
    if (request.endsWith('/constants/Config') || request === '../constants/Config') {
        return { getBackendUrl: () => 'https://example.test' };
    }
    if (request.endsWith('/utils/apiClient') || request === '../utils/apiClient') {
        return {
            fetchWithToken: async (_url, options, expectedUserId) => {
                if (failNextRequest) {
                    failNextRequest = false;
                    throw new Error('offline');
                }
                requests.push({ ...JSON.parse(options.body), expectedUserId });
                if (responseGate) await responseGate;
                const ledger = serverRecords.get(expectedUserId) ?? {};
                for (const record of JSON.parse(options.body).records) ledger[record.id] = record;
                serverRecords.set(expectedUserId, ledger);
                return {
                    ok: true,
                    async json() {
                        return responsePayload ?? { unlockCounts: {}, spotIdAliases: {}, unlockedRecords: Object.values(ledger) };
                    },
                };
            },
        };
    }
    return originalLoad.call(this, request, parent, isMain);
};
require.extensions['.ts'] = (module, filename) => {
    const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    module._compile(output, filename);
};

const managerPath = path.resolve(__dirname, '../managers/TriviaUnlockManager.ts');
const { TriviaUnlockManager } = require(managerPath);

test.after(() => {
    Module._load = originalLoad;
    require.extensions['.ts'] = originalTsLoader;
});

test.beforeEach(() => {
    values.clear();
    serverRecords.clear();
    requests.length = 0;
    failNextRequest = false;
    failWriteKey = null;
    responseGate = null;
    responsePayload = null;
    for (const id of ['guest-a', 'apple-a', 'apple-b']) TriviaUnlockManager.resumeUser(id);
});

test('legacy history is claimed once and cannot leak to a second account', async () => {
    const record = { map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00.000Z' } };
    values.set('triviaMapUnlockedRecords', JSON.stringify(record));

    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('guest-a'), record);
    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-b'), {});

    await TriviaUnlockManager.syncUnlockedRecords('apple-b');
    assert.deepEqual(requests[0].records, []);
});

test('guest records transfer locally to Apple without entering another account', async () => {
    const record = { map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00.000Z' } };
    values.set('triviaMapUnlockedRecordsByUserV2:guest-a', JSON.stringify(record));
    values.set('triviaMapUnlockedRecordsLegacyOwnerV2', 'guest-a');

    await TriviaUnlockManager.transferUserRecords('guest-a', 'apple-a');

    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-a'), record);
    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-b'), {});
    assert.equal(values.has('triviaMapUnlockedRecordsByUserV2:guest-a'), false);
    assert.equal(values.get('triviaMapUnlockedRecordsLegacyOwnerV2'), 'apple-a');
});

test('more than one thousand records are uploaded in bounded chunks', async () => {
    const records = Object.fromEntries(Array.from({ length: 1001 }, (_, index) => {
        const id = `map_${index + 1}`;
        return [id, { id, unlockedAt: '2025-01-01T00:00:00.000Z' }];
    }));
    values.set('triviaMapUnlockedRecordsByUserV2:apple-a', JSON.stringify(records));
    values.set('triviaMapUnlockedRecordsLegacyOwnerV2', 'apple-a');

    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), true);
    assert.deepEqual(requests.map((request) => request.records.length), [500, 500, 1]);
    assert.ok(requests.every((request) => request.expectedUserId === 'apple-a'));
});

test('an offline failure retains every local record for the next retry', async () => {
    const record = { map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00.000Z' } };
    values.set('triviaMapUnlockedRecordsByUserV2:apple-a', JSON.stringify(record));
    values.set('triviaMapUnlockedRecordsLegacyOwnerV2', 'apple-a');
    failNextRequest = true;

    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), false);
    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-a'), record);
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), true);
    assert.equal(requests.length, 1);
});

test('explicit account deletion removes scoped and legacy recovery copies', async () => {
    values.set('triviaMapUnlockedRecords', '{"map_1":{"id":"map_1","unlockedAt":"2025-01-01T00:00:00.000Z"}}');
    await TriviaUnlockManager.getUnlockedRecords('apple-a');

    await TriviaUnlockManager.removeUserRecords('apple-a');

    assert.equal(values.has('triviaMapUnlockedRecordsByUserV2:apple-a'), false);
    assert.equal(values.has('triviaMapUnlockedRecords'), false);
    assert.equal(values.has('triviaMapUnlockedRecordsLegacyOwnerV2'), false);
});

test('concurrent reads cannot both claim the legacy ledger', async () => {
    const record = { map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00Z' } };
    values.set('triviaMapUnlockedRecords', JSON.stringify(record));
    const [first, second] = await Promise.all([
        TriviaUnlockManager.getUnlockedRecords('apple-a'),
        TriviaUnlockManager.getUnlockedRecords('apple-b'),
    ]);
    assert.deepEqual(first, record);
    assert.deepEqual(second, {});
    assert.equal(values.get('triviaMapUnlockedRecordsLegacyOwnerV2'), 'apple-a');
});

test('failed legacy copy reserves its owner and resumes without data loss', async () => {
    const record = { map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00Z' } };
    values.set('triviaMapUnlockedRecords', JSON.stringify(record));
    failWriteKey = 'triviaMapUnlockedRecordsByUserV2:apple-a';
    await assert.rejects(TriviaUnlockManager.getUnlockedRecords('apple-a'), /storage failure/);
    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-b'), {});
    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-a'), record);
    assert.equal(values.get('triviaMapUnlockedRecords'), JSON.stringify(record));
});

test('corrupt storage is not silently overwritten by an empty ledger', async () => {
    const key = 'triviaMapUnlockedRecordsByUserV2:apple-a';
    values.set(key, '{broken');
    await assert.rejects(TriviaUnlockManager.unlockTrivia({ id: 'map_2' }, 'apple-a'));
    assert.equal(values.get(key), '{broken');
});

test('a hung upload does not block local unlocks or overwrite concurrent saves', async () => {
    let release;
    responseGate = new Promise(resolve => { release = resolve; });
    responsePayload = { unlockedRecords: [{ id: 'map_3', unlockedAt: '2025-01-01T00:00:00Z' }] };
    const sync = TriviaUnlockManager.syncUnlockedRecords('apple-a');
    while (!requests.length) await new Promise(resolve => setImmediate(resolve));
    try {
        const record = await TriviaUnlockManager.unlockTrivia({ id: 'map_2' }, 'apple-a');
        assert.equal(record.id, 'map_2');
        assert.ok((await TriviaUnlockManager.getUnlockedRecords('apple-a')).map_2);
    } finally { release(); }
    assert.equal(await sync, false, 'concurrent unsent unlock must not be reported as backed up');
    const records = await TriviaUnlockManager.getUnlockedRecords('apple-a');
    assert.ok(records.map_2);
    assert.ok(records.map_3);
});

test('deletion drains an in-flight response and cannot recreate local storage', async () => {
    let release;
    responseGate = new Promise(resolve => { release = resolve; });
    responsePayload = { unlockedRecords: [{ id: 'map_1', unlockedAt: '2025-01-01T00:00:00Z' }] };
    const sync = TriviaUnlockManager.syncUnlockedRecords('apple-a');
    while (!requests.length) await new Promise(resolve => setImmediate(resolve));
    const deletion = TriviaUnlockManager.removeUserRecords('apple-a');
    release();
    await Promise.all([sync, deletion]);
    assert.equal(values.has('triviaMapUnlockedRecordsByUserV2:apple-a'), false);
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), false);
});

test('a persisted pending deletion blocks uploads and new unlocks after restart', async () => {
    values.set('triviaMapAccountDeletionV1:apple-a', 'true');
    TriviaUnlockManager.resumeUser('apple-a'); // Simulate an empty in-memory pause set.
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), false);
    assert.equal(await TriviaUnlockManager.unlockTrivia({ id: 'map_1' }, 'apple-a'), null);
    assert.equal(requests.length, 0);
});

for (const userId of ['guest-a', 'apple-a']) {
    test(`1.1.0 legacy records survive an offline upgrade for ${userId}`, async () => {
        const records = { map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00Z' } };
        const original = JSON.stringify(records);
        values.set('triviaMapUnlockedRecords', original);
        failNextRequest = true;
        assert.equal(await TriviaUnlockManager.syncUnlockedRecords(userId), false);
        assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords(userId), records);
        assert.equal(values.get('triviaMapUnlockedRecords'), original);
    });
}

test('confirmed Apple backup restores legacy unlocks after clearing all device storage', async () => {
    const records = { map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00Z' } };
    values.set('triviaMapUnlockedRecords', JSON.stringify(records));
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), true);
    values.clear(); // Reinstall: no device ledger, ownership marker or cache remains.
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-b'), true);
    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-b'), {});
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), true);
    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-a'), records);
});

test('HTTP 200 with an ignored unlock does not confirm backup or discard the local record', async () => {
    const records = { old_unknown: { id: 'old_unknown', unlockedAt: '2025-01-01T00:00:00Z' } };
    values.set('triviaMapUnlockedRecords', JSON.stringify(records));
    responsePayload = { unlockedRecords: [], spotIdAliases: {} };
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), false);
    assert.deepEqual(await TriviaUnlockManager.getUnlockedRecords('apple-a'), records);
    responsePayload = {};
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), false);
});

test('a server-confirmed canonical alias backs up the legacy record without deleting it', async () => {
    const record = { id: 'tokyo_001', unlockedAt: '2025-01-01T00:00:00Z' };
    values.set('triviaMapUnlockedRecords', JSON.stringify({ tokyo_001: record }));
    responsePayload = {
        unlockedRecords: [{ ...record, id: 'map_1' }],
        spotIdAliases: { tokyo_001: 'map_1' },
    };
    assert.equal(await TriviaUnlockManager.syncUnlockedRecords('apple-a'), true);
    const records = await TriviaUnlockManager.getUnlockedRecords('apple-a');
    assert.deepEqual(records.tokyo_001, record);
    assert.ok(records.map_1);
});
