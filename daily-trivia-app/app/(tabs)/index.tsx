import { useState, useEffect, useCallback } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert, Platform } from 'react-native';
import { Link, useRouter, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import Constants from 'expo-constants';
import TriviaCard from '../../components/TriviaCard';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import { syncTriviaToWidget } from '../../utils/widgetSync';
import { BannerAd, BannerAdSize, TestIds } from 'react-native-google-mobile-ads';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import { Theme, Colors } from '../../constants/Colors';
import { Config } from '../../constants/Config';
import DefaultPreference from 'react-native-default-preference';

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

export default function HomeScreen() {
    const router = useRouter();
    const [currentIndex, setCurrentIndex] = useState(0);
    const [triviaList, setTriviaList] = useState<TriviaItem[]>([]);
    const [loading, setLoading] = useState(true);
    const DAILY_LIMIT = 3;
    const { isPro, currentOffering, purchasePackage } = useRevenueCat();

    const checkTutorial = async () => {
        try {
            const hasSeen = await AsyncStorage.getItem('hasSeenTutorial');
            if (hasSeen !== 'true') {
                router.replace('/tutorial');
            }
        } catch (e) {
            console.error(e);
        }
    };

    const params = useLocalSearchParams();

    useEffect(() => {
        if (params.reload === 'true') {
            initializeUserAndFetch();
        }
    }, [params.reload]);

    useEffect(() => {
        checkTutorial();
        initializeUserAndFetch();
    }, []);

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
        try {
            // Get or create UUID
            let userId = await AsyncStorage.getItem('user_id');
            if (!userId) {
                userId = Crypto.randomUUID();
                await AsyncStorage.setItem('user_id', userId);
            }
            console.log('User ID:', userId);

            // Sync with App Group for Widget
            try {
                await DefaultPreference.setName('group.com.dailytrivia.app');
                await DefaultPreference.set('user_id', userId);
                console.log('Synced user_id with App Group');
            } catch (e) {
                console.error('Failed to sync user_id with App Group:', e);
            }

            await fetchTrivia(userId);
        } catch (error) {
            console.error('Initialization error:', error);
            Alert.alert('エラー', '初期化に失敗しました。');
            setLoading(false);
        }
    };

    const fetchTrivia = async (userId: string, retryCount = 0) => {
        try {
            const limit = isPro ? 14 : DAILY_LIMIT; // Pro gets 14 initially to support infinite scroll start
            const apiUrl = `${getBackendUrl()}/trivia/today?user_id=${userId}&limit=${limit}`;
            console.log(`Fetching from: ${apiUrl} (Attempt: ${retryCount + 1})`);
            const response = await fetch(apiUrl);

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

            setTriviaList(data);
            setLoading(false);

            // Sync to widget in background (don't block UI)
            syncTriviaToWidget(data, userId).catch(err => console.error('Background widget sync failed:', err));
        } catch (error) {
            console.error('Fetch error:', error);
            if (retryCount < 2) {
                console.log(`Retrying fetch in 2 seconds... (${retryCount + 1}/2)`);
                setTimeout(() => fetchTrivia(userId, retryCount + 1), 2000);
            } else {
                setLoading(false);
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

    const fetchMoreTrivia = async () => {
        try {
            const userId = await AsyncStorage.getItem('user_id');
            // Fetch 7 more items
            const apiUrl = `${getBackendUrl()}/trivia/today?user_id=${userId}&limit=7`;
            const response = await fetch(apiUrl);
            if (response.ok) {
                const data = await response.json();
                if (Array.isArray(data) && data.length > 0) {
                    // Append new unique items
                    // Append new items (allowing duplicates for infinite scroll)
                    setTriviaList(prev => [...prev, ...data]);
                }
            }
        } catch (e) {
            console.log("Failed to fetch more trivia", e);
        }
    };

    const addToHistory = async (triviaId: number) => {
        try {
            const userId = await AsyncStorage.getItem('user_id');
            if (!userId) {
                console.warn("No user ID found for history");
                return;
            }

            const apiUrl = `${getBackendUrl()}/history`;
            await fetch(apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    user_id: userId,
                    trivia_id: triviaId
                }),
            });
            console.log('Added to history:', triviaId, 'for user:', userId);
        } catch (error) {
            console.error('Failed to add to history:', error);
        }
    };

    const handleSwipe = (direction: 'left' | 'right') => {
        console.log(`Swiped ${direction}`);

        // Add current item to history when swiped
        const currentItem = triviaList[currentIndex];
        if (currentItem) {
            addToHistory(currentItem.id);
        }

        // Wait a bit for animation to finish before updating state to remove card
        setTimeout(() => {
            setCurrentIndex((prev) => prev + 1);

            // For Pro Users: Fetch more trivia if running low
            // Check if we are close to the end (e.g., 7 items left)
            if (isPro && currentIndex >= triviaList.length - 7) {
                // detailed implementation: fetch more and append
                fetchMoreTrivia();
            }
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

    if (loading) {
        return (
            <SafeAreaView style={[styles.container, styles.center]}>
                <ActivityIndicator size="large" color="#007AFF" />
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
                <Text style={styles.headerTitle}>毎日雑学</Text>
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
                        {currentItem && (
                            <TriviaCard
                                key={`current-${currentItem.id}`}
                                item={currentItem}
                                onSwipe={handleSwipe}
                                onPressDetails={handlePressDetails}
                                style={{ zIndex: 1 }}
                            />
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
        zIndex: 10,
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
