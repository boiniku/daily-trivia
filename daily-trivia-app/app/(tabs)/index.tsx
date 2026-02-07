import { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert, Platform } from 'react-native';
import { Link, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import Constants from 'expo-constants';
import TriviaCard from '../../components/TriviaCard';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
// TEMP: Disabled for minimal build test
// import { syncTriviaToWidget } from '../../utils/widgetSync';
// TEMP: Disabled for minimal build test
// import { BannerAd, BannerAdSize, TestIds } from 'react-native-google-mobile-ads';
import { useRevenueCat } from '../../contexts/RevenueCatContext';

// Helper to determine backend URL
const getBackendUrl = () => {
    if (Platform.OS === 'web') return 'http://localhost:8000';
    if (Platform.OS === 'android') return 'http://10.0.2.2:8000'; // Emulator default

    // For physical devices or iOS simulator, try to use the packager IP
    const hostUri = Constants.expoConfig?.hostUri;
    if (hostUri) {
        const ip = hostUri.split(':')[0];
        return `http://${ip}:8000`;
    }

    return 'http://localhost:8000';
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
    const { isPro } = useRevenueCat();

    useEffect(() => {
        initializeUserAndFetch();
    }, []);

    const initializeUserAndFetch = async () => {
        try {
            // Get or create UUID
            let userId = await AsyncStorage.getItem('user_id');
            if (!userId) {
                userId = Crypto.randomUUID();
                await AsyncStorage.setItem('user_id', userId);
            }
            console.log('User ID:', userId);

            await fetchTrivia(userId);
        } catch (error) {
            console.error('Initialization error:', error);
            Alert.alert('エラー', '初期化に失敗しました。');
            setLoading(false);
        }
    };

    const fetchTrivia = async (userId: string) => {
        try {
            const apiUrl = `${getBackendUrl()}/trivia/today?user_id=${userId}`;
            console.log('Fetching from:', apiUrl);
            const response = await fetch(apiUrl);
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            const data = await response.json();
            setTriviaList(data);
            // TEMP: Disabled for minimal build test
            // await syncTriviaToWidget(data); // Sync to widget
        } catch (error) {
            console.error('Fetch error:', error);
            Alert.alert('エラー', 'データの取得に失敗しました。');
        } finally {
            setLoading(false);
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
                content: item.content // Add this!
            }
        });
    };

    const isLimitReached = currentIndex >= DAILY_LIMIT;
    const currentItem = triviaList[currentIndex];

    if (loading) {
        return (
            <SafeAreaView style={[styles.container, styles.center]}>
                <ActivityIndicator size="large" color="#007AFF" />
                <Text style={{ marginTop: 10 }}>雑学を読み込み中...</Text>
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
                        <Pressable style={styles.upgradeButton}>
                            <Text style={styles.upgradeText}>サブスクで無制限に見る</Text>
                        </Pressable>
                    </View>
                )}
            </View>

            <View style={styles.adsContainer}>
                {/* TEMP: Disabled for minimal build test */}
                {/* {!isPro && (
                    <BannerAd
                        unitId={TestIds.BANNER}
                        size={BannerAdSize.ANCHORED_ADAPTIVE_BANNER}
                        requestOptions={{
                            requestNonPersonalizedAdsOnly: true,
                        }}
                    />
                )} */}
            </View>
        </SafeAreaView>
    );
}

import { Theme, Colors } from '../../constants/Colors';

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
