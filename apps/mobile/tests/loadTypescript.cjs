const fs = require('node:fs');
const Module = require('node:module');
const ts = require('typescript');

module.exports = function loadTypescript(file, mocks = {}) {
    const loaded = new Module(file, module);
    loaded.filename = file;
    loaded.paths = module.paths;
    const original = loaded.require.bind(loaded);
    loaded.require = (name) => Object.hasOwn(mocks, name) ? mocks[name] : original(name);
    loaded._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
    }).outputText, file);
    return loaded.exports;
};
