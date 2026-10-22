const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');

function setup(overrides = {}) {
    const swipes = [];
    const details = [];
    const hee = [];
    const react = {
        createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
        useEffect: () => {},
        useState: initial => [initial, () => {}],
    };
    function gesture() {
        const handlers = {};
        const options = {};
        const result = { handlers, options };
        for (const name of ['enabled', 'numberOfTaps', 'activeOffsetX']) {
            result[name] = value => { options[name] = value; return result; };
        }
        for (const name of ['onBegin', 'onStart', 'onUpdate', 'onEnd', 'onFinalize']) {
            result[name] = callback => { handlers[name] = callback; return result; };
        }
        return result;
    }
    const reanimated = {
        default: { View: 'AnimatedView' },
        useSharedValue: value => ({ value }),
        useAnimatedStyle: evaluate => ({ evaluate }),
        runOnJS: callback => callback,
        withSpring: value => value,
        withTiming: value => value,
        withDelay: (_delay, value) => value,
        withRepeat: value => value,
        withSequence: value => value,
        Easing: { inOut: value => value, quad: 'quad' },
    };
    const { default: TriviaCard } = load(path.resolve(__dirname, '../components/TriviaCard.tsx'), {
        react: { __esModule: true, default: react, ...react },
        'react-native': {
            View: 'View', Text: 'Text', Pressable: 'Pressable',
            StyleSheet: { create: value => value },
        },
        '@expo/vector-icons': { Ionicons: 'Icon' },
        'react-native-gesture-handler': {
            GestureDetector: 'GestureDetector',
            Gesture: { Pan: gesture, Tap: gesture, Simultaneous: (...gestures) => gestures },
        },
        'react-native-reanimated': { __esModule: true, ...reanimated },
        '../constants/Colors': {
            Theme: { borderRadius: {}, spacing: {}, shadow: { pop: {}, small: {} } },
            Colors: { light: {} },
        },
    });
    const tree = TriviaCard({
        item: { id: 3, title: '3枚目', content: '内容', category: '雑学' },
        onSwipe: direction => swipes.push(direction),
        onPressDetails: () => details.push(3),
        onDoubleTap: () => hee.push(3),
        width: 320, height: 480,
        ...overrides,
    });
    const [pan, tap] = tree.props.gesture;
    const card = tree.props.children[0];
    const transforms = () => Object.assign({}, ...card.props.style[2].evaluate().transform);
    const startPan = () => { pan.handlers.onBegin?.(); pan.handlers.onStart?.(); };
    const finalizePan = success => pan.handlers.onFinalize?.({}, success);
    return { tree, card, pan, tap, swipes, details, hee, transforms, startPan, finalizePan };
}

function elements(node) {
    if (node == null || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(elements);
    return [node, ...elements(node.props?.children)];
}

test('a system-cancelled drag restores the last card and leaves it swipeable', () => {
    const card = setup();
    card.startPan();
    card.pan.handlers.onUpdate({ translationX: 70, translationY: 20 });
    assert.equal(card.transforms().translateX, 70);

    // Native cancellation after activation calls both callbacks with success=false.
    card.pan.handlers.onEnd({ translationX: 70 }, false);
    card.finalizePan(false);
    assert.deepEqual(card.transforms(), { translateX: 0, translateY: 0, rotate: '0deg', scale: 1 });
    assert.deepEqual(card.swipes, []);

    card.startPan();
    card.pan.handlers.onUpdate({ translationX: -70, translationY: 0 });
    card.pan.handlers.onEnd({ translationX: -70 }, true);
    card.finalizePan(true);
    assert.deepEqual(card.swipes, ['left']);
    assert.equal(card.transforms().translateX, -500, 'a committed dismissal must retain its exit animation');
});

test('a gesture cancelled before activation does not leave a tap-scaled card behind', () => {
    const card = setup();
    card.pan.handlers.onBegin?.();
    card.finalizePan(false);
    assert.deepEqual(card.transforms(), { translateX: 0, translateY: 0, rotate: '0deg', scale: 1 });
    assert.deepEqual(card.swipes, []);
});

test('an outgoing card cannot enqueue a second swipe or double tap before unmount', () => {
    const card = setup();
    card.startPan();
    card.pan.handlers.onEnd({ translationX: 70 }, true);
    card.finalizePan(true);
    card.startPan();
    card.pan.handlers.onUpdate({ translationX: -70, translationY: 40 });
    card.pan.handlers.onEnd({ translationX: -70 }, true);
    card.tap.handlers.onStart();

    assert.deepEqual(card.swipes, ['right']);
    assert.deepEqual(card.hee, []);
    assert.equal(card.transforms().translateX, 500);
});

test('a queued detail press from an outgoing card cannot open the old trivia', () => {
    const card = setup();
    const button = elements(card.tree).find(element => element.type === 'Pressable');
    card.startPan();
    card.pan.handlers.onEnd({ translationX: 70 }, true);
    card.finalizePan(true);
    button.props.onPress();

    assert.deepEqual(card.swipes, ['right']);
    assert.deepEqual(card.details, []);
});

test('a disabled background card cannot intercept native touches or detail presses', () => {
    const card = setup({ enabled: false });
    const button = elements(card.tree).find(element => element.type === 'Pressable');
    assert.equal(card.card.props.pointerEvents, 'none');
    assert.equal(card.card.props.accessibilityElementsHidden, true);
    assert.equal(card.card.props.importantForAccessibility, 'no-hide-descendants');
    assert.equal(button.props.disabled, true);
    assert.equal(card.pan.options.enabled, false);
    assert.equal(card.tap.options.enabled, false);
    button.props.onPress();
    assert.deepEqual(card.details, []);
});

test('the active card keeps details available and a short drag returns to its origin', () => {
    const card = setup();
    const button = elements(card.tree).find(element => element.type === 'Pressable');
    assert.equal(card.card.props.pointerEvents ?? 'auto', 'auto');
    assert.equal(button.props.disabled ?? false, false);
    // Native Pan must wait for horizontal movement before stealing the RN
    // Pressable responder; vertical finger jitter should remain a detail tap.
    assert.deepEqual(card.pan.options.activeOffsetX, [-10, 10]);
    button.props.onPress();
    assert.deepEqual(card.details, [3]);

    card.startPan();
    card.pan.handlers.onUpdate({ translationX: 20, translationY: 30 });
    card.pan.handlers.onEnd({ translationX: 20 }, true);
    card.finalizePan(true);
    assert.deepEqual(card.transforms(), { translateX: 0, translateY: 0, rotate: '0deg', scale: 1 });
    assert.deepEqual(card.swipes, []);
});

test('a card without a swipe handler cannot animate away and leave an empty touch surface', () => {
    const card = setup({ onSwipe: undefined });
    assert.equal(card.pan.options.enabled, false);
    card.pan.handlers.onEnd({ translationX: 80 }, true);
    card.finalizePan(true);
    assert.equal(card.transforms().translateX, 0);
});
