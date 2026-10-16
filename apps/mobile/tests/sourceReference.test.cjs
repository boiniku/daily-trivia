const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');

function setup({ failToOpen = false } = {}) {
    const opened = [];
    const alerts = [];
    const { default: SourceReference } = load(path.resolve(__dirname, '../components/SourceReference.tsx'), {
        react: { default: require('react') },
        'react-native': {
            View: 'View', Text: 'Text', Pressable: 'Pressable',
            StyleSheet: { create: styles => styles },
            Linking: { openURL: async url => {
                opened.push(url);
                if (failToOpen) throw new Error('Browser unavailable');
            } },
            Alert: { alert: (...args) => alerts.push(args) },
        },
        '@expo/vector-icons': { Ionicons: 'Icon' },
        '../constants/Colors': { Colors: { light: {} } },
        '../utils/photoAttribution': load(path.resolve(__dirname, '../utils/photoAttribution.ts')),
    });
    return { render: source => SourceReference({ source }), opened, alerts };
}

function elements(node) {
    if (node == null || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(elements);
    return [node, ...elements(node.props?.children)];
}

function textContent(node) {
    if (node == null) return '';
    if (Array.isArray(node)) return node.map(textContent).join('');
    if (typeof node === 'object') return textContent(node.props?.children);
    return String(node);
}


test('credits are compact and expose the complete attribution only on request', () => {
    const app = setup();
    const credit = '写真：User:HarJIT / Emergency exit UK 010.jpg / CC BY 4.0 / Wikimedia Commons経由 / © HarJIT / Own work / 加工：トリミング・縮小\nhttps://commons.wikimedia.org/wiki/File:Emergency_exit.jpg\nhttps://creativecommons.org/licenses/by/4.0/';
    const tree = app.render(credit);
    assert.match(textContent(tree), /User:HarJIT.*CC BY 4\.0.*加工あり/);
    assert.doesNotMatch(textContent(tree), /https:|Emergency exit|Own work|©/);
    assert.deepEqual(app.alerts, []);
    elements(tree).find(element => element.props?.accessibilityRole === 'button').props.onPress();
    assert.equal(app.alerts[0][1], credit);
    assert.deepEqual(app.alerts[0][2].map(button => button.text), ['元の写真', 'ライセンス', '閉じる']);
});

test('source and license links are opened only from the attribution details', async () => {
    const app = setup();
    const source = '写真：作者 / Title / CC BY-SA 3.0\nhttps://example.com/source\nhttps://creativecommons.org/licenses/by-sa/3.0/';
    const button = elements(app.render(source)).find(element => element.props?.accessibilityRole === 'button');
    button.props.onPress();
    assert.ok(app.alerts[0][1].includes('Title'));
    assert.deepEqual(app.opened, []);
    await app.alerts[0][2][0].onPress();
    await app.alerts[0][2][1].onPress();
    assert.deepEqual(app.opened, ['https://example.com/source', 'https://creativecommons.org/licenses/by-sa/3.0/']);
});

test('URL-only and custom credits retain their complete text in the details', () => {
    const app = setup();
    for (const source of ['https://example.com/photo?a=1', '撮影：山田太郎 / 提供：観光協会']) {
        const tree = app.render(source);
        assert.doesNotMatch(textContent(tree), /https:/);
        elements(tree).find(element => element.props?.accessibilityRole === 'button').props.onPress();
        assert.equal(app.alerts.at(-1)[1], source);
    }
});

test('photos without a source omit attribution entirely', () => {
    const app = setup();
    for (const source of [undefined, null, '', '  ']) assert.equal(app.render(source), null);
});

test('unsupported protocols and credentialed URLs never become source links', () => {
    const app = setup();
    for (const source of ['javascript:alert(1)', 'file:///local/file', 'https://', 'https://user:pass@example.com']) {
        const tree = app.render(source);
        elements(tree).find(element => element.props?.accessibilityRole === 'button').props.onPress();
        assert.deepEqual(app.alerts.at(-1)[2].map(button => button.text), ['閉じる']);
    }
    assert.deepEqual(app.opened, []);
});

test('failure to open a source is reported without crashing', async () => {
    const app = setup({ failToOpen: true });
    elements(app.render('http://example.com/source')).find(element => element.props?.accessibilityRole === 'button').props.onPress();
    await app.alerts[0][2][0].onPress();
    assert.equal(app.alerts[1][0], '写真の出典を開けませんでした');
});
