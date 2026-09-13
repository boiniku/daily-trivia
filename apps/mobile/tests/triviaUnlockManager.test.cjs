const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');

const values = new Map();
const requests = [];
let failNextRequest = false;
const AsyncStorage = {
    async getItem(key) { return values.get(key) ?? null; },
    async setItem(key, value) { values.set(key, value); },
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
                return {
                    ok: true,
                    async json() {
                        return { unlockCounts: {}, spotIdAliases: {}, unlockedRecords: [] };
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
    requests.length = 0;
    failNextRequest = false;
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
