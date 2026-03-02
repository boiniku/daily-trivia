import AsyncStorage from '@react-native-async-storage/async-storage';
import * as StoreReview from 'expo-store-review';
import { Alert, Platform } from 'react-native';

const SWIPE_COUNT_KEY = 'cardSwipeCount';
const REVIEW_REQUESTED_KEY = 'hasRequestedReview';
const REVIEW_THRESHOLD = 9;

/**
 * Checks the number of times the app has been opened.
 * If the count reaches the threshold (e.g., 3) and no review has been requested yet,
 * it prompts the user for a store review.
 */
export const checkAndRequestReview = async () => {
    try {
        // 1. Check if we've already requested a review
        const hasRequested = await AsyncStorage.getItem(REVIEW_REQUESTED_KEY);
        if (hasRequested === 'true') {
            console.log('Review already requested in the past. Skipping.');
            return; // We already asked, don't keep tracking or asking
        }

        // 2. Get current swipe count (default to 0)
        const swipeCountStr = await AsyncStorage.getItem(SWIPE_COUNT_KEY);
        let swipeCount = swipeCountStr ? parseInt(swipeCountStr, 10) : 0;

        // 3. Increment the count
        swipeCount += 1;
        await AsyncStorage.setItem(SWIPE_COUNT_KEY, swipeCount.toString());
        console.log(`[ReviewHandler] Card swipe count incremented to: ${swipeCount}`);

        // 4. Request review if we reach the threshold
        if (swipeCount >= REVIEW_THRESHOLD) {
            const isAvailable = await StoreReview.isAvailableAsync();
            const hasAction = await StoreReview.hasAction(); // Specifically checks if the current environment supports it

            if (isAvailable && hasAction) {
                console.log(`[ReviewHandler] Threshold ${REVIEW_THRESHOLD} reached. Requesting store review...`);
                await StoreReview.requestReview();

                // Mark as requested so we don't ask again
                await AsyncStorage.setItem(REVIEW_REQUESTED_KEY, 'true');
            } else {
                console.log(`[ReviewHandler] Store review blocked. isAvailable: ${isAvailable}, hasAction: ${hasAction}`);
            }
        }
    } catch (error) {
        console.error('Error in checkAndRequestReview:', error);
    }
};

/**
 * DEV/TESTING: Resets the stored review data so it can be triggered again.
 */
export const resetReviewStateForTesting = async () => {
    try {
        await AsyncStorage.removeItem(SWIPE_COUNT_KEY);
        await AsyncStorage.removeItem(REVIEW_REQUESTED_KEY);
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
