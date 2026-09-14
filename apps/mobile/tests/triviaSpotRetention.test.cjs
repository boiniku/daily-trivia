const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');

function setup(remote, cached, offline = false) {
    let saved = cached;
    const { getTriviaSpots } = load(path.resolve(__dirname, '../data/triviaSpots.ts'), {
        '../constants/Config': { getBackendUrl: () => 'https://example.test' },
        '../utils/apiClient': { fetchWithToken: async () => {
            if (offline) throw new Error('offline');
            return { ok: true, json: async () => remote };
        } },
        '../managers/TriviaSpotCache': { TriviaSpotCache: {
            read: async () => saved,
            save: async spots => { saved = spots; },
        } },
    });
    return { getTriviaSpots, read: () => saved };
}

test('partial and empty server lists preserve old content without copying account unlock flags', async () => {
    for (const remote of [[], [{ id: 'map_2', title: 'new' }]]) {
        const app = setup(remote, [{ id: 'map_1', title: 'collected', isUnlocked: true }]);
        const spots = await app.getTriviaSpots();
        const old = spots.find(spot => spot.id === 'map_1');
        assert.equal(old.title, 'collected');
        assert.equal(old.isArchived, true);
        assert.equal(old.isUnlocked, false);
        assert.equal(old.unlockedAt, null);
        assert.deepEqual(app.read(), spots);
    }
});

test('fresh metadata replaces matching cached IDs without duplicating them', async () => {
    const app = setup([{ id: 'map_1', title: 'current', isArchived: false }],
        [{ id: 'map_1', title: 'old', isArchived: true }]);
    const spots = await app.getTriviaSpots();
    assert.equal(spots.length, 1);
    assert.equal(spots[0].title, 'current');
    assert.equal(spots[0].isArchived, false);
});

test('offline or invalid server responses leave the existing cache intact', async () => {
    for (const offline of [true, false]) {
        const cached = [{ id: 'map_1', title: 'collected' }];
        const app = setup({}, cached, offline);
        assert.deepEqual(await app.getTriviaSpots(), cached);
        assert.deepEqual(app.read(), cached);
    }
});
