import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator, Alert, Platform, ScrollView } from 'react-native';
import { useState, useEffect } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import { Config } from '../../constants/Config';
import { Theme, Colors } from '../../constants/Colors';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import { InterstitialAd, AdEventType, TestIds } from 'react-native-google-mobile-ads';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { fetchWithToken } from '../../utils/apiClient';

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

const interstitial = InterstitialAd.createForAdRequest(TestIds.INTERSTITIAL, {
    requestNonPersonalizedAdsOnly: true,
});

export default function CollectionDetailsScreen() {
    const { id, title } = useLocalSearchParams();
    const router = useRouter();
    const [items, setItems] = useState<TriviaItem[]>([]);
    const [filteredItems, setFilteredItems] = useState<TriviaItem[]>([]);
    const [loading, setLoading] = useState(true);
    const { isPro } = useRevenueCat();

    // Filtering
    const [categories, setCategories] = useState<string[]>([]);
    const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

    // Ads
    const [adLoaded, setAdLoaded] = useState(false);

    useEffect(() => {
        fetchCollectionItems();

        // Ad Logic
        if (!isPro) {
            const unsubscribe = interstitial.addAdEventListener(AdEventType.LOADED, () => {
                setAdLoaded(true);
            });

            const unsubscribeClosed = interstitial.addAdEventListener(AdEventType.CLOSED, () => {
                setAdLoaded(false);
                interstitial.load();
            });

            interstitial.load();

            return () => {
                unsubscribe();
                unsubscribeClosed();
            };
        }
    }, [id]);

    // Check Ad Cooldown when entering
    useEffect(() => {
        const checkAdCooldown = async () => {
            if (isPro) return;
            // Only show ad if collection is "Past Trivia" (as per request) OR maybe all collections?
            // "過去に見た雑学フォルダをみたときに出てくる広告のクールタイム"
            if (title !== "過去に見た雑学") return;

            try {
                const lastShown = await AsyncStorage.getItem('last_interstitial_shown');
                const now = Date.now();
                const COOLDOWN = 5 * 60 * 1000; // 5 minutes

                if (!lastShown || (now - parseInt(lastShown)) > COOLDOWN) {
                    // Show Ad if loaded
                    if (adLoaded) {
                        interstitial.show();
                        await AsyncStorage.setItem('last_interstitial_shown', now.toString());
                    } else {
                        // Watch for load logic if strictly required, but mostly passive here
                    }
                }
            } catch (e) {
                console.error("Ad cooldown error", e);
            }
        };

        if (adLoaded) {
            checkAdCooldown();
        }
    }, [adLoaded, isPro, title]);

    const fetchCollectionItems = async () => {
        try {
            const apiUrl = `${getBackendUrl()}/collections/${id}/items`;
            const response = await fetchWithToken(apiUrl);
            if (!response.ok) throw new Error('Network error');
            const data: TriviaItem[] = await response.json();
            setItems(data);
            setFilteredItems(data);

            // Extract unique categories safely
            if (Array.isArray(data)) {
                const cats = Array.from(new Set(data.filter(item => item && item.category).map(item => item.category))).filter(Boolean);
                setCategories(cats);
            }

        } catch (error) {
            Alert.alert('エラー', 'データの取得に失敗しました');
        } finally {
            setLoading(false);
        }
    };

    const handleFilter = (category: string | null) => {
        setSelectedCategory(category);
        if (category) {
            setFilteredItems(items.filter(i => i.category === category));
        } else {
            setFilteredItems(items);
        }
    };

    const renderItem = ({ item }: { item: TriviaItem }) => (
        <Pressable
            style={styles.itemContainer}
            onPress={() => {
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
            }}
        >
            <View style={styles.itemIcon}>
                <Ionicons name="bulb" size={28} color={Colors.light.accent} />
            </View>
            <View style={styles.itemContent}>
                <Text style={styles.itemTitle}>{item.title}</Text>
                <Text style={styles.itemPreview} numberOfLines={1}>{item.content}</Text>
                <View style={styles.tagBadge}>
                    <Text style={styles.tagText}>{item.category || 'その他'}</Text>
                </View>
            </View>
            <Ionicons name="chevron-forward" size={20} color="#ccc" />
        </Pressable>
    );

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Pressable onPress={() => router.back()} style={styles.backButton}>
                    <Ionicons name="arrow-back" size={24} color={Colors.light.primary} />
                </Pressable>
                <Text style={styles.headerTitle} numberOfLines={1}>{title || 'フォルダの中身'}</Text>
                <View style={{ width: 40 }} />
            </View>

            {/* Category Filter */}
            {categories.length > 0 && (
                <View style={styles.filterContainer}>
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 20 }}>
                        <Pressable
                            style={[styles.filterChip, selectedCategory === null && styles.filterChipActive]}
                            onPress={() => handleFilter(null)}
                        >
                            <Text style={[styles.filterText, selectedCategory === null && styles.filterTextActive]}>すべて</Text>
                        </Pressable>
                        {categories.map(cat => (
                            <Pressable
                                key={cat}
                                style={[styles.filterChip, selectedCategory === cat && styles.filterChipActive]}
                                onPress={() => handleFilter(cat)}
                            >
                                <Text style={[styles.filterText, selectedCategory === cat && styles.filterTextActive]}>{cat}</Text>
                            </Pressable>
                        ))}
                    </ScrollView>
                </View>
            )}

            {loading ? (
                <View style={styles.center}>
                    <ActivityIndicator size="large" color="#007AFF" />
                </View>
            ) : (
                <FlatList
                    data={filteredItems}
                    renderItem={renderItem}
                    keyExtractor={item => item.id.toString()}
                    contentContainerStyle={styles.listContent}
                    ListEmptyComponent={
                        <View style={styles.emptyContainer}>
                            <Text style={styles.emptyText}>まだ保存された雑学はありません</Text>
                        </View>
                    }
                />
            )}
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: Colors.light.background,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        padding: 20,
        backgroundColor: 'transparent',
    },
    backButton: {
        padding: 8,
        borderRadius: 20,
        backgroundColor: '#F5F5F5',
        ...Theme.shadow.small,
    },
    headerTitle: {
        fontSize: 22, // Slightly smaller to fit
        fontWeight: '900',
        color: Colors.light.primary,
        flex: 1,
        textAlign: 'center',
    },
    center: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
    },
    listContent: {
        padding: 20,
        paddingBottom: 100,
    },
    itemContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: Colors.light.cardBackground,
        padding: 16,
        marginBottom: 16,
        borderRadius: Theme.borderRadius.m,
        ...Theme.shadow.small,
        borderWidth: 2,
        borderColor: Colors.light.border,
    },
    itemIcon: {
        width: 48,
        height: 48,
        borderRadius: 24,
        backgroundColor: '#FFF8E1', // Pale yellow
        justifyContent: 'center',
        alignItems: 'center',
        marginRight: 16,
        borderWidth: 2,
        borderColor: 'white',
    },
    itemContent: {
        flex: 1,
        marginRight: 8,
    },
    itemTitle: {
        fontSize: 16,
        fontWeight: 'bold',
        marginBottom: 4,
        color: Colors.light.text,
    },
    itemPreview: {
        fontSize: 13,
        color: Colors.light.subtext,
        fontWeight: '500',
        marginBottom: 6,
    },
    emptyContainer: {
        padding: 40,
        alignItems: 'center',
    },
    emptyText: {
        color: Colors.light.subtext,
        fontSize: 16,
        fontWeight: 'bold',
    },
    // Filter Styles
    filterContainer: {
        marginBottom: 10,
        height: 40,
    },
    filterChip: {
        paddingHorizontal: 16,
        paddingVertical: 8,
        borderRadius: 20,
        backgroundColor: Colors.light.cardBackground,
        marginRight: 8,
        borderWidth: 1,
        borderColor: Colors.light.border,
    },
    filterChipActive: {
        backgroundColor: Colors.light.primary,
        borderColor: Colors.light.primary,
    },
    filterText: {
        fontSize: 13,
        fontWeight: '600',
        color: Colors.light.subtext,
    },
    filterTextActive: {
        color: 'white',
    },
    tagBadge: {
        backgroundColor: '#E3F2FD',
        alignSelf: 'flex-start',
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 8,
    },
    tagText: {
        fontSize: 10,
        color: '#1565C0',
        fontWeight: 'bold',
    }
});
