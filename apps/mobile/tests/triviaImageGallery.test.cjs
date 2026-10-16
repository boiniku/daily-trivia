const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');

const images = load(path.resolve(__dirname, '../utils/triviaImages.ts'));

function elements(node) {
    if (node == null || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(elements);
    return [node, ...elements(node.props?.children)];
}

function hookHarness(t) {
    const hooks = [], effects = [];
    let cursor = 0, dirty = true, tree, component, props = {};
    const same = (left, right) => left && right && left.length === right.length && left.every((value, i) => Object.is(value, right[i]));
    const react = {
        createElement: (type, attributes, ...children) => ({ type, props: { ...attributes, children } }),
        useState(initial) {
            const i = cursor++;
            if (!hooks[i]) {
                const slot = { value: typeof initial === 'function' ? initial() : initial };
                slot.set = update => {
                    const next = typeof update === 'function' ? update(slot.value) : update;
                    if (!Object.is(next, slot.value)) { slot.value = next; dirty = true; }
                };
                hooks[i] = slot;
            }
            return [hooks[i].value, hooks[i].set];
        },
        useRef(initial) { const i = cursor++; return hooks[i] ??= { current: initial }; },
        useMemo(factory, deps) {
            const i = cursor++;
            if (!hooks[i] || !same(hooks[i].deps, deps)) hooks[i] = { value: factory(), deps };
            return hooks[i].value;
        },
        useEffect(effect, deps) {
            const i = cursor++;
            if (!hooks[i] || !same(hooks[i].deps, deps)) {
                const previous = hooks[i]; hooks[i] = { deps };
                effects.push(() => { previous?.cleanup?.(); hooks[i].cleanup = effect(); });
            }
        },
    };
    const previousReact = global.React;
    global.React = react;
    t.after(() => {
        for (const slot of hooks) slot?.cleanup?.();
        if (previousReact === undefined) delete global.React; else global.React = previousReact;
    });
    return {
        react: { __esModule: true, default: react, ...react },
        start(value, initial) { component = value; props = initial; },
        update(next) { props = { ...props, ...next }; dirty = true; },
        render(mount = () => {}) {
            do {
                dirty = false; cursor = 0; tree = component(props); mount(tree);
                for (const effect of effects.splice(0)) effect();
            } while (dirty);
            return tree;
        },
    };
}

function gallery(t, initial = {}) {
    const harness = hookHarness(t), scrolls = [];
    const { default: Gallery } = load(path.resolve(__dirname, '../components/TriviaImageGallery.tsx'), {
        react: harness.react,
        'react-native': {
            View: 'View', Text: 'Text', Pressable: 'Pressable', Image: 'Image', FlatList: 'FlatList',
            StyleSheet: { create: styles => styles },
        },
        '../constants/Colors': { Colors: { light: { primary: 'red', subtext: '#666' } } },
        '../constants/Config': { Config: { TRIVIA_IMAGE_R2_BASE_URL: 'https://cdn.example.com/photos/' } },
        '../utils/triviaImages': images,
        './SourceReference': { __esModule: true, default: 'PhotoSource' },
    });
    harness.start(Gallery, { title: '海の雑学', itemKey: 1, imageUrls: ['a.jpg', 'b.jpg', 'c.jpg'], ...initial });
    const render = () => harness.render(tree => {
        const list = elements(tree).find(node => node.type === 'FlatList');
        if (list?.props.ref) list.props.ref.current = { scrollToOffset: options => scrolls.push(options) };
    });
    const list = () => elements(render()).find(node => node.type === 'FlatList');
    const dots = () => elements(render()).filter(node => node.type === 'Pressable');
    const selectedPage = () => dots().findIndex(node => node.props.accessibilityState.selected);
    const layout = width => {
        elements(render()).find(node => node.props?.onLayout).props.onLayout({ nativeEvent: { layout: { width } } });
        render();
    };
    const swipe = offset => {
        list().props.onMomentumScrollEnd({ nativeEvent: { contentOffset: { x: offset } } });
        render();
    };
    return { render, layout, list, dots, selectedPage, swipe, scrolls, update: props => { harness.update(props); render(); } };
}

test('gallery normalization preserves ordered photos, legacy covers and explicit removal', () => {
    assert.deepEqual(images.normalizeTriviaImageUrls([' b.jpg ', 'a.jpg', 'b.jpg', null], 'cover.jpg'), ['b.jpg', 'a.jpg']);
    assert.deepEqual(images.normalizeTriviaImageUrls([], 'old-cover.jpg'), []);
    for (const malformed of [undefined, null, '', '{}', [null, false, ' ']]) {
        assert.deepEqual(images.normalizeTriviaImageUrls(malformed, ' cover.jpg '), ['cover.jpg']);
    }
    assert.deepEqual(images.normalizeTriviaImageUrls(undefined, undefined), []);
    assert.equal(images.normalizeTriviaImageUrls(Array.from({ length: 15 }, (_, i) => `${i}.jpg`)).length, 10);
});

test('route photos decode safely while preserving absent and explicitly empty lists', () => {
    assert.deepEqual(images.parseTriviaImageUrlsParam('["a.jpg","b.jpg"]'), ['a.jpg', 'b.jpg']);
    assert.deepEqual(images.parseTriviaImageUrlsParam(['[]', '["ignored.jpg"]']), []);
    for (const malformed of [undefined, '', '{', '{}', 'null', 'false', '[null]']) {
        assert.equal(images.parseTriviaImageUrlsParam(malformed), undefined);
    }
});

test('R2 keys and full URLs resolve to images without treating other schemes as keys', () => {
    assert.equal(images.resolveTriviaImageUrl('/folder/a.jpg', 'https://cdn.example.com/'), 'https://cdn.example.com/folder/a.jpg');
    assert.equal(images.resolveTriviaImageUrl('https://other.example.com/a.jpg', ''), 'https://other.example.com/a.jpg');
    assert.equal(images.resolveTriviaImageUrl('data:image/png;base64,abc', ''), 'data:image/png;base64,abc');
    assert.equal(images.resolveTriviaImageUrl('javascript:alert(1)', 'https://cdn.example.com'), '');
    assert.equal(images.resolveTriviaImageUrl('key.jpg', ''), '');
});

test('horizontal swipes update the selected dot and accessible photo position', t => {
    const app = gallery(t); app.layout(320);
    assert.equal(app.list().props.horizontal, true);
    assert.equal(app.list().props.pagingEnabled, true);
    assert.equal(app.list().props.initialNumToRender, 1);
    assert.equal(app.selectedPage(), 0);
    app.swipe(320);
    assert.equal(app.selectedPage(), 1);
    assert.ok(elements(app.render()).some(node => node.props?.accessibilityLabel === '全3枚中2枚目の写真'));
    const photo = app.list().props.renderItem({ item: app.list().props.data[1], index: 1 });
    assert.equal(photo.props.source.uri, 'https://cdn.example.com/photos/b.jpg');
    assert.equal(photo.props.accessibilityLabel, '海の雑学の写真 2枚目、全3枚');
    app.swipe(5000); assert.equal(app.selectedPage(), 2);
    app.swipe(-30); assert.equal(app.selectedPage(), 0);
});

test('photo dots navigate to the measured page offset', t => {
    const app = gallery(t); app.layout(375);
    app.dots()[2].props.onPress();
    assert.equal(app.selectedPage(), 2);
    assert.deepEqual(app.scrolls.at(-1), { offset: 750, animated: true });
    assert.deepEqual(app.list().props.getItemLayout(null, 2), { length: 375, offset: 750, index: 2 });
});

test('item changes, reordered photos and rotation reset native offset and selected dot', t => {
    const app = gallery(t); app.layout(320);
    app.swipe(640); const oldList = app.list();
    const oldDot = app.dots()[2];
    app.update({ itemKey: 2 });
    assert.equal(app.selectedPage(), 0);
    assert.deepEqual(app.scrolls.at(-1), { offset: 0, animated: false });
    oldList.props.onMomentumScrollEnd({ nativeEvent: { contentOffset: { x: 640 } } });
    assert.equal(app.selectedPage(), 0, 'a late native event from the previous item must not change the new item');
    const beforeOldTap = app.scrolls.length;
    oldDot.props.onPress();
    assert.equal(app.selectedPage(), 0, 'a late dot tap from the previous item must not change the new item');
    assert.equal(app.scrolls.length, beforeOldTap);
    app.swipe(320);
    app.update({ imageUrls: ['c.jpg', 'a.jpg', 'b.jpg'] });
    assert.equal(app.selectedPage(), 0);
    app.swipe(640); app.layout(640);
    assert.equal(app.selectedPage(), 0);
    assert.deepEqual(app.list().props.getItemLayout(null, 2), { length: 640, offset: 1280, index: 2 });
});

test('single legacy photos omit pagination, while explicit empty photos hide the gallery', t => {
    const app = gallery(t, { imageUrls: undefined, imageUrl: 'old.jpg' }); app.layout(320);
    assert.equal(app.dots().length, 0);
    assert.equal(app.list().props.scrollEnabled, false);
    assert.deepEqual(app.list().props.data, ['https://cdn.example.com/photos/old.jpg']);
    app.update({ imageUrls: [] }); assert.equal(app.render(), null);
});

test('photo attribution follows the visible image through swipes, reordering and removal', t => {
    const app = gallery(t, { imageSources: {
        'a.jpg': 'https://museum.example.com/photo-a',
        'https://cdn.example.com/photos/b.jpg': '撮影：山田太郎',
    } });
    const source = () => elements(app.render()).find(node => node.type === 'PhotoSource')?.props.source;
    app.layout(320);
    assert.equal(source(), 'https://museum.example.com/photo-a');
    app.swipe(320);
    assert.equal(source(), '撮影：山田太郎');
    app.swipe(640);
    assert.equal(source(), undefined, 'the CDN URL must not be invented as a photo source');
    app.update({ imageUrls: ['b.jpg', 'a.jpg'] });
    assert.equal(source(), '撮影：山田太郎');
    app.update({ imageSources: {} });
    assert.equal(source(), undefined);
});

test('photo source route data preserves explicit removal and rejects malformed shapes', () => {
    assert.deepEqual(images.parseTriviaImageSourcesParam('{" a.jpg ":" 撮影：山田 ","b.jpg":null}'), { 'a.jpg': '撮影：山田' });
    assert.deepEqual(images.parseTriviaImageSourcesParam('{}'), {});
    for (const value of [undefined, '', '{', '[]', 'null', '"source"']) {
        assert.equal(images.parseTriviaImageSourcesParam(value), undefined);
    }
});

async function detail(t, params, data) {
    const harness = hookHarness(t);
    let resolveRequest;
    const request = new Promise(resolve => { resolveRequest = resolve; });
    const { default: Details } = load(path.resolve(__dirname, '../app/details.tsx'), {
        react: harness.react,
        'expo-router': { useLocalSearchParams: () => params, useRouter: () => ({}) },
        'react-native': {
            View: 'View', Text: 'Text', ScrollView: 'ScrollView', Pressable: 'Pressable', Modal: 'Modal', FlatList: 'FlatList',
            ActivityIndicator: 'ActivityIndicator', TouchableOpacity: 'TouchableOpacity', Platform: { OS: 'ios' },
            StyleSheet: { create: styles => styles },
        },
        'react-native-google-mobile-ads': { BannerAd: 'BannerAd', BannerAdSize: {} },
        'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView' },
        '@expo/vector-icons': { Ionicons: 'Icon' },
        '../constants/Colors': load(path.resolve(__dirname, '../constants/Colors.ts')),
        '../constants/Config': { Config: { BACKEND_URL: 'https://example.invalid' } },
        '../contexts/RevenueCatContext': { useRevenueCat: () => ({ isPro: true }) },
        '../contexts/AuthContext': { useAuth: () => ({ userId: 'test' }) },
        '../components/HeeButton': { __esModule: true, default: 'HeeButton' },
        '../components/SourceReference': { __esModule: true, default: 'SourceReference' },
        '../components/TriviaImageGallery': { __esModule: true, default: 'Gallery' },
        '../utils/triviaImages': images,
        '../utils/apiClient': { fetchWithToken: () => request },
    });
    harness.start(Details, {});
    const galleryProps = () => elements(harness.render()).find(node => node.type === 'Gallery').props;
    const initial = galleryProps();
    resolveRequest({ ok: true, json: async () => data });
    await new Promise(resolve => setImmediate(resolve));
    return { initial, latest: galleryProps(), tree: harness.render() };
}

test('details show photo sources from the API and never render the trivia reference', async t => {
    const app = await detail(t, { id: '1', source: '本文の出典', image_url: 'a.jpg',
        image_sources: '{"a.jpg":"古い写真の出典"}' }, {
        id: 1, source: '更新された本文の出典', image_url: 'a.jpg', image_sources: { 'a.jpg': '写真提供：博物館' },
    });
    assert.deepEqual(app.initial.imageSources, { 'a.jpg': '古い写真の出典' });
    assert.deepEqual(app.latest.imageSources, { 'a.jpg': '写真提供：博物館' });
    assert.equal(elements(app.tree).some(node => node.type === 'SourceReference'), false);
});

test('details replace route photos with the latest API list, including explicit removal', async t => {
    const app = await detail(t, { id: '1', title: '雑学', image_url: 'old.jpg', image_urls: '["old.jpg","other.jpg"]' }, {
        id: 1, title: '雑学', image_url: null, image_urls: [],
    });
    assert.deepEqual(app.initial.imageUrls, ['old.jpg', 'other.jpg']);
    assert.deepEqual(images.normalizeTriviaImageUrls(app.latest.imageUrls, app.latest.imageUrl), []);
});

test('details fall back safely for old APIs and malformed widget route photos', async t => {
    const app = await detail(t, { id: '1', image_url: 'old.jpg', image_urls: '{' }, { id: 1, image_url: 'latest.jpg' });
    assert.deepEqual(images.normalizeTriviaImageUrls(app.initial.imageUrls, app.initial.imageUrl), ['old.jpg']);
    assert.deepEqual(images.normalizeTriviaImageUrls(app.latest.imageUrls, app.latest.imageUrl), ['latest.jpg']);
});

test('MAP cache keeps ordered photos offline and replaces them when the API clears the gallery', async () => {
    const storage = new Map();
    const { TriviaSpotCache } = load(path.resolve(__dirname, '../managers/TriviaSpotCache.ts'), {
        '@react-native-async-storage/async-storage': { __esModule: true, default: {
            getItem: async key => storage.get(key) ?? null,
            setItem: async (key, value) => { storage.set(key, value); },
        } },
    });
    let remote = [{ id: 'map_1', title: '写真つきスポット', image_url: 'cover.jpg', image_urls: ['cover.jpg', 'detail.jpg'] }];
    let offline = false;
    const { getTriviaSpots } = load(path.resolve(__dirname, '../data/triviaSpots.ts'), {
        '../constants/Config': { getBackendUrl: () => 'https://example.invalid' },
        '../utils/apiClient': { fetchWithToken: async () => ({ ok: !offline, status: 503, json: async () => remote }) },
        '../managers/TriviaSpotCache': { TriviaSpotCache },
    });
    const initial = await getTriviaSpots();
    assert.deepEqual(initial[0].image_urls, ['cover.jpg', 'detail.jpg']);
    assert.deepEqual((await TriviaSpotCache.read())[0].image_urls, initial[0].image_urls);
    offline = true;
    assert.deepEqual((await getTriviaSpots())[0].image_urls, initial[0].image_urls);
    offline = false;
    remote = [{ ...remote[0], image_url: null, image_urls: [] }];
    assert.deepEqual((await getTriviaSpots())[0].image_urls, []);
    assert.deepEqual((await TriviaSpotCache.read())[0].image_urls, []);
});
