const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const load = require('./loadTypescript.cjs');

function setup(subject = 'apple-subject') {
    const calls = [];
    const auth = {
        currentUser: { uid: 'apple', isAnonymous: false, providerData: [{ providerId: 'apple.com', uid: 'apple-subject' }] },
        revokeToken: async code => { calls.push(['revoke', code]); },
    };
    const api = load(path.resolve(__dirname, '../managers/appleAccountDeletion.ts'), {
        '@react-native-firebase/auth': {
            getAuth: () => auth, AppleAuthProvider: { credential: () => 'credential' },
            reauthenticateWithCredential: async user => { calls.push(['reauth', user.uid]); },
        },
        'expo-crypto': { randomUUID: () => 'nonce', CryptoDigestAlgorithm: { SHA256: 'SHA256' }, digestStringAsync: async () => 'hash' },
        'expo-apple-authentication': { signInAsync: async options => ({
            state: options.state, user: subject, identityToken: 'identity-proof', authorizationCode: 'code',
        }) },
    });
    return { api, calls };
}

test('deletion reauthenticates and revokes only the current Apple account', async () => {
    const { api, calls } = setup();
    await api.authorizeAppleDeletion('apple');
    assert.deepEqual(calls, [['reauth', 'apple'], ['revoke', 'code']]);
});

test('selecting a different Apple account never reauthenticates or revokes it', async () => {
    const { api, calls } = setup('other-subject');
    await assert.rejects(api.authorizeAppleDeletion('apple'), /一致しません/);
    assert.deepEqual(calls, []);
});
