const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');
const flush = () => new Promise(resolve => setImmediate(resolve));
const elements = node => !node || typeof node !== 'object' ? [] : Array.isArray(node)
    ? node.flatMap(elements) : [node, ...elements(node.props?.children)];
const text = node => node == null ? '' : Array.isArray(node) ? node.map(text).join('')
    : typeof node === 'object' ? text(node.props?.children) : String(node);

function setup(t, { unlocked = true, failRefresh = false, pendingRefresh = false } = {}) {
    const savedDate = new Date('2026-10-01T00:00:00Z');
    const spot = { id: 'map_1', title: '東京のスポット', description: '本文', explanation: '解説',
        latitude: 35, longitude: 139, unlockRadiusMeters: 300, prefecture: '東京都',
        isUnlocked: false, unlockedAt: null, unlockCount: 5, image_urls: [] };
    const photos = ['https://images.test/map/a.webp', 'https://images.test/map/b.webp'];
    const sources = { [photos[0]]: '写真：作者A / CC BY 4.0', [photos[1]]: '写真：作者B / CC BY-SA 3.0' };
    const latest = { ...spot, image_url: photos[0], image_urls: photos, image_sources: sources };
    const hooks = [], effects = [];
    let cursor = 0, dirty = true, tree, requests = 0, resolveRefresh;
    const sameDeps = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
    const react = {
        Fragment: 'Fragment',
        createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
        useState(initial) {
            const index = cursor++;
            if (!hooks[index]) {
                const slot = { value: typeof initial === 'function' ? initial() : initial };
                slot.set = value => {
                    const next = typeof value === 'function' ? value(slot.value) : value;
                    if (!Object.is(next, slot.value)) { slot.value = next; dirty = true; }
                };
                hooks[index] = slot;
            }
            return [hooks[index].value, hooks[index].set];
        },
        useRef(value) { return hooks[cursor++] ??= { current: value }; },
        useMemo(factory, deps) {
            const index = cursor++;
            if (!hooks[index] || !sameDeps(hooks[index].deps, deps)) hooks[index] = { value: factory(), deps };
            return hooks[index].value;
        },
        useCallback(callback, deps) { return react.useMemo(() => callback, deps); },
        useEffect(effect, deps) {
            const index = cursor++;
            if (!hooks[index] || !sameDeps(hooks[index].deps, deps)) {
                const previous = hooks[index]; hooks[index] = { deps };
                effects.push(() => { previous?.cleanup?.(); hooks[index].cleanup = effect(); });
            }
        },
    };
    const oldReact = global.React;
    global.React = react;
    t.after(() => { for (const hook of hooks) hook?.cleanup?.(); global.React = oldReact; });
    const { default: Screen } = load(path.resolve(__dirname, '../app/(tabs)/map.tsx'), {
        react: react,
        'expo-router': { useFocusEffect() {}, useLocalSearchParams: () => ({}) },
        'react-native': { View: 'View', Text: 'Text', Pressable: 'Pressable', ScrollView: 'ScrollView',
            Modal: 'Modal', ActivityIndicator: 'ActivityIndicator', TouchableOpacity: 'TouchableOpacity',
            StyleSheet: { create: styles => styles }, Platform: { OS: 'ios' },
            AppState: { addEventListener: () => ({ remove() {} }) } },
        '@expo/vector-icons': { Ionicons: 'Icon' },
        'react-native-maps': { __esModule: true, default: 'MapView', Marker: 'Marker', Circle: 'Circle' },
        'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView', useSafeAreaInsets: () => ({ bottom: 0, top: 0 }) },
        '../../data/triviaSpots': { getTriviaSpots: async () => {
            requests++;
            if (requests === 1) return [spot];
            if (failRefresh) throw new Error('offline');
            if (pendingRefresh) return new Promise(resolve => { resolveRefresh = resolve; });
            return [latest];
        } },
        '../../managers/TriviaSpotCache': { TriviaSpotCache: { read: async () => [] } },
        '../../managers/TriviaUnlockManager': { calculateDistanceMeters: () => 10000,
            TriviaUnlockManager: { syncUnlockedRecords: async () => {},
                hydrateSpots: async rows => rows.map(row => ({ ...row, isUnlocked: unlocked, unlockedAt: unlocked ? savedDate : null })) } },
        '../../managers/TriviaGeofenceManager': { TriviaGeofenceManager: {} },
        '../../managers/TriviaLocationManager': { TriviaLocationManager: { requestForegroundPermission: async () => 'denied' } },
        '../../constants/Colors': load(path.resolve(__dirname, '../constants/Colors.ts')),
        '../../constants/JapanRegions': load(path.resolve(__dirname, '../constants/JapanRegions.ts')),
        '../../constants/Layout': { BANNER_RESERVED_HEIGHT: 50, FLOATING_TAB_BAR_HEIGHT: 60,
            getFloatingTabBarBottom: () => 0, getTabScreenAdBottomMargin: () => 0 },
        '../../constants/Config': { Config: { IS_PRODUCTION: false } },
        '../../components/TriviaImageGallery': { __esModule: true, default: 'Gallery' },
        '../../contexts/RevenueCatContext': { useRevenueCat: () => ({ isPro: true }) },
        '../../contexts/AuthContext': { useAuth: () => ({ userId: 'test-user' }) },
        '@react-native-async-storage/async-storage': { __esModule: true, default: {} },
        'react-native-google-mobile-ads': { TestIds: {}, AdEventType: {},
            InterstitialAd: { createForAdRequest: () => ({ loaded: false }) } },
    });
    async function render() {
        for (let i = 0; i < 20; i++) {
            if (dirty) { dirty = false; cursor = 0; tree = Screen(); }
            while (effects.length) effects.shift()();
            await flush();
            if (!dirty && !effects.length) return tree;
        }
        throw new Error('Screen did not settle');
    }
    const find = predicate => elements(tree).find(predicate);
    const press = async predicate => { const button = find(predicate); assert.ok(button, 'Control exists'); await button.props.onPress(); await render(); };
    async function selectPin() {
        find(node => node.type === 'MapView').props.onRegionChangeComplete({ latitudeDelta: 0.5 });
        await render();
        await press(node => node.type === 'Marker' && node.props.coordinate.latitude === 35);
    }
    async function openDetail() {
        await press(node => node.type === 'Pressable' && text(node).includes('タップして詳細を見る'));
    }
    return { render, find, press, selectPin, openDetail, photos, sources, savedDate,
        resolveRefresh: () => resolveRefresh([latest]), requests: () => requests };
}

test('Map detail refreshes all photos and sources while preserving local unlocks', async t => {
    const app = setup(t);
    await app.render(); await app.selectPin(); await app.openDetail();
    const modal = app.find(node => node.type === 'Modal');
    assert.equal(modal.props.visible, true);
    const gallery = app.find(node => node.type === 'Gallery');
    assert.deepEqual(gallery.props.imageUrls, app.photos);
    assert.deepEqual(gallery.props.imageSources, app.sources);
    assert.ok(text(modal).includes('2026/10/1'));
    assert.equal(app.requests(), 2);
    await app.press(node => node.type === 'Pressable' && elements(node).some(child => child.type === 'Icon' && child.props.name === 'albums'));
    assert.equal(app.find(node => node.type === 'Modal').props.visible, true);
});

test('collected Map trivia opens the same detail gallery', async t => {
    const app = setup(t);
    await app.render();
    await app.press(node => node.type === 'Pressable' && elements(node).some(child => child.type === 'Icon' && child.props.name === 'albums'));
    await app.press(node => node.type === 'Pressable' && text(node).includes('東京のスポット'));
    await app.openDetail();
    assert.deepEqual(app.find(node => node.type === 'Gallery').props.imageUrls, app.photos);
});

test('unreadable locked Map trivia does not reveal photos after metadata refresh', async t => {
    const app = setup(t, { unlocked: false });
    await app.render(); await app.selectPin(); await app.openDetail();
    assert.equal(app.find(node => node.type === 'Gallery'), undefined);
    assert.ok(text(app.find(node => node.type === 'Modal')).includes('まだ解放されていません'));
});

test('closing a detail cancels a pending photo refresh', async t => {
    const app = setup(t, { pendingRefresh: true });
    await app.render(); await app.selectPin(); await app.openDetail();
    app.find(node => node.type === 'Modal').props.onRequestClose();
    await app.render(); app.resolveRefresh(); await app.render();
    assert.deepEqual(app.find(node => node.type === 'Gallery').props.imageUrls, []);
});
