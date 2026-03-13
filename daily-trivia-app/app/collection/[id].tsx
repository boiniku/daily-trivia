import { useLocalSearchParams, useRouter, useFocusEffect } from 'expo-router';
import { View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator, Alert, Platform, ScrollView } from 'react-native';
import React, { useState, useEffect, useCallback } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Config } from '../../constants/Config';
import { Theme, Colors } from '../../constants/Colors';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import { InterstitialAd, AdEventType } from 'react-native-google-mobile-ads';
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
    hee_count?: number;
    user_hee_count?: number;
}

const INTERSTITIAL_ID = Platform.OS === 'ios'
    ? Config.INTERSTITIAL_ID_IOS
    : Config.INTERSTITIAL_ID_ANDROID;

const interstitial = InterstitialAd.createForAdRequest(INTERSTITIAL_ID, {
    requestNonPersonalizedAdsOnly: true,
});

export default function CollectionDetailsScreen() {
    const { id, title } = useLocalSearchParams();
    const router = useRouter();
    const [items, setItems] = useState<TriviaItem[]>([]);
    const [filteredItems, setFilteredItems] = useState<TriviaItem[]>([]);
    const [loading, setLoading] = useState(true);
    const { isPro } = useRevenueCat();

    // Filtering & Sorting
    const [categories, setCategories] = useState<string[]>([]);
    const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
    const [sortType, setSortType] = useState<'default' | 'total' | 'user'>('default');

    // Ads
    const [adLoaded, setAdLoaded] = useState(false);
    const normalizedTitle = Array.isArray(title) ? title[0] : title;
    const isHistoryCollection = (normalizedTitle ?? '').trim().includes('過去に見た雑学');

    useFocusEffect(
        useCallback(() => {
            fetchCollectionItems();
        }, [id])
    );

    useEffect(() => {
        // Ad Logic
        if (!isPro) {
            if (interstitial.loaded) {
                setAdLoaded(true);
            }

            const unsubscribe = interstitial.addAdEventListener(AdEventType.LOADED, () => {
                setAdLoaded(true);
            });

            const unsubscribeClosed = interstitial.addAdEventListener(AdEventType.CLOSED, () => {
                setAdLoaded(false);
                interstitial.load();
            });
            const unsubscribeError = interstitial.addAdEventListener(AdEventType.ERROR, (error) => {
                setAdLoaded(false);
                console.error('[Ads] Interstitial failed to load/show:', error);
            });

            if (!interstitial.loaded) {
                interstitial.load();
            }

            return () => {
                unsubscribe();
                unsubscribeClosed();
                unsubscribeError();
            };
        }
    }, [id, isPro]);

    // Reverting ad check function to fire when the folder opens (or ad loads while open)
    useEffect(() => {
        const triggerAdIfReady = async () => {
            if (isPro) return; // サブスク(Pro)に加入している場合はここで早期リターンし、広告は表示されません
            if (!isHistoryCollection) return; // 過去に見た雑学フォルダのみで表示
            if (!adLoaded && !interstitial.loaded) return;

            try {
                const lastShown = await AsyncStorage.getItem('last_interstitial_shown');
                const now = Date.now();
                const COOLDOWN = 5 * 60 * 1000; // 5 minutes 

                if (!lastShown || (now - parseInt(lastShown)) > COOLDOWN) {
                    interstitial.show();
                    await AsyncStorage.setItem('last_interstitial_shown', now.toString());
                }
            } catch (e) {
                console.error("Ad cooldown error", e);
            }
        };

        if (adLoaded || interstitial.loaded) {
            triggerAdIfReady();
        }
    }, [adLoaded, isPro, isHistoryCollection]);

    const fetchCollectionItems = async () => {
        try {
            const apiUrl = `${getBackendUrl()}/collections/${id}/items?t=${Date.now()}`;
            const response = await fetchWithToken(apiUrl);
            if (!response.ok) throw new Error('Network error');
            const data: TriviaItem[] = await response.json();
            setItems(data);
            applySortAndFilter(selectedCategory, sortType, data);

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

    const applySortAndFilter = (cat: string | null, sort: 'default' | 'total' | 'user', data: TriviaItem[]) => {
        let result = data;
        if (cat) {
            result = result.filter(i => i.category === cat);
        }
        if (sort === 'total') {
            result = [...result].sort((a, b) => (b.hee_count || 0) - (a.hee_count || 0));
        } else if (sort === 'user') {
            result = [...result].sort((a, b) => (b.user_hee_count || 0) - (a.user_hee_count || 0));
        }
        setFilteredItems(result);
    };

    const handleFilter = (category: string | null) => {
        setSelectedCategory(category);
        applySortAndFilter(category, sortType, items);
    };

    const handleSort = (sort: 'default' | 'total' | 'user') => {
        setSortType(sort);
        applySortAndFilter(selectedCategory, sort, items);
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
                        content: item.content,
                        user_hee_count: item.user_hee_count
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
                <View style={styles.badgeRow}>
                    <View style={styles.tagBadge}>
                        <Text style={styles.tagText}>{item.category || 'その他'}</Text>
                    </View>
                    {(sortType === 'total' || sortType === 'user') && (
                        <View style={styles.heeBadge}>
                            <Text style={styles.heeBadgeText}>
                                {sortType === 'total' ? `${item.hee_count || 0} へぇ` : `自分: ${item.user_hee_count || 0} へぇ`}
                            </Text>
                        </View>
                    )}
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
                <Text style={styles.headerTitle} numberOfLines={1}>{normalizedTitle || 'フォルダの中身'}</Text>
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

            {/* Sort Filter */}
            <View style={styles.filterContainer}>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 20 }}>
                    <Pressable
                        style={[styles.filterChip, sortType === 'default' && styles.filterChipActive]}
                        onPress={() => handleSort('default')}
                    >
                        <Text style={[styles.filterText, sortType === 'default' && styles.filterTextActive]}>追加順</Text>
                    </Pressable>
                    <Pressable
                        style={[styles.filterChip, sortType === 'total' && styles.filterChipActive]}
                        onPress={() => handleSort('total')}
                    >
                        <Text style={[styles.filterText, sortType === 'total' && styles.filterTextActive]}>全ユーザーへぇ順</Text>
                    </Pressable>
                    <Pressable
                        style={[styles.filterChip, sortType === 'user' && styles.filterChipActive]}
                        onPress={() => handleSort('user')}
                    >
                        <Text style={[styles.filterText, sortType === 'user' && styles.filterTextActive]}>自分のへぇ順</Text>
                    </Pressable>
                </ScrollView>
            </View>

            {loading ? (
                <View style={styles.center}>
                    <ActivityIndicator size="large" color={Colors.light.primary} />
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
    },
    badgeRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    heeBadge: {
        backgroundColor: '#FFF8E1',
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 8,
    },
    heeBadgeText: {
        fontSize: 10,
        color: '#F57F17',
        fontWeight: 'bold',
    }
});
