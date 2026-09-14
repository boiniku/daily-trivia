const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const load = require('./loadTypescript.cjs');

function setup() {
    const calls = [];
    let fail = false;
    const api = load(path.resolve(__dirname, '../managers/AccountMigration.ts'), {
        '../constants/Config': { Config: { BACKEND_URL: 'https://example.test' } },
        '../utils/apiClient': { fetchWithToken: async (url, options, uid) => {
            calls.push({ url, options, uid });
            if (fail) throw new Error('offline');
            return { ok: true, json: async () => ({ merged_guest_ids: ['guest'] }) };
        } },
        './TriviaUnlockManager': { TriviaUnlockManager: {
            isAccountDeletionPending: async () => false,
            getUnlockedRecords: async () => ({}), syncUnlockedRecords: async () => true,
            suspendUser: async () => calls.push('suspend'), resumeUser: () => calls.push('resume'),
            transferUserRecords: async (from, to) => calls.push({ from, to }),
        } },
    });
    return { api, calls, setFailure: value => { fail = value; } };
}

test('preparation binds the Apple subject to authenticated guest without storing ID tokens', async () => {
    const { api, calls } = setup();
    await api.prepareAppleMigration('guest', 'apple-subject');
    const request = calls.find(item => item.url);
    assert.equal(request.uid, 'guest');
    assert.deepEqual(JSON.parse(request.options.body), { apple_subject: 'apple-subject' });
});

test('preparation failure resumes source and never transfers its local records', async () => {
    const { api, calls, setFailure } = setup();
    setFailure(true);
    await assert.rejects(api.prepareAppleMigration('guest', 'apple-subject'), /offline/);
    assert.ok(calls.includes('resume'));
    assert.equal(calls.some(item => item.from), false);
});

test('failed migration can retry without a guest token and transfers only after success', async () => {
    const { api, calls, setFailure } = setup();
    setFailure(true);
    await assert.rejects(api.finishAppleMigration('apple'), /offline/);
    assert.equal(calls.some(item => item.from), false);
    setFailure(false);
    await api.finishAppleMigration('apple');
    assert.deepEqual(calls.at(-1), { from: 'guest', to: 'apple' });
    assert.ok(calls.filter(item => item.url).every(item => item.uid === 'apple'));
});
