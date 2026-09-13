const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');

const helperPath = path.resolve(__dirname, '../managers/triviaUnlockMerge.ts');
const source = fs.readFileSync(helperPath, 'utf8');
const output = ts.transpileModule(source, {
    compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
    },
}).outputText;
const helperModule = new Module(helperPath, module);
helperModule.filename = helperPath;
helperModule.paths = module.paths;
helperModule._compile(output, helperPath);
const { mergeUnlockRecords } = helperModule.exports;
const { mergeUnlockRecordMaps } = helperModule.exports;

test('anonymous user local history survives a normal app update and empty sync', () => {
    const original = {
        map_1: { id: 'map_1', unlockedAt: '2026-01-01T00:00:00.000Z' },
    };

    const result = mergeUnlockRecords(original, {
        spotIdAliases: {},
        unlockedRecords: [],
    });

    assert.deepEqual(result.records, original);
    assert.equal(result.changed, false);
});

test('Apple user receives server backup while all device records remain', () => {
    const result = mergeUnlockRecords(
        {
            trivia_240: { id: 'trivia_240', unlockedAt: '2025-10-01T00:00:00.000Z' },
            map_1: { id: 'map_1', unlockedAt: '2025-11-01T00:00:00.000Z' },
        },
        {
            spotIdAliases: { trivia_240: 'map_2' },
            unlockedRecords: [
                { id: 'map_3', unlockedAt: '2026-01-01T00:00:00.000Z' },
            ],
        },
    );

    assert.deepEqual(Object.keys(result.records).sort(), ['map_1', 'map_2', 'map_3', 'trivia_240']);
    assert.equal(result.records.map_2.unlockedAt, result.records.trivia_240.unlockedAt);
});

test('server sync never overwrites a device unlock timestamp', () => {
    const deviceTimestamp = '2025-01-01T00:00:00.000Z';
    const result = mergeUnlockRecords(
        { map_1: { id: 'map_1', unlockedAt: deviceTimestamp } },
        { unlockedRecords: [{ id: 'map_1', unlockedAt: '2026-01-01T00:00:00.000Z' }] },
    );

    assert.equal(result.records.map_1.unlockedAt, deviceTimestamp);
    assert.equal(result.changed, false);
});

test('malformed server records cannot corrupt local history', () => {
    const original = {
        map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00.000Z' },
    };
    const result = mergeUnlockRecords(original, {
        unlockedRecords: [
            null,
            { id: 'map_2', unlockedAt: 'invalid' },
        ],
    });

    assert.deepEqual(result.records, original);
});

test('account transfer keeps the earliest timestamp from either ledger', () => {
    const result = mergeUnlockRecordMaps(
        { map_1: { id: 'map_1', unlockedAt: '2026-01-01T00:00:00.000Z' } },
        { map_1: { id: 'map_1', unlockedAt: '2025-01-01T00:00:00.000Z' } },
    );
    assert.equal(result.records.map_1.unlockedAt, '2025-01-01T00:00:00.000Z');
});
