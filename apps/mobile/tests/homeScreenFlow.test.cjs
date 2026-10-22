const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');

const tutorial = load(path.resolve(__dirname, '../constants/Tutorial.ts'));
const colors = load(path.resolve(__dirname, '../constants/Colors.ts'));
const flush = () => new Promise(resolve => setImmediate(resolve));
const items = Array.from({ length: 6 }, (_, i) => ({
    id: i + 1, title: `雑学${i + 1}`, content: `本文${i + 1}`,
    explanation: `解説${i + 1}`, category: '科学', source: `https://example.com/${i + 1}`,
}));

function elements(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(elements);
    return [node, ...elements(node.props?.children)];
}

function textContent(node) {
    if (node == null) return '';
    if (Array.isArray(node)) return node.map(textContent).join('');
    if (typeof node === 'object') return textContent(node.props?.children);
    return String(node);
}

// Render the real screen and its effects with isolated storage, navigation,
// timers and ad events. Native cards remain inert so callbacks can be exercised.
function setup(t, { index = 0, params = {}, bonus = false, list = items.slice(0, 3), pro = false } = {}) {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: new Date('2026-10-15T12:00:00Z').getTime() });
    const date = new Date(); date.setHours(date.getHours() - 2);
    const today = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    const storage = new Map([
        [tutorial.TUTORIAL_COMPLETION_KEY, 'true'],
        [tutorial.TUTORIAL_REVISION_KEY, tutorial.CURRENT_TUTORIAL_REVISION],
        ['hasSeenInteractionGuide', 'true'], ['hasSeenWidgetGuide', 'true'],
        ['triviaState', JSON.stringify({ date: today, currentIndex: index, list })],
    ]);
    if (bonus) storage.set('triviaRewardedBonusDate', today);
    const hooks = [], pendingEffects = [], focusEffects = new Set();
    const navigation = [], requests = [], alerts = [], ads = [], appStateListeners = new Set();
    const widgetChecks = [], widgetCacheSyncs = [];
    let cursor = 0, dirty = true, tree, focused = true, fetchMoreFails = false;
    const sameDeps = (left, right) => left && right && left.length === right.length && left.every((value, i) => Object.is(value, right[i]));
    const react = {
        Fragment: 'Fragment',
        createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
        useState(initial) {
            const i = cursor++;
            if (!hooks[i]) {
                const slot = { value: typeof initial === 'function' ? initial() : initial };
                slot.set = value => {
                    const next = typeof value === 'function' ? value(slot.value) : value;
                    if (!Object.is(next, slot.value)) { slot.value = next; dirty = true; }
                };
                hooks[i] = slot;
            }
            return [hooks[i].value, hooks[i].set];
        },
        useRef(initial) { const i = cursor++; return hooks[i] ??= { current: initial }; },
        useMemo(factory, deps) {
            const i = cursor++;
            if (!hooks[i] || !sameDeps(hooks[i].deps, deps)) hooks[i] = { value: factory(), deps };
            return hooks[i].value;
        },
        useCallback(callback, deps) { return react.useMemo(() => callback, deps); },
        useEffect(effect, deps) {
            const i = cursor++;
            if (!hooks[i] || !sameDeps(hooks[i].deps, deps)) {
                const previous = hooks[i];
                hooks[i] = { deps };
                pendingEffects.push(() => { previous?.cleanup?.(); hooks[i].cleanup = effect(); });
            }
        },
    };
    const previousReact = global.React;
    global.React = react; // The app's JSX is transformed to React.createElement by the loader.
    const router = {
        push: route => navigation.push({ kind: 'push', route }),
        replace: route => navigation.push({ kind: 'replace', route }),
        setParams: values => { params = { ...params, ...values }; dirty = true; },
    };
    const createAd = (unitId, options) => {
        const listeners = new Map();
        const ad = {
            unitId, options, loaded: false, loadCount: 0, showCount: 0, failShow: false,
            load() { ad.loadCount++; },
            show() {
                ad.showCount++;
                if (ad.failShow) return Promise.reject(new Error('show failed'));
                ad.loaded = false;
                return Promise.resolve();
            },
            addAdEventListener(type, listener) {
                if (!listeners.has(type)) listeners.set(type, new Set());
                listeners.get(type).add(listener);
                return () => listeners.get(type).delete(listener);
            },
            emit(type, value) {
                if (type === 'loaded') ad.loaded = true;
                for (const listener of [...(listeners.get(type) ?? [])]) listener(value);
            },
            listenerCount: () => [...listeners.values()].reduce((count, listeners) => count + listeners.size, 0),
        };
        ads.push(ad);
        return ad;
    };
    const { default: HomeScreen } = load(path.resolve(__dirname, '../app/(tabs)/index.tsx'), {
        react: { __esModule: true, default: react, ...react },
        'react-native': {
            View: 'View', Text: 'Text', Pressable: 'Pressable', ActivityIndicator: 'ActivityIndicator',
            StyleSheet: { create: styles => styles }, Platform: { OS: 'ios' },
            useWindowDimensions: () => ({ width: 390, height: 844 }),
            Alert: { alert: (...args) => alerts.push(args) },
            AppState: {
                currentState: 'active',
                addEventListener: (_event, callback) => {
                    appStateListeners.add(callback);
                    return { remove: () => appStateListeners.delete(callback) };
                },
            },
        },
        'expo-router': {
            useRouter: () => router, useLocalSearchParams: () => params,
            useFocusEffect(callback) {
                react.useEffect(() => {
                    const entry = { callback, cleanup: focused ? callback() : undefined };
                    focusEffects.add(entry);
                    return () => { entry.cleanup?.(); focusEffects.delete(entry); };
                }, [callback]);
            },
        },
        'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView', useSafeAreaInsets: () => ({ top: 0, bottom: 20, left: 0, right: 0 }) },
        '@expo/vector-icons': { Ionicons: 'Icon' },
        'expo-haptics': { impactAsync: async () => {}, ImpactFeedbackStyle: { Light: 'light', Medium: 'medium' } },
        '../../components/TriviaCard': { __esModule: true, default: 'TriviaCard' },
        '../../components/SwipeGuide': { __esModule: true, default: 'SwipeGuide' },
        '@react-native-async-storage/async-storage': {
            __esModule: true, default: {
                getItem: async key => storage.get(key) ?? null,
                setItem: async (key, value) => { storage.set(key, value); },
                removeItem: async key => { storage.delete(key); },
            },
        },
        '../../contexts/RevenueCatContext': { useRevenueCat: () => ({ isPro: pro }) },
        '../../contexts/AuthContext': { useAuth: () => ({ userId: 'test-user' }) },
        '../../utils/widgetSync': {
            syncTriviaToWidget: async (list, userId, date) => { widgetCacheSyncs.push({ list, userId, date }); },
            syncInstalledWidgetTrivia: async (userId, date) => { widgetChecks.push({ userId, date }); return false; },
        },
        '../../utils/reviewHandler': { checkAndRequestReview: async () => {} },
        '../../constants/Colors': colors,
        '../../constants/Tutorial': tutorial,
        '../../constants/Layout': { BANNER_RESERVED_HEIGHT: 64, getTabScreenAdBottomMargin: () => 114 },
        '../../constants/Config': { Config: {
            BACKEND_URL: 'https://example.invalid', IS_PRODUCTION: false,
            INTERSTITIAL_ID_IOS: 'history-interstitial-ios', INTERSTITIAL_ID_ANDROID: 'history-interstitial-android',
        } },
        '../../utils/apiClient': { fetchWithToken: async (url, options, expectedUserId) => {
            requests.push({ url, options, expectedUserId });
            if (url.includes('include_assignments=false')) return { ok: !fetchMoreFails, json: async () => items.slice(3) };
            return { ok: true, json: async () => items.slice(0, 3) };
        } },
        'react-native-google-mobile-ads': {
            BannerAd: 'BannerAd', BannerAdSize: { ANCHORED_ADAPTIVE_BANNER: 'banner' },
            TestIds: { INTERSTITIAL: 'test-interstitial', REWARDED: 'test-rewarded' },
            InterstitialAd: { createForAdRequest: createAd },
            AdEventType: { LOADED: 'loaded', OPENED: 'opened', CLOSED: 'closed', ERROR: 'error' },
        },
    });
    const render = () => {
        while (dirty) {
            dirty = false; cursor = 0; tree = HomeScreen();
            for (const effect of pendingEffects.splice(0)) effect();
        }
        return tree;
    };
    const settle = async () => { for (let i = 0; i < 5; i++) { render(); await flush(); } render(); };
    const close = () => {
        for (const slot of hooks) slot?.cleanup?.();
        if (previousReact === undefined) delete global.React; else global.React = previousReact;
    };
    t.after(close);
    render();
    return {
        storage, navigation, requests, alerts, ads, widgetChecks, widgetCacheSyncs, settle, render,
        currentCard: () => elements(render()).find(node => node.type === 'TriviaCard' && typeof node.props.onSwipe === 'function'),
        button: pattern => elements(render()).find(node => node.type === 'Pressable' && pattern.test(textContent(node))),
        async layout() {
            elements(render()).find(node => node.props?.onLayout)?.props.onLayout({ nativeEvent: { layout: { width: 390, height: 560 } } });
            await settle();
        },
        async swipe() { this.currentCard().props.onSwipe('left'); t.mock.timers.tick(200); await settle(); },
        blur() { focused = false; for (const entry of focusEffects) { entry.cleanup?.(); entry.cleanup = undefined; } },
        async focus() { focused = true; for (const entry of focusEffects) entry.cleanup = entry.callback(); await settle(); },
        async appState(value) { for (const callback of appStateListeners) callback(value); await settle(); },
        advance: async ms => { t.mock.timers.tick(ms); await settle(); },
        fetchMoreFails: value => { fetchMoreFails = value; },
    };
}

test('opening cards or details does not register history, while a swipe registers exactly that card', async t => {
    const app = setup(t);
    await app.settle(); await app.layout();
    assert.equal(app.requests.filter(request => request.url.endsWith('/history')).length, 0);
    app.currentCard().props.onPressDetails();
    await app.settle();
    assert.equal(app.requests.filter(request => request.url.endsWith('/history')).length, 0);
    app.blur(); await app.focus(); await app.swipe();
    const history = app.requests.filter(request => request.url.endsWith('/history'));
    assert.equal(history.length, 1);
    assert.deepEqual(JSON.parse(history[0].options.body), { trivia_id: 1 });
    assert.equal(history[0].expectedUserId, 'test-user');
});

test('cached cards recheck widget installation on launch and when the app returns', async t => {
    const app = setup(t);
    await app.settle(); await app.layout();
    assert.ok(app.widgetChecks.length > 0);
    assert.equal(app.widgetCacheSyncs[0].userId, 'test-user');
    assert.equal(app.widgetCacheSyncs[0].date, JSON.parse(app.storage.get('triviaState')).date);
    const initialChecks = app.widgetChecks.length;
    app.blur(); await app.focus();
    assert.ok(app.widgetChecks.length > initialChecks);
    const focusChecks = app.widgetChecks.length;
    await app.appState('inactive'); await app.appState('active');
    assert.ok(app.widgetChecks.length > focusChecks);
    assert.equal(app.requests.length, 0, 'Cached cards and details must not cause a normal fetch or a history POST');
});

test('widget launch preserves the third card and permits details, return, and its final swipe', async t => {
    const app = setup(t, { index: 2, params: { from_widget: 'true', id: '3', source: items[2].source } });
    await app.settle(); await app.layout();
    assert.equal(app.currentCard().props.item.id, 3);
    const widgetRoute = app.navigation.find(entry => entry.kind === 'replace');
    assert.equal(widgetRoute.route.pathname, '/details');
    assert.equal(widgetRoute.route.params.source, items[2].source);
    app.blur(); await app.focus();
    app.currentCard().props.onPressDetails();
    assert.equal(app.navigation.at(-1).route.params.id, 3);
    app.blur(); await app.focus();
    await app.swipe();
    assert.equal(JSON.parse(app.storage.get('triviaState')).currentIndex, 3);
    assert.ok(app.button(/広告.*3つ|広告を準備/));
});

test('successive swipes record each item once and leave the last card interactive', async t => {
    const app = setup(t);
    await app.settle(); await app.layout();
    app.currentCard().props.onSwipe('left');
    app.currentCard().props.onSwipe('right');
    await app.advance(200);
    assert.equal(app.currentCard().props.item.id, 2);
    await app.swipe();
    assert.equal(app.currentCard().props.item.id, 3);
    app.currentCard().props.onPressDetails();
    assert.equal(app.navigation.at(-1).route.params.id, 3);
    app.blur(); await app.focus(); await app.swipe();
    assert.deepEqual(app.requests.filter(request => request.url.endsWith('/history')).map(request => JSON.parse(request.options.body).trivia_id), [1, 2, 3]);
});

test('a delayed callback from card two cannot swipe or lock card three after a widget return', async t => {
    const app = setup(t, { index: 1 });
    await app.settle(); await app.layout();
    const previousCard = app.currentCard();
    await app.swipe();
    assert.equal(app.currentCard().props.item.id, 3);
    app.blur(); await app.focus();
    previousCard.props.onSwipe('left');
    previousCard.props.onPressDetails();
    await app.advance(200);
    assert.equal(app.currentCard()?.props.item.id, 3);
    assert.equal(app.navigation.length, 0);
    app.currentCard().props.onPressDetails();
    assert.equal(app.navigation.at(-1).route.params.id, 3);
    app.blur(); await app.focus(); await app.swipe();
    assert.equal(JSON.parse(app.storage.get('triviaState')).currentIndex, 3);
    assert.deepEqual(app.requests.filter(request => request.url.endsWith('/history')).map(request => JSON.parse(request.options.body).trivia_id), [2, 3]);
});

test('leaving during a swipe cancels its timer and the third card works again on return', async t => {
    const app = setup(t, { index: 2 });
    await app.settle(); await app.layout();
    app.currentCard().props.onSwipe('left');
    app.blur();
    await app.advance(300);
    await app.focus();
    assert.equal(app.currentCard()?.props.item.id, 3);
    app.currentCard().props.onPressDetails();
    assert.equal(app.navigation.at(-1).route.params.id, 3);
    app.blur(); await app.focus(); await app.swipe();
    assert.equal(JSON.parse(app.storage.get('triviaState')).currentIndex, 3);
});

test('callbacks from the same third card before a widget return cannot affect its remounted card', async t => {
    const app = setup(t, { index: 2 });
    await app.settle(); await app.layout();
    const previousCard = app.currentCard();
    app.blur(); await app.focus();
    assert.notEqual(app.currentCard().props.key, previousCard.props.key);
    previousCard.props.onPressDetails();
    previousCard.props.onSwipe('left');
    await previousCard.props.onDoubleTap();
    await app.advance(200);
    assert.equal(app.currentCard()?.props.item.id, 3);
    assert.equal(app.navigation.length, 0);
    assert.equal(app.requests.length, 0);
    app.currentCard().props.onPressDetails();
    assert.equal(app.navigation.at(-1).route.params.id, 3);
    app.blur(); await app.focus(); await app.swipe();
    assert.equal(JSON.parse(app.storage.get('triviaState')).currentIndex, 3);
});

test('undoing back to the same trivia never revalidates callbacks from its previous card', async t => {
    const app = setup(t, { index: 1 });
    await app.settle(); await app.layout();
    const previousCard = app.currentCard();
    await app.swipe();
    const undo = elements(app.render()).find(node => node.props?.accessibilityLabel === 'ひとつ前の雑学に戻る');
    undo.props.onPress();
    await app.settle();
    assert.equal(app.currentCard().props.item.id, 2);

    previousCard.props.onPressDetails();
    previousCard.props.onSwipe('left');
    await previousCard.props.onDoubleTap();
    await app.advance(200);
    assert.equal(app.navigation.length, 0);
    assert.equal(app.currentCard()?.props.item.id, 2);
    assert.deepEqual(app.requests.map(request => request.url.split('/').at(-1)), ['history']);

    app.currentCard().props.onPressDetails();
    assert.equal(app.navigation.at(-1).route.params.id, 2);
    app.blur(); await app.focus(); await app.swipe();
    assert.equal(app.currentCard().props.item.id, 3);
    await app.swipe();
    assert.equal(JSON.parse(app.storage.get('triviaState')).currentIndex, 3);
});

test('undo during the last swipe cancels its advance and keeps the revealed cards usable', async t => {
    const app = setup(t, { index: 2 });
    await app.settle(); await app.layout();
    const outgoingCard = app.currentCard();
    outgoingCard.props.onSwipe('left');
    const undo = elements(app.render()).find(node => node.props?.accessibilityLabel === 'ひとつ前の雑学に戻る');
    undo.props.onPress();
    await app.advance(300);
    assert.equal(app.currentCard().props.item.id, 2);
    assert.equal(JSON.parse(app.storage.get('triviaState')).currentIndex, 1);

    await app.swipe();
    outgoingCard.props.onSwipe('right');
    outgoingCard.props.onPressDetails();
    await app.advance(300);
    assert.equal(app.currentCard()?.props.item.id, 3);
    assert.equal(app.navigation.length, 0);
    app.currentCard().props.onPressDetails();
    assert.equal(app.navigation.at(-1).route.params.id, 3);
    app.blur(); await app.focus(); await app.swipe();
    assert.equal(JSON.parse(app.storage.get('triviaState')).currentIndex, 3);
});

test('background callbacks are ignored and old callbacks stay invalid after the app resumes', async t => {
    const app = setup(t, { index: 2 });
    await app.settle(); await app.layout();
    const previousCard = app.currentCard();
    await app.appState('inactive');
    await app.appState('background');
    previousCard.props.onPressDetails();
    previousCard.props.onSwipe('left');
    await previousCard.props.onDoubleTap();
    await app.advance(200);
    assert.equal(app.navigation.length, 0);
    assert.equal(app.requests.length, 0);
    await app.appState('active');
    previousCard.props.onPressDetails();
    previousCard.props.onSwipe('left');
    await app.advance(200);
    assert.equal(app.currentCard()?.props.item.id, 3);
    assert.equal(app.navigation.length, 0);
    app.currentCard().props.onPressDetails();
    assert.equal(app.navigation.at(-1).route.params.id, 3);
    app.blur(); await app.focus(); await app.swipe();
    assert.equal(JSON.parse(app.storage.get('triviaState')).currentIndex, 3);
});

test('the daily bonus uses an interstitial and grants exactly three cards only when the shown ad closes', async t => {
    const app = setup(t, { index: 3 });
    await app.settle();
    const ad = app.ads[0];
    assert.ok(ad, 'Daily bonus must create an ordinary interstitial ad');
    assert.ok(['history-interstitial-ios', 'test-interstitial'].includes(ad.unitId));
    assert.deepEqual(ad.options, { requestNonPersonalizedAdsOnly: true });
    ad.emit('closed'); await app.settle();
    assert.equal(app.storage.has('triviaRewardedBonusDate'), false, 'An unrelated close event must not grant a bonus');
    ad.emit('loaded'); await app.settle();
    const press = app.button(/広告.*3つ/).props.onPress;
    press(); press();
    await app.settle();
    assert.equal(ad.showCount, 1, 'Repeated taps must not present the ad twice');
    assert.equal(app.storage.has('triviaRewardedBonusDate'), false);
    assert.equal(app.requests.filter(request => request.url.includes('include_assignments=false')).length, 0);
    ad.emit('closed'); ad.emit('closed'); await app.settle(); await app.layout();
    assert.ok(app.storage.has('triviaRewardedBonusDate'));
    assert.equal(app.currentCard().props.item.id, 4);
    const extraRequests = app.requests.filter(request => request.url.includes('include_assignments=false'));
    assert.equal(extraRequests.length, 1);
    assert.match(extraRequests[0].url, /limit=3(?:&|$)/);
    await app.swipe(); await app.swipe(); await app.swipe();
    assert.equal(app.currentCard(), undefined);
    assert.equal(app.button(/広告.*3つ/), undefined, 'The bonus can be used only once per day');
});

test('a failed interstitial does not grant the daily bonus and permits another attempt', async t => {
    const app = setup(t, { index: 3 });
    await app.settle();
    const ad = app.ads[0];
    ad.emit('loaded'); await app.settle();
    app.button(/広告.*3つ/).props.onPress(); await app.settle();
    ad.emit('error', new Error('offline')); await app.settle();
    ad.emit('closed'); await app.settle();
    assert.equal(app.storage.has('triviaRewardedBonusDate'), false);
    assert.equal(app.requests.some(request => request.url.includes('include_assignments=false')), false);
    assert.ok(app.alerts.length > 0);
    ad.emit('loaded'); await app.settle();
    app.button(/広告.*3つ/).props.onPress(); await app.settle();
    assert.equal(ad.showCount, 2);
    ad.emit('closed'); await app.settle();
    assert.ok(app.storage.has('triviaRewardedBonusDate'));
});

test('an unready interstitial loads on demand and keeps the daily bonus locked', async t => {
    const app = setup(t, { index: 3 });
    await app.settle();
    const ad = app.ads[0];
    const initialLoadCount = ad.loadCount;
    await app.button(/広告を準備/).props.onPress(); await app.settle();
    assert.equal(ad.loadCount, initialLoadCount + 1);
    assert.equal(ad.showCount, 0);
    assert.equal(app.storage.has('triviaRewardedBonusDate'), false);
    assert.equal(app.requests.length, 0);
    assert.equal(app.alerts.at(-1)[0], '広告を準備しています');
    ad.emit('loaded'); await app.settle();
    await app.button(/広告.*3つ/).props.onPress();
    ad.emit('closed'); await app.settle();
    assert.ok(app.storage.has('triviaRewardedBonusDate'));
});

test('a rejected ad show promise resets the pending request and allows a later retry', async t => {
    const app = setup(t, { index: 3 });
    await app.settle();
    const ad = app.ads[0];
    ad.failShow = true;
    ad.emit('loaded'); await app.settle();
    await app.button(/広告.*3つ/).props.onPress(); await app.settle();
    ad.emit('closed'); await app.settle();
    assert.equal(app.storage.has('triviaRewardedBonusDate'), false);
    assert.equal(app.requests.length, 0);
    assert.equal(app.alerts.at(-1)[0], '広告を表示できませんでした');
    ad.failShow = false;
    ad.emit('loaded'); await app.settle();
    await app.button(/広告.*3つ/).props.onPress();
    ad.emit('closed'); await app.settle();
    assert.equal(ad.showCount, 2);
    assert.ok(app.storage.has('triviaRewardedBonusDate'));
});

test('an already granted bonus survives restart and resumes fetching without another ad', async t => {
    const app = setup(t, { index: 3, bonus: true });
    await app.settle(); await app.layout();
    assert.equal(app.currentCard().props.item.id, 4);
    assert.equal(app.ads.reduce((count, ad) => count + ad.showCount, 0), 0);
    assert.equal(app.requests.filter(request => request.url.includes('include_assignments=false')).length, 1);
});

test('a bonus fetch failure can be retried without watching another ad', async t => {
    const app = setup(t, { index: 3 });
    app.fetchMoreFails(true);
    await app.settle();
    const ad = app.ads[0];
    ad.emit('loaded'); await app.settle();
    app.button(/広告.*3つ/).props.onPress(); await app.settle();
    ad.emit('closed'); await app.settle(); await app.layout();
    assert.ok(app.storage.has('triviaRewardedBonusDate'));
    assert.ok(app.button(/再試行/));
    app.fetchMoreFails(false);
    app.button(/再試行/).props.onPress(); await app.settle();
    assert.equal(app.currentCard().props.item.id, 4);
    assert.equal(ad.showCount, 1);
    assert.equal(app.requests.filter(request => request.url.includes('include_assignments=false')).length, 2);
});
