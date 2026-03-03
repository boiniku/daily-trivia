import { useState, useEffect, useCallback, useRef } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert, Platform, AppState, AppStateStatus } from 'react-native';
import { Link, useRouter, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import TriviaCard from '../../components/TriviaCard';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import { syncTriviaToWidget } from '../../utils/widgetSync';
import { BannerAd, BannerAdSize, TestIds } from 'react-native-google-mobile-ads';
import SwipeGuide from '../../components/SwipeGuide';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import { Config } from '../../constants/Config';
import { fetchWithToken } from '../../utils/apiClient';
import { Theme, Colors } from '../../constants/Colors';
import { checkAndRequestReview } from '../../utils/reviewHandler';

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
}

import { useAuth } from '../../contexts/AuthContext';

export default function HomeScreen() {
    const router = useRouter();
    const [currentIndex, setCurrentIndex] = useState(0);
    const [triviaList, setTriviaList] = useState<TriviaItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [showSwipeGuide, setShowSwipeGuide] = useState(false);
    const [hasSeenWidgetGuide, setHasSeenWidgetGuide] = useState(true); // Default true, updated accurately on mount and focus
    const DAILY_LIMIT = 3;
    const { isPro, currentOffering, purchasePackage } = useRevenueCat();
    const { userId } = useAuth(); // Use AuthContext

    const appState = useRef(AppState.currentState);
    const isFetchingRef = useRef(false);
    const isFetchingMoreRef = useRef(false); // Prevents infinite swiping API flood
    const currentIndexRef = useRef(currentIndex); // Ensures saveState uses exact latest index during async fetch

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

    const checkSwipeGuide = async () => {
        try {
            // Only check if tutorial is already done
            const hasSeen = await AsyncStorage.getItem('hasSeenTutorial');
            if (hasSeen !== 'true') return;

            const hasSeenSwipe = await AsyncStorage.getItem('hasSeenSwipeGuide');
            if (hasSeenSwipe !== 'true') {
                // Set the flag immediately so it truly only shows once
                await AsyncStorage.setItem('hasSeenSwipeGuide', 'true');

                // Delay slightly to ensure render is ready
                setTimeout(() => {
                    setShowSwipeGuide(true);

                    if (swipeTimerRef.current) {
                        clearTimeout(swipeTimerRef.current);
                    }

                    // Auto hide after 8 seconds
                    swipeTimerRef.current = setTimeout(() => {
                        setShowSwipeGuide(false);
                    }, 8000);
                }, 500);
            }
        } catch (e) {
            console.error(e);
        }
    };

    const params = useLocalSearchParams();

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
                        const hasSeenSwipe = await AsyncStorage.getItem('hasSeenSwipeGuide');
                        if (hasSeenSwipe !== 'true') {
                            await AsyncStorage.setItem('hasSeenSwipeGuide', 'true');
                            setShowSwipeGuide(true);
                            if (swipeTimerRef.current) clearTimeout(swipeTimerRef.current);
                            swipeTimerRef.current = setTimeout(() => {
                                setShowSwipeGuide(false);
                            }, 8000);
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

            // --- Resume Logic ---
            const savedStateJson = await AsyncStorage.getItem('triviaState');
            if (savedStateJson) {
                const savedState = JSON.parse(savedStateJson);
                const today = getEffectiveDate();

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
            const apiUrl = `${getBackendUrl()}/trivia/today?limit=${limit}&date=${today}`;
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

    const fetchMoreTrivia = async () => {
        if (isFetchingMoreRef.current) return;
        try {
            isFetchingMoreRef.current = true;
            if (!userId) return;
            // Fetch 7 more items, but ensure they match the logical date of our current batch
            const apiUrl = `${getBackendUrl()}/trivia/today?limit=7&date=${dataDateRef.current}`;
            const response = await fetchWithToken(apiUrl);
            if (response.ok) {
                const data = await response.json();
                if (Array.isArray(data) && data.length > 0) {
                    // Append new items (allowing duplicates for infinite scroll)
                    setTriviaList(prev => {
                        const newList = [...prev, ...data];
                        saveState(currentIndexRef.current, newList); // Use accurate current index, not the stale one from closure
                        return newList;
                    });
                }
            }
        } catch (e) {
            console.log("Failed to fetch more trivia", e);
        } finally {
            isFetchingMoreRef.current = false;
        }
    };

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
            console.error('Failed to add to history:', error);
            Alert.alert('エラー', `履歴への追加に失敗しました: ${error.message || error}`);
        }
    };

    const handleSwipe = async (direction: 'left' | 'right') => {
        console.log(`Swiped ${direction}`);

        // Dismiss the swipe guide if it's currently showing
        if (showSwipeGuide) {
            setShowSwipeGuide(false);
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
                content: item.content
            }
        });
    };

    const isLimitReached = !isPro && currentIndex >= DAILY_LIMIT;
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
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <View style={{ width: 44 }} /> {/* Spacer to balance the right icon */}
                <Text style={styles.headerTitle}>毎日雑学</Text>

                {/* Info Button for Widget Setup Guide */}
                <Pressable
                    style={styles.infoButton}
                    onPress={() => router.push('/widget-setup')}
                    hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                >
                    <Ionicons name="information-circle-outline" size={28} color={Colors.light.text} />
                    {!hasSeenWidgetGuide && (
                        <View style={styles.badge}>
                            <Text style={styles.badgeText}>!</Text>
                        </View>
                    )}
                </Pressable>
            </View>

            <View style={styles.cardContainer}>
                {!isLimitReached ? (
                    <>
                        {/* Next Card (Background) */}
                        {triviaList[currentIndex + 1] && (
                            <TriviaCard
                                key={`next-${triviaList[currentIndex + 1].id}`}
                                item={triviaList[currentIndex + 1]}
                                onSwipe={undefined}
                                onPressDetails={() => { }}
                                enabled={false}
                                style={{ zIndex: 0, transform: [{ scale: 0.95 }, { translateY: 10 }] }}
                            />
                        )}

                        {/* Current Card (Foreground) */}
                        {currentItem ? (
                            <TriviaCard
                                key={`current-${currentItem.id}`}
                                item={currentItem}
                                onSwipe={handleSwipe}
                                onPressDetails={handlePressDetails}
                                style={{ zIndex: 1 }}
                            />
                        ) : (
                            // When waiting for fetchMoreTrivia to load next block in Pro plan
                            <View style={[styles.finishedContainer, { paddingVertical: 60, zIndex: 1 }]}>
                                <ActivityIndicator size="large" color={Colors.light.primary} />
                                <Text style={[styles.subText, { marginTop: 16 }]}>新しい雑学を準備中...</Text>
                            </View>
                        )}

                        {/* Swipe Guide Overlay */}
                        {showSwipeGuide && triviaList.length > 0 && (
                            <SwipeGuide />
                        )}
                    </>
                ) : (
                    <View style={styles.finishedContainer}>
                        <Text style={styles.finishedText}>今日の雑学は以上です！</Text>
                        <Text style={styles.subText}>また明日見に来てください。</Text>
                        {!isPro && (
                            <Pressable style={styles.upgradeButton} onPress={() => router.push('/settings')}>
                                <Text style={styles.upgradeText}>サブスクで無制限に見る</Text>
                            </Pressable>
                        )}
                    </View>
                )}
            </View>

            <View style={styles.adsContainer}>
                {/* Banner Ad */}
                {!isPro && (
                    <BannerAd
                        unitId={Platform.OS === 'ios' ? Config.BANNER_ID_IOS : Config.BANNER_ID_ANDROID}
                        size={BannerAdSize.ANCHORED_ADAPTIVE_BANNER}
                        requestOptions={{
                            requestNonPersonalizedAdsOnly: true,
                        }}
                    />
                )}
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
    headerTitle: {
        fontSize: 32,
        fontWeight: '900', // Heaviest
        color: Colors.light.primary, // Red
        letterSpacing: -1,
        textTransform: 'uppercase', // Bold feel
        fontStyle: 'italic', // Dynamic
    },
    infoButton: {
        width: 44,
        height: 44,
        justifyContent: 'center',
        alignItems: 'center',
        position: 'relative',
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
        marginTop: -30,
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
    adsContainer: {
        height: 60,
        backgroundColor: 'transparent',
        justifyContent: 'center',
        alignItems: 'center',
        marginBottom: 90,
    },
});
