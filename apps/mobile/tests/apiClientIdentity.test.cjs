const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');

const firebaseUser = { uid: 'apple-a' };
const originalLoad = Module._load;
const originalFetch = global.fetch;
const sentRequests = [];

Module._load = function load(request, parent, isMain) {
    if (request === '@react-native-firebase/auth') {
        return {
            getAuth: () => ({ currentUser: firebaseUser }),
            getIdToken: async () => 'verified-token',
            signInAnonymously: async () => ({ user: firebaseUser }),
        };
    }
    if (request === '../constants/Config') {
        return { Config: { APP_VERSION: '1.1.1', APP_ENV: 'production', API_VERSION: '1' } };
    }
    return originalLoad.call(this, request, parent, isMain);
};
global.fetch = async (url, options) => {
    sentRequests.push({ url, options });
    return { ok: true };
};

const file = path.resolve(__dirname, '../utils/apiClient.ts');
const output = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const apiModule = new Module(file, module);
apiModule.filename = file;
apiModule.paths = module.paths;
apiModule._compile(output, file);
const { fetchWithToken } = apiModule.exports;

test.after(() => {
    Module._load = originalLoad;
    global.fetch = originalFetch;
});

test('sync is blocked if Firebase changed to a different user', async () => {
    await assert.rejects(
        fetchWithToken('https://example.test', {}, 'apple-b'),
        /Authenticated user changed/,
    );
    assert.equal(sentRequests.length, 0);
});

test('sync is sent only for the matching Firebase user', async () => {
    await fetchWithToken('https://example.test', {}, 'apple-a');
    assert.equal(sentRequests.length, 1);
    assert.equal(sentRequests[0].options.headers.Authorization, 'Bearer verified-token');
});
