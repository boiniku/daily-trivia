import AsyncStorage from '@react-native-async-storage/async-storage';
import * as StoreReview from 'expo-store-review';
import { Alert, Platform } from 'react-native';

const SWIPE_COUNT_KEY = 'cardSwipeCount';
const REVIEW_REQUESTED_KEY = 'hasRequestedReview';
const REVIEW_STATE_KEY = 'reviewStateV2';
const REVIEW_THRESHOLD = 9;
const MAX_REVIEW_REQUESTS = 1;

type ReviewState = {
    swipeCount: number;
    requestCount: number;
    lastRequestedAt: string | null;
    lastAttemptedAt: string | null;
};

let reviewCheckQueue: Promise<void> = Promise.resolve();

const parseReviewState = (raw: string | null): ReviewState | null => {
    if (!raw) return null;
    try {
        const parsed = JSON.parse(raw);
        const swipeCount = Number(parsed?.swipeCount);
        const requestCount = Number(parsed?.requestCount);
        return {
            swipeCount: Number.isFinite(swipeCount) && swipeCount >= 0 ? swipeCount : 0,
            requestCount: Number.isFinite(requestCount) && requestCount >= 0 ? requestCount : 0,
            lastRequestedAt: typeof parsed?.lastRequestedAt === 'string' ? parsed.lastRequestedAt : null,
            lastAttemptedAt: typeof parsed?.lastAttemptedAt === 'string' ? parsed.lastAttemptedAt : null,
        };
    } catch {
        return null;
    }
};

const loadReviewState = async (): Promise<ReviewState> => {
    const [stateStr, swipeCountStr, hasRequested] = await Promise.all([
        AsyncStorage.getItem(REVIEW_STATE_KEY),
        AsyncStorage.getItem(SWIPE_COUNT_KEY),
        AsyncStorage.getItem(REVIEW_REQUESTED_KEY),
    ]);

    const parsed = parseReviewState(stateStr);
    if (parsed) return parsed;

    const legacySwipeCount = Number.parseInt(swipeCountStr ?? '0', 10);
    const legacyRequested = hasRequested === 'true';
    return {
        swipeCount: Number.isFinite(legacySwipeCount) && legacySwipeCount >= 0 ? legacySwipeCount : 0,
        requestCount: legacyRequested ? 1 : 0,
        lastRequestedAt: null,
        lastAttemptedAt: null,
    };
};

const saveReviewState = async (state: ReviewState) => {
    await Promise.all([
        AsyncStorage.setItem(REVIEW_STATE_KEY, JSON.stringify(state)),
        AsyncStorage.setItem(SWIPE_COUNT_KEY, String(state.swipeCount)),
        AsyncStorage.setItem(REVIEW_REQUESTED_KEY, state.requestCount > 0 ? 'true' : 'false'),
    ]);
};

const runCheckAndRequestReview = async () => {
    const state = await loadReviewState();

    state.swipeCount += 1;
    console.log(`[ReviewHandler] Card swipe count incremented to: ${state.swipeCount}`);

    if (state.swipeCount < REVIEW_THRESHOLD) {
        await saveReviewState(state);
        return;
    }

    if (state.requestCount >= MAX_REVIEW_REQUESTS) {
        console.log(`[ReviewHandler] Max review requests reached (${MAX_REVIEW_REQUESTS}). Skipping.`);
        await saveReviewState(state);
        return;
    }

    const nowMs = Date.now();
    const isAvailable = await StoreReview.isAvailableAsync();
    const hasAction = await StoreReview.hasAction();
    const nowIso = new Date(nowMs).toISOString();
    state.lastAttemptedAt = nowIso;

    if (isAvailable && hasAction) {
        console.log(`[ReviewHandler] Threshold ${REVIEW_THRESHOLD} reached. Requesting store review...`);
        await StoreReview.requestReview();
        state.requestCount += 1;
        state.lastRequestedAt = nowIso;
        state.swipeCount = 0;
    } else {
        console.log(`[ReviewHandler] Store review blocked. isAvailable: ${isAvailable}, hasAction: ${hasAction}`);
    }

    await saveReviewState(state);
};

/**
 * Counts swipes and requests in-app review when threshold is reached.
 * Calls are queued to avoid AsyncStorage race conditions.
 */
export const checkAndRequestReview = async () => {
    reviewCheckQueue = reviewCheckQueue
        .then(() => runCheckAndRequestReview())
        .catch(error => {
            console.error('Error in checkAndRequestReview:', error);
        });

    return reviewCheckQueue;
};

/**
 * DEV/TESTING: Resets the stored review data so it can be triggered again.
 */
export const resetReviewStateForTesting = async () => {
    try {
        await Promise.all([
            AsyncStorage.removeItem(SWIPE_COUNT_KEY),
            AsyncStorage.removeItem(REVIEW_REQUESTED_KEY),
            AsyncStorage.removeItem(REVIEW_STATE_KEY),
        ]);
        console.log('[ReviewHandler] Reset review state successfully.');
    } catch (error) {
        console.error('Error resetting review state:', error);
    }
};

/**
 * DEV/TESTING: Immediately triggers the review prompt, bypassing the count.
 * Note: Still subject to iOS/Android OS restrictions.
 */
export const forceTriggerReviewForTesting = async () => {
    try {
        const isAvailable = await StoreReview.isAvailableAsync();
        const hasAction = await StoreReview.hasAction();

        if (isAvailable && hasAction) {
            console.log('[ReviewHandler] Force requesting store review...');
            await StoreReview.requestReview();
            const state = await loadReviewState();
            const nowIso = new Date().toISOString();
            state.requestCount += 1;
            state.lastAttemptedAt = nowIso;
            state.lastRequestedAt = nowIso;
            state.swipeCount = 0;
            await saveReviewState(state);
        } else {
            console.log(`[ReviewHandler] Force request blocked. isAvailable: ${isAvailable}, hasAction: ${hasAction}`);

            let reason = "";
            if (Platform.OS === 'ios') {
                reason = "iOSの「設定」>「App Store」>「App内評価とレビュー」がオフになっているか、テスト環境(TestFlightの一部状況)でブロックされている可能性があります。";
            } else {
                reason = "Android環境ではPlayストアからインストールしていない場合、表示されません。";
            }

            Alert.alert(
                "レビューを強制表示できません",
                `OS側がダイアログの表示を拒否しています。\n[isAvailable: ${isAvailable}, hasAction: ${hasAction}]\n\n${reason}`
            );
        }
    } catch (error) {
        console.error('Error force triggering review:', error);
        Alert.alert("エラー", "レビューの呼び出し中にエラーが発生しました。");
    }
};
