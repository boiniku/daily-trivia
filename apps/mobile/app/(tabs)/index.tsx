import { useState, useEffect, useCallback, useRef } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert, Platform, AppState, AppStateStatus, LayoutChangeEvent, useWindowDimensions } from 'react-native';
import * as Haptics from 'expo-haptics';
import { Link, useRouter, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import TriviaCard from '../../components/TriviaCard';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import { syncTriviaToWidget } from '../../utils/widgetSync';
import { BannerAd, BannerAdSize, TestIds, useRewardedAd } from 'react-native-google-mobile-ads';
import SwipeGuide from '../../components/SwipeGuide';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import { Config } from '../../constants/Config';
import { fetchWithToken } from '../../utils/apiClient';
import { Theme, Colors } from '../../constants/Colors';
import { BANNER_RESERVED_HEIGHT, getTabScreenAdBottomMargin } from '../../constants/Layout';
import { checkAndRequestReview } from '../../utils/reviewHandler';

const DAILY_LIMIT = 3;
const REWARDED_BONUS_LIMIT = 3;
const REWARDED_BONUS_DATE_KEY = 'triviaRewardedBonusDate';

// Helper to determine backend URL
const getBackendUrl = () => {
    return Config.BACKEND_URL;
};

interface TriviaItem {
    id: number;
    title: string;
    content: string;
    explanation: string;
    source: string;
    category: string;
    image_url?: string | null;
}

import { useAuth } from '../../contexts/AuthContext';

export default function HomeScreen() {
    const router = useRouter();
    const { height: windowHeight } = useWindowDimensions();
    const isShortScreen = windowHeight < 750;
    const [currentIndex, setCurrentIndex] = useState(0);
    const [cardArea, setCardArea] = useState({ width: 0, height: 0 });
    const [triviaList, setTriviaList] = useState<TriviaItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [showGuideMode, setShowGuideMode] = useState<'tap' | 'swipe' | null>(null);
    const [hasSeenWidgetGuide, setHasSeenWidgetGuide] = useState(true); // Default true, updated accurately on mount and focus
    const { isPro, currentOffering, purchasePackage } = useRevenueCat();
    const { userId } = useAuth(); // Use AuthContext
    const insets = useSafeAreaInsets();
    const rewardedAdUnitId = Config.IS_PRODUCTION
        ? (Platform.OS === 'ios' ? Config.REWARDED_ID_IOS : Config.REWARDED_ID_ANDROID)
        : TestIds.REWARDED;
    const {
        isLoaded: isRewardedAdLoaded,
        isEarnedReward,
        isClosed: isRewardedAdClosed,
        error: rewardedAdError,
        load: loadRewardedAd,
        show: showRewardedAd,
    } = useRewardedAd(rewardedAdUnitId, { requestNonPersonalizedAdsOnly: true });
    const [bonusUnlocked, setBonusUnlocked] = useState(false);
    const [isLoadingRewardedTrivia, setIsLoadingRewardedTrivia] = useState(false);

    const appState = useRef(AppState.currentState);
    const isFetchingRef = useRef(false);
    const isFetchingMoreRef = useRef(false); // Prevents infinite swiping API flood
    const [errorFetchingMore, setErrorFetchingMore] = useState(false); // New state for fetchMoreTrivia errors
    const currentIndexRef = useRef(currentIndex); // Ensures saveState uses exact latest index during async fetch
    const shouldShowSwipeAfterTapGuideRef = useRef(true);
    const rewardHandledRef = useRef(false);
    const rewardRequestPendingRef = useRef(false);

    const handleCardAreaLayout = useCallback((event: LayoutChangeEvent) => {
        const { width, height } = event.nativeEvent.layout;
        setCardArea((current) => {
            if (Math.abs(current.width - width) < 1 && Math.abs(current.height - height) < 1) {
                return current;
            }
            return { width, height };
        });
    }, []);

    const cardWidth = Math.max(0, Math.min(cardArea.width * 0.86, 420));
    const cardHeight = Math.max(0, Math.min(cardArea.height - 24, 500));
    const canRenderCard = cardWidth > 0 && cardHeight > 0;

    // Helper to get effective date (changes at 2:00 AM)
    const getEffectiveDate = useCallback(() => {
        const now = new Date();
        now.setHours(now.getHours() - 2);
        // Return local YYYY-MM-DD
        return now.getFullYear() + '-' +
            String(now.getMonth() + 1).padStart(2, '0') + '-' +
            String(now.getDate()).padStart(2, '0');
    }, []);

    const dataDateRef = useRef(getEffectiveDate()); // Tracks the logical date of the currently rendered trivia list

    useEffect(() => {
        currentIndexRef.current = currentIndex;
    }, [currentIndex]);

    useEffect(() => {
        if (!isPro && !bonusUnlocked) {
            loadRewardedAd();
        }
    }, [bonusUnlocked, isPro, loadRewardedAd]);

    useEffect(() => {
        if (rewardedAdError && rewardRequestPendingRef.current) {
            rewardRequestPendingRef.current = false;
            Alert.alert('広告を読み込めませんでした', '通信状態を確認して、もう一度お試しください。');
        }
    }, [rewardedAdError]);

    useEffect(() => {
        if (isRewardedAdClosed && !isEarnedReward) {
            rewardRequestPendingRef.current = false;
        }
    }, [isEarnedReward, isRewardedAdClosed]);

    const checkTutorial = async () => {
        try {
            const hasSeen = await AsyncStorage.getItem('hasSeenTutorial');
            if (hasSeen !== 'true') {
                router.push('/tutorial');
            }
        } catch (e) {
            console.error(e);
        }
    };

    const swipeTimerRef = useRef<NodeJS.Timeout | null>(null);

    const showTapGuide = (shouldShowSwipeAfterTap: boolean) => {
        shouldShowSwipeAfterTapGuideRef.current = shouldShowSwipeAfterTap;
        setShowGuideMode('tap');

        if (swipeTimerRef.current) {
            clearTimeout(swipeTimerRef.current);
        }

        swipeTimerRef.current = setTimeout(() => {
            if (shouldShowSwipeAfterTapGuideRef.current) {
                AsyncStorage.setItem('hasSeenSwipeGuide', 'true').catch(() => {});
                setShowGuideMode('swipe');
            } else {
                setShowGuideMode(null);
            }
        }, 8000);
    };

    const checkSwipeGuide = async () => {
        try {
            // Only check if tutorial is already done
            const hasSeen = await AsyncStorage.getItem('hasSeenTutorial');
            if (hasSeen !== 'true') return;

            const hasSeenInteractionGuide = await AsyncStorage.getItem('hasSeenInteractionGuide');
            if (hasSeenInteractionGuide !== 'true') {
                const hasSeenOldSwipeGuide = await AsyncStorage.getItem('hasSeenSwipeGuide');
                await AsyncStorage.setItem('hasSeenInteractionGuide', 'true');

                // Delay slightly to ensure render is ready
                setTimeout(() => {
                    showTapGuide(hasSeenOldSwipeGuide !== 'true');
                }, 500);
            }
        } catch (e) {
            console.error(e);
        }
    };

    const params = useLocalSearchParams();
    const lastHandledWidgetDeepLinkRef = useRef<string | null>(null);

    const getParamString = (value: string | string[] | undefined) => {
        if (Array.isArray(value)) return value[0];
        return value;
    };

    // If a widget deep link lands on this tab first, forward it to details unconditionally.
    useEffect(() => {
        const fromWidget = getParamString(params.from_widget) === 'true';
        const triviaId = getParamString(params.id);
        if (!fromWidget || !triviaId) return;
        if (lastHandledWidgetDeepLinkRef.current === triviaId) return;

        lastHandledWidgetDeepLinkRef.current = triviaId;
        router.replace({
            pathname: '/details',
            params: {
                id: triviaId,
                title: getParamString(params.title) ?? '',
                content: getParamString(params.content) ?? '',
                explanation: getParamString(params.explanation) ?? '解説データがありません',
                source: getParamString(params.source) ?? '',
                category: getParamString(params.category) ?? '未分類',
                image_url: getParamString(params.image_url) ?? '',
                from_widget: 'true'
            }
        });
    }, [params, router]);

    // Run tutorial check ONCE on mount
    useEffect(() => {
        checkTutorial();
    }, []);

    // Watch for userId changes (e.g. login)
    useEffect(() => {
        if (userId) {
            initializeUserAndFetch();
        }
    }, [userId]); // Re-run when userId changes

    // Show swipe guide when screen gains focus (handles cold start / task kill case)
    useFocusEffect(
        useCallback(() => {
            checkSwipeGuide();

            // Check widget guide status
            const checkWidgetGuide = async () => {
                try {
                    // Check if they've seen the tutorial first. If not, they shouldn't see badge yet either, 
                    // or badge will show immediately. Only show badge (false) if tutorial is done but widget guide isn't.
                    const hasSeenTutorialObj = await AsyncStorage.getItem('hasSeenTutorial');
                    if (hasSeenTutorialObj !== 'true') {
                        setHasSeenWidgetGuide(true); // Hide badge while in tutorial
                        return;
                    }

                    const hasSeen = await AsyncStorage.getItem('hasSeenWidgetGuide');
                    setHasSeenWidgetGuide(hasSeen === 'true');
                } catch (e) {
                    console.error('Error checking widget guide status', e);
                }
            };
            checkWidgetGuide();
        }, [])
    );

    // Also show swipe guide when data loads AND pendingSwipeGuide flag is set
    // This handles the post-tutorial case where useFocusEffect may not fire
    useEffect(() => {
        if (triviaList.length > 0) {
            const checkPendingGuide = async () => {
                try {
                    const pending = await AsyncStorage.getItem('pendingSwipeGuide');
                    if (pending === 'true') {
                        await AsyncStorage.removeItem('pendingSwipeGuide');
                        const hasSeenInteractionGuide = await AsyncStorage.getItem('hasSeenInteractionGuide');
                        if (hasSeenInteractionGuide !== 'true') {
                            const hasSeenOldSwipeGuide = await AsyncStorage.getItem('hasSeenSwipeGuide');
                            await AsyncStorage.setItem('hasSeenInteractionGuide', 'true');
                            showTapGuide(hasSeenOldSwipeGuide !== 'true');
                        }
                    }
                } catch (e) {
                    console.error('Pending guide check error', e);
                }
            };
            checkPendingGuide();
        }
    }, [triviaList.length]);

    // Watch for Pro status change to fetch more trivia if stuck at limit
    useEffect(() => {
        if (isPro && triviaList.length > 0 && currentIndex >= triviaList.length) {
            console.log("User became Pro at end of list, fetching more...");
            setLoading(true); // Show loading to avoid blank screen
            fetchMoreTrivia().finally(() => setLoading(false));
        }
    }, [isPro, triviaList.length, currentIndex]);

    const handlePurchase = async () => {
        if (isPro) {
            Alert.alert('確認', 'すでにサブスクリプションに登録済みです。');
            return;
        }
        if (!currentOffering?.current?.availablePackages?.length) {
            Alert.alert('エラー', '現在購入可能なプランがありません。');
            return;
        }

        try {
            await purchasePackage(currentOffering.current.availablePackages[0]);
        } catch (e) {
            console.log('Purchase cancelled or failed', e);
        }
    };

    const initializeUserAndFetch = async () => {
        if (isFetchingRef.current) return;
        try {
            isFetchingRef.current = true;
            if (!userId) {
                isFetchingRef.current = false;
                return;
            }
            console.log('User ID from Context:', userId);
            const today = getEffectiveDate();
            const rewardedBonusDate = await AsyncStorage.getItem(REWARDED_BONUS_DATE_KEY);
            const hasRewardedBonusToday = rewardedBonusDate === today;
            setBonusUnlocked(hasRewardedBonusToday);
            rewardHandledRef.current = hasRewardedBonusToday;
            if (rewardedBonusDate && !hasRewardedBonusToday) {
                await AsyncStorage.removeItem(REWARDED_BONUS_DATE_KEY);
            }

            // --- Resume Logic ---
            const savedStateJson = await AsyncStorage.getItem('triviaState');
            if (savedStateJson) {
                const savedState = JSON.parse(savedStateJson);
                if (savedState.date === today && Array.isArray(savedState.list) && savedState.list.length > 0) {
                    console.log('Restoring state for date:', today);
                    // Set the dataDateRef to match the cached date we are restoring
                    dataDateRef.current = today;
                    setTriviaList(savedState.list);
                    setCurrentIndex(savedState.currentIndex || 0);
                    setLoading(false);
                    isFetchingRef.current = false;
                    return; // Skip fetching from server
                } else {
                    console.log('Saved state expired or invalid. Clearing.');
                    await AsyncStorage.removeItem('triviaState');
                }
            }
            // --------------------

            await fetchTrivia(userId);
        } catch (error) {
            console.error('Initialization error:', error);
            Alert.alert('エラー', '初期化に失敗しました。');
            setLoading(false);
            isFetchingRef.current = false;
        }
    };

    const fetchTrivia = async (userId: string, retryCount = 0) => {
        try {
            const limit = isPro ? 14 : DAILY_LIMIT; // Pro gets 14 initially to support infinite scroll start
            const today = getEffectiveDate();
            const apiUrl = `${getBackendUrl()}/trivia/today?limit=${limit}&date=${today}&user_id=${encodeURIComponent(userId)}`;
            console.log(`Fetching from: ${apiUrl} (Attempt: ${retryCount + 1})`);
            const response = await fetchWithToken(apiUrl);

            if (!response.ok) {
                const errorText = await response.text();
                // If 500 error, valid JSON might still be returned in some cases, but usually it's HTML or text
                console.error(`HTTP Error: ${response.status} ${response.statusText}`);
                console.error(`Response body: ${errorText}`);
                throw new Error(`Network response was not ok: ${response.status}`);
            }

            const data = await response.json();

            // Validate data structure
            if (!Array.isArray(data)) {
                throw new Error('Invalid data format: expected an array');
            }

            // Successfully fetched new data, lock the logical date for this batch
            dataDateRef.current = today;

            setTriviaList(data);
            setCurrentIndex(0); // FIX: Ensure swipe index is reset to 0 when loading a new batch
            setLoading(false);
            isFetchingRef.current = false;
            saveState(0, data); // FIX: Ensure date state is saved immediately to track day changes

            // Sync to widget in background (don't block UI)
            syncTriviaToWidget(data, userId).catch(err => console.error('Background widget sync failed:', err));
        } catch (error) {
            console.error('Fetch error:', error);
            if (retryCount < 2) {
                console.log(`Retrying fetch in 2 seconds... (${retryCount + 1}/2)`);
                setTimeout(() => fetchTrivia(userId, retryCount + 1), 2000);
            } else {
                setLoading(false);
                isFetchingRef.current = false;
                Alert.alert(
                    '通信エラー',
                    'データの取得に失敗しました。時間をおいて再度お試しください。',
                    [
                        { text: '再試行', onPress: () => fetchTrivia(userId, 0) }
                    ]
                );
            }
        }
    };


    // getEffectiveDate was moved up to be near refs

    const saveState = async (index: number, list: TriviaItem[]) => {
        try {
            const state = {
                date: dataDateRef.current, // FIX: Use the logical date of the batch, not the wall-clock time
                currentIndex: index,
                list: list
            };
            await AsyncStorage.setItem('triviaState', JSON.stringify(state));
        } catch (e) {
            console.error('Failed to save state:', e);
        }
    };

    const fetchMoreTrivia = async (limit = 7): Promise<boolean> => {
        if (isFetchingMoreRef.current) return false;
        let fetchedItems = false;
        try {
            isFetchingMoreRef.current = true;
            setErrorFetchingMore(false); // Reset error state on new attempt
            if (!userId) return false;
            // Fetch 7 more items, ensure they match the logical date, AND disable daily assignment prepending
            const apiUrl = `${getBackendUrl()}/trivia/today?limit=${limit}&date=${dataDateRef.current}&include_assignments=false&user_id=${encodeURIComponent(userId)}`;
            const response = await fetchWithToken(apiUrl);
            if (response.ok) {
                const data = await response.json();
                if (Array.isArray(data) && data.length > 0) {
                    fetchedItems = true;
                    // Append new items (filtering out duplicates that are already in the list to prevent buffer overlap logic loop)
                    setTriviaList(prev => {
                        const existingIds = new Set(prev.map(item => item.id));
                        const filteredData = data.filter(item => !existingIds.has(item.id));
                        
                        // If all items are filtered out, it means the DB might be exhausted, 
                        // so we append them anyway to keep the infinite scroll alive instead of breaking it.
                        const finalDataToAppend = filteredData.length > 0 ? filteredData : data;
                        
                        const newList = [...prev, ...finalDataToAppend];
                        saveState(currentIndexRef.current, newList); // Use accurate current index, not the stale one from closure
                        return newList;
                    });
                } else {
                    // This handles empty arrays but since our backend falls back to history, 
                    // this typically means a server error disguised as a 200 OK empty response or true DB zero state.
                    setErrorFetchingMore(true);
                }
            } else {
                setErrorFetchingMore(true);
            }
        } catch (e) {
            console.log("Failed to fetch more trivia", e);
            setErrorFetchingMore(true);
        } finally {
            isFetchingMoreRef.current = false;
        }
        return fetchedItems;
    };

    useEffect(() => {
        if (!isEarnedReward || rewardHandledRef.current) return;

        rewardHandledRef.current = true;
        rewardRequestPendingRef.current = false;
        const grantRewardedBonus = async () => {
            setBonusUnlocked(true);
            setIsLoadingRewardedTrivia(true);
            await AsyncStorage.setItem(REWARDED_BONUS_DATE_KEY, dataDateRef.current);
            const fetched = await fetchMoreTrivia(REWARDED_BONUS_LIMIT);
            setIsLoadingRewardedTrivia(false);
            if (!fetched) {
                Alert.alert('追加の雑学を取得できませんでした', '「再試行」を押して、もう一度お試しください。');
            }
        };

        void grantRewardedBonus();
    }, [isEarnedReward]);

    useEffect(() => {
        const shouldResumeRewardedFetch =
            !isPro &&
            bonusUnlocked &&
            !loading &&
            !isLoadingRewardedTrivia &&
            !errorFetchingMore &&
            currentIndex >= triviaList.length &&
            currentIndex < DAILY_LIMIT + REWARDED_BONUS_LIMIT;

        if (!shouldResumeRewardedFetch) return;
        setIsLoadingRewardedTrivia(true);
        fetchMoreTrivia(REWARDED_BONUS_LIMIT).finally(() => setIsLoadingRewardedTrivia(false));
    }, [bonusUnlocked, currentIndex, errorFetchingMore, isLoadingRewardedTrivia, isPro, loading, triviaList.length]);

    const addToHistory = async (triviaId: number) => {
        try {
            if (!userId) {
                console.warn("No user ID found for history");
                return;
            }

            const apiUrl = `${getBackendUrl()}/history`;
            await fetchWithToken(apiUrl, {
                method: 'POST',
                body: JSON.stringify({
                    trivia_id: triviaId
                }),
            });
            console.log('Added to history:', triviaId, 'for user:', userId);
        } catch (error: any) {
            // Silently fail history addition to avoid UX blocking spam when offline
            console.error('Failed to add to history (Network/Server error):', error);
        }
    };

    const handleSwipe = async (direction: 'left' | 'right') => {
        console.log(`Swiped ${direction}`);

        // Dismiss the swipe guide if it's currently showing
        if (showGuideMode === 'swipe') {
            setShowGuideMode(null);
            AsyncStorage.setItem('hasSeenSwipeGuide', 'true').catch(() => {});
            if (swipeTimerRef.current) clearTimeout(swipeTimerRef.current);
        }

        // Add current item to history when swiped
        const currentItem = triviaList[currentIndex];
        if (currentItem) {
            addToHistory(currentItem.id);
        }

        // Wait a bit for animation to finish before updating state to remove card
        setTimeout(() => {
            const nextIndex = currentIndex + 1;
            setCurrentIndex(nextIndex);

            // Save state
            saveState(nextIndex, triviaList);

            // For Pro Users: Fetch more trivia if running low
            // Check if we are close to the end (e.g., 7 items left)
            if (isPro && currentIndex >= triviaList.length - 7) {
                // detailed implementation: fetch more and append
                fetchMoreTrivia();
            }

            // Check for review prompt on swipe (threshold logic handled inside)
            checkAndRequestReview();
        }, 200);
    };

    const handleUndoSwipe = () => {
        if (currentIndex <= 0) return;
        const previousIndex = currentIndex - 1;
        currentIndexRef.current = previousIndex;
        setCurrentIndex(previousIndex);
        saveState(previousIndex, triviaList);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    };

    const handleWatchRewardedAd = () => {
        if (!isRewardedAdLoaded) {
            loadRewardedAd();
            Alert.alert('広告を準備しています', '少し待ってから、もう一度押してください。');
            return;
        }
        rewardRequestPendingRef.current = true;
        showRewardedAd();
    };

    const handlePressDetails = () => {
        const item = triviaList[currentIndex];
        router.push({
            pathname: '/details',
            params: {
                id: item.id,
                title: item.title,
                explanation: item.explanation,
                source: item.source,
                category: item.category,
                content: item.content,
                image_url: item.image_url ?? ''
            }
        });
    };

    const handleDoubleTapHee = async () => {
        const item = triviaList[currentIndex];
        if (!item || !userId) return;
        if (showGuideMode === 'tap') {
            if (swipeTimerRef.current) clearTimeout(swipeTimerRef.current);
            if (shouldShowSwipeAfterTapGuideRef.current) {
                AsyncStorage.setItem('hasSeenSwipeGuide', 'true').catch(() => {});
                setShowGuideMode('swipe');
            } else {
                setShowGuideMode(null);
            }
        }
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            await fetchWithToken(`${getBackendUrl()}/trivia/${item.id}/hee`, {
                method: 'POST',
                body: JSON.stringify({ count: 1 }),
            });
        } catch (e) {
            console.error('Double-tap hee failed:', e);
        }
    };

    const freeDailyLimit = DAILY_LIMIT + (bonusUnlocked ? REWARDED_BONUS_LIMIT : 0);
    const isLimitReached = !isPro && currentIndex >= freeDailyLimit;
    const canUnlockRewardedBonus = !isPro && !bonusUnlocked && currentIndex >= DAILY_LIMIT;
    const currentItem = triviaList[currentIndex];

    // --- New Refresh Logic ---
    const checkDateAndRefresh = async () => {
        try {
            const today = getEffectiveDate();
            const savedStateJson = await AsyncStorage.getItem('triviaState');

            let shouldRefresh = false;
            if (savedStateJson) {
                const savedState = JSON.parse(savedStateJson);
                if (savedState.date !== today) {
                    console.log(`Date changed (State: ${savedState.date}, Today: ${today}). Refreshing...`);
                    shouldRefresh = true;
                }
            } else if (!loading) {
                // If there is no saved state at all but we are not loading, refresh to be safe so we establish a date state
                shouldRefresh = true;
            }

            if (shouldRefresh) {
                setLoading(true);
                await initializeUserAndFetch();
            }
        } catch (e) {
            console.error("Check date error:", e);
        }
    };

    useFocusEffect(
        useCallback(() => {
            checkDateAndRefresh();
        }, [userId])
    );

    useEffect(() => {
        const subscription = AppState.addEventListener('change', nextAppState => {
            if (
                appState.current.match(/inactive|background/) &&
                nextAppState === 'active'
            ) {
                console.log('App has come to the foreground!');
                checkDateAndRefresh();
            }
            appState.current = nextAppState;
        });

        return () => {
            subscription.remove();
        };
    }, [userId]);
    // -------------------------

    // --- Rescue Logic for Pro User Subscription Validation Race Condition ---
    useEffect(() => {
        // If the user's subscription validation returns late (after the initial Free-tier 3 items were fetched)
        // Ensure we automatically pull in the rest of the 14 items without requiring a impossible swipe
        if (isPro && !loading && triviaList.length > 0 && triviaList.length <= DAILY_LIMIT) {
            console.log("Pro subscription validated late. Automatically fetching additional Pro items...");
            fetchMoreTrivia();
        }
    }, [isPro, loading, triviaList.length]);

    if (loading) {
        return (
            <SafeAreaView style={[styles.container, styles.center]}>
                <ActivityIndicator size="large" color={Colors.light.primary} />
                <Text style={{ marginTop: 10, color: Colors.light.subtext }}>雑学を読み込み中...</Text>
                <Text style={{ fontSize: 10, color: '#CCC', marginTop: 4 }}>v1.0.1</Text>
            </SafeAreaView>
        );
    }

    // Add empty check for non-loading state
    if (!loading && triviaList.length === 0) {
        return (
            <SafeAreaView style={[styles.container, styles.center]}>
                <Text style={styles.subText}>雑学データが見つかりませんでした。</Text>
                <Pressable style={styles.upgradeButton} onPress={() => initializeUserAndFetch()}>
                    <Text style={styles.upgradeText}>再読み込み</Text>
                </Pressable>
            </SafeAreaView>
        );
    }

    return (
        <SafeAreaView edges={['top', 'left', 'right']} style={styles.container}>
            <View style={[styles.header, isShortScreen && styles.headerCompact]}>
                <Pressable
                    style={[styles.undoButton, isShortScreen && styles.headerButtonCompact, currentIndex <= 0 && styles.undoButtonDisabled]}
                    onPress={handleUndoSwipe}
                    disabled={currentIndex <= 0}
                    accessibilityRole="button"
                    accessibilityLabel="ひとつ前の雑学に戻る"
                >
                    <Ionicons name="arrow-undo" size={isShortScreen ? 21 : 24} color={currentIndex > 0 ? Colors.light.primary : '#C8C8C8'} />
                </Pressable>
                <Text style={[styles.headerTitle, isShortScreen && styles.headerTitleCompact]} maxFontSizeMultiplier={1.2}>毎日雑学</Text>

                {/* Info Button for Widget Setup Guide */}
                <Pressable
                    style={[styles.infoButton, isShortScreen && styles.headerButtonCompact]}
                    onPress={() => router.push('/widget-setup')}
                    hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                >
                    <Ionicons name="information-circle-outline" size={isShortScreen ? 25 : 28} color={Colors.light.text} />
                    {!hasSeenWidgetGuide ? (
                        <View style={styles.badge}>
                            <Text style={styles.badgeText}>!</Text>
                        </View>
                    ) : null}
                </Pressable>
            </View>

            <View style={styles.cardContainer} onLayout={handleCardAreaLayout}>
                {!isLimitReached ? (
                    <>
                        {/* Next Card (Background) */}
                        {canRenderCard && triviaList[currentIndex + 1] ? (
                            <TriviaCard
                                key={`next-${triviaList[currentIndex + 1].id}`}
                                item={triviaList[currentIndex + 1]}
                                onSwipe={undefined}
                                onPressDetails={() => { }}
                                enabled={false}
                                width={cardWidth}
                                height={cardHeight}
                                style={{ zIndex: 0, transform: [{ scale: 0.95 }, { translateY: 10 }] }}
                            />
                        ) : null}

                        {/* Current Card (Foreground) */}
                        {currentItem ? (
                            canRenderCard ? (
                                <TriviaCard
                                    key={`current-${currentItem.id}`}
                                    item={currentItem}
                                    onSwipe={handleSwipe}
                                    onPressDetails={handlePressDetails}
                                    onDoubleTap={handleDoubleTapHee}
                                    width={cardWidth}
                                    height={cardHeight}
                                    style={{ zIndex: 1 }}
                                />
                            ) : null
                        ) : (
                            // When waiting for fetchMoreTrivia to load next block in Pro plan
                            <View style={[styles.finishedContainer, { paddingVertical: 60, zIndex: 1 }]}>
                                {errorFetchingMore ? (
                                    <>
                                        <Text style={[styles.subText, { marginTop: 16 }]}>読み込みに失敗しました。</Text>
                                        <Pressable
                                            style={styles.upgradeButton}
                                            onPress={() => fetchMoreTrivia(isPro ? 7 : REWARDED_BONUS_LIMIT)}
                                        >
                                            <Text style={styles.upgradeText}>再試行</Text>
                                        </Pressable>
                                    </>
                                ) : (
                                    <>
                                        <ActivityIndicator size="large" color={Colors.light.primary} />
                                        <Text style={[styles.subText, { marginTop: 16 }]}>
                                            {isLoadingRewardedTrivia ? '広告特典の雑学を準備中...' : '新しい雑学を準備中...'}
                                        </Text>
                                    </>
                                )}
                            </View>
                        )}

                        {/* Swipe Guide Overlay */}
                        {showGuideMode && triviaList.length > 0 ? (
                            <SwipeGuide mode={showGuideMode} />
                        ) : null}
                    </>
                ) : (
                    <View style={[styles.finishedContainer, isShortScreen && styles.finishedContainerCompact]}>
                        {canUnlockRewardedBonus ? (
                            <>
                                <Ionicons name="play-circle" size={52} color={Colors.light.accent} />
                                <Text style={styles.finishedText}>もう3つ見られます！</Text>
                                <Text style={styles.subText}>広告を最後まで見ると、今日の雑学を3つ追加します。</Text>
                                <Pressable style={styles.rewardedButton} onPress={handleWatchRewardedAd}>
                                    <Ionicons name="play" size={18} color="#FFFFFF" />
                                    <Text style={styles.rewardedButtonText}>
                                        {isRewardedAdLoaded ? '広告を見て3つ追加' : '広告を準備する'}
                                    </Text>
                                </Pressable>
                            </>
                        ) : (
                            <>
                                <Text style={styles.finishedText}>今日の雑学は以上です！</Text>
                                <Text style={styles.subText}>また明日見に来てください。</Text>
                                {!isPro ? (
                                    <Pressable style={styles.upgradeButton} onPress={() => router.push('/settings')}>
                                        <Text style={styles.upgradeText}>サブスクで無制限に見る</Text>
                                    </Pressable>
                                ) : null}
                            </>
                        )}
                    </View>
                )}
            </View>

            <View style={[
                styles.adsContainer,
                {
                    marginBottom: getTabScreenAdBottomMargin(insets),
                    minHeight: isPro ? 0 : BANNER_RESERVED_HEIGHT,
                },
            ]}>
                {/* Banner Ad */}
                {!isPro ? (
                    <BannerAd
                        unitId={Platform.OS === 'ios' ? Config.BANNER_ID_IOS : Config.BANNER_ID_ANDROID}
                        size={BannerAdSize.ANCHORED_ADAPTIVE_BANNER}
                        requestOptions={{
                            requestNonPersonalizedAdsOnly: true,
                        }}
                    />
                ) : null}
            </View>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: Colors.light.background,
    },
    center: {
        justifyContent: 'center',
        alignItems: 'center',
    },
    header: {
        flexDirection: 'row',
        justifyContent: 'center',
        paddingVertical: 20,
        alignItems: 'center',
        zIndex: 50, // High z-index so it stays above SwipeGuide overlay
        backgroundColor: 'transparent',
    },
    headerCompact: {
        paddingVertical: 8,
    },
    headerTitle: {
        fontSize: 32,
        fontWeight: '900', // Heaviest
        color: Colors.light.primary, // Red
        letterSpacing: -1,
        textTransform: 'uppercase', // Bold feel
        fontStyle: 'italic', // Dynamic
    },
    headerTitleCompact: {
        fontSize: 26,
    },
    infoButton: {
        width: 44,
        height: 44,
        justifyContent: 'center',
        alignItems: 'center',
        position: 'relative',
    },
    headerButtonCompact: {
        width: 38,
        height: 38,
    },
    undoButton: {
        width: 44,
        height: 44,
        justifyContent: 'center',
        alignItems: 'center',
        borderRadius: 22,
        backgroundColor: '#FFFFFF',
        ...Theme.shadow.small,
    },
    undoButtonDisabled: {
        opacity: 0.55,
        shadowOpacity: 0,
        elevation: 0,
    },
    badge: {
        position: 'absolute',
        top: 6,
        right: 6,
        backgroundColor: 'red',
        width: 14,
        height: 14,
        borderRadius: 7,
        justifyContent: 'center',
        alignItems: 'center',
        borderWidth: 1,
        borderColor: 'white',
    },
    badgeText: {
        color: 'white',
        fontSize: 9,
        fontWeight: 'bold',
        lineHeight: 11,
    },
    cardContainer: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        position: 'relative',
        overflow: 'hidden',
    },
    finishedContainer: {
        justifyContent: 'center',
        alignItems: 'center',
        padding: 40,
        backgroundColor: Colors.light.cardBackground,
        borderRadius: Theme.borderRadius.l,
        ...Theme.shadow.pop, // Pop shadow
        margin: 20,
        borderWidth: 4,
        borderColor: Colors.light.border,
    },
    finishedContainerCompact: {
        padding: 20,
        margin: 12,
    },
    finishedText: {
        fontSize: 24,
        fontWeight: 'bold',
        marginBottom: 10,
        color: Colors.light.text,
        textAlign: 'center',
    },
    subText: {
        fontSize: 16,
        color: Colors.light.subtext,
        marginBottom: 24,
        textAlign: 'center',
        fontWeight: '600',
    },
    upgradeButton: {
        backgroundColor: Colors.light.accent, // Yellow button
        paddingVertical: 16,
        paddingHorizontal: 40,
        borderRadius: 50, // Pill shape
        ...Theme.shadow.small,
        borderWidth: 2,
        borderColor: 'white',
    },
    upgradeText: {
        color: '#8B4500', // Darker text for yellow bg
        fontWeight: 'bold',
        fontSize: 18,
    },
    rewardedButton: {
        minHeight: 54,
        paddingHorizontal: 24,
        borderRadius: 27,
        backgroundColor: Colors.light.primary,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        ...Theme.shadow.small,
    },
    rewardedButtonText: {
        color: '#FFFFFF',
        fontSize: 16,
        fontWeight: '900',
    },
    adsContainer: {
        backgroundColor: 'transparent',
        justifyContent: 'center',
        alignItems: 'center',
    },
});
