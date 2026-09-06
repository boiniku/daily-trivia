import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator, Alert, Platform, ScrollView, TextInput } from 'react-native';
import React, { useState, useEffect, useCallback, useRef } from 'react';
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
    image_url?: string | null;
}

const INTERSTITIAL_ID = Platform.OS === 'ios'
    ? Config.INTERSTITIAL_ID_IOS
    : Config.INTERSTITIAL_ID_ANDROID;

const interstitial = InterstitialAd.createForAdRequest(INTERSTITIAL_ID, {
    requestNonPersonalizedAdsOnly: true,
});

const HISTORY_PAGE_SIZE = 50;

export default function CollectionDetailsScreen() {
    const { id, title } = useLocalSearchParams();
    const router = useRouter();
    const normalizedCollectionId = Array.isArray(id) ? id[0] : id;
    const [items, setItems] = useState<TriviaItem[]>([]);
    const [filteredItems, setFilteredItems] = useState<TriviaItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchText, setSearchText] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [total, setTotal] = useState(0);
    const [currentPage, setCurrentPage] = useState(1);
    const searchRequestId = useRef(0);
    const { isPro } = useRevenueCat();

    // Filtering & Sorting
    const [categories, setCategories] = useState<string[]>([]);
    const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
    const [sortType, setSortType] = useState<'default' | 'total' | 'user'>('default');

    // Ads
    const pendingNavigationRef = useRef<(() => void) | null>(null);
    const isOpeningItemRef = useRef(false);
    const normalizedTitle = Array.isArray(title) ? title[0] : title;
    const isHistoryCollection = (normalizedTitle ?? '').trim().includes('過去に見た雑学');

    const tryShowInterstitial = useCallback(async (reason: string): Promise<boolean> => {
        if (isPro) return false;
        if (!isHistoryCollection) return false;
        if (!interstitial.loaded) return false;

        try {
            const lastShown = await AsyncStorage.getItem('last_interstitial_shown');
            const now = Date.now();
            const COOLDOWN = 5 * 60 * 1000; // 5 minutes
            const parsedLastShown = Number(lastShown);
            const hasValidLastShown = Number.isFinite(parsedLastShown) && parsedLastShown > 0;
            const isCooldownPassed = !hasValidLastShown || (now - parsedLastShown) > COOLDOWN;
            if (isCooldownPassed) {
                console.log('[Ads] Showing interstitial:', { reason, interstitialId: INTERSTITIAL_ID });
                await interstitial.show();
                await AsyncStorage.setItem('last_interstitial_shown', now.toString());
                return true;
            } else {
                console.log('[Ads] Interstitial cooldown active');
            }
        } catch (e) {
            console.error("Ad cooldown error", e);
        }
        return false;
    }, [isHistoryCollection, isPro]);

    useEffect(() => {
        // Ad Logic
        if (!isPro && isHistoryCollection) {
            console.log('[Ads] Interstitial setup:', {
                interstitialId: INTERSTITIAL_ID,
                isHistoryCollection,
                title: normalizedTitle ?? '',
            });

            const unsubscribe = interstitial.addAdEventListener(AdEventType.LOADED, () => {
                console.log('[Ads] Interstitial loaded');
            });

            const unsubscribeClosed = interstitial.addAdEventListener(AdEventType.CLOSED, () => {
                const navigate = pendingNavigationRef.current;
                pendingNavigationRef.current = null;
                isOpeningItemRef.current = false;
                navigate?.();
                interstitial.load();
            });
            const unsubscribeError = interstitial.addAdEventListener(AdEventType.ERROR, (error) => {
                console.error('[Ads] Interstitial failed to load/show:', error);
                const navigate = pendingNavigationRef.current;
                pendingNavigationRef.current = null;
                isOpeningItemRef.current = false;
                navigate?.();
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
    }, [isPro, isHistoryCollection, normalizedTitle]);

    const normalizeTriviaItems = (rawData: unknown): TriviaItem[] => {
        if (!Array.isArray(rawData)) return [];

        return rawData
            .map((item) => {
                if (!item || typeof item !== 'object') return null;

                const rawItem = item as Partial<TriviaItem> & {
                    id?: unknown;
                    hee_count?: unknown;
                    user_hee_count?: unknown;
                    image_url?: unknown;
                };

                const numericId = Number(rawItem.id);
                if (!Number.isFinite(numericId)) return null;

                return {
                    id: numericId,
                    title: typeof rawItem.title === 'string' ? rawItem.title : 'タイトルなし',
                    content: typeof rawItem.content === 'string' ? rawItem.content : '',
                    explanation: typeof rawItem.explanation === 'string' ? rawItem.explanation : '解説データがありません',
                    source: typeof rawItem.source === 'string' ? rawItem.source : '',
                    category: typeof rawItem.category === 'string' ? rawItem.category : 'その他',
                    image_url: typeof rawItem.image_url === 'string' ? rawItem.image_url : null,
                    hee_count: Number.isFinite(Number(rawItem.hee_count)) ? Number(rawItem.hee_count) : 0,
                    user_hee_count: Number.isFinite(Number(rawItem.user_hee_count)) ? Number(rawItem.user_hee_count) : 0,
                };
            })
            .filter(Boolean) as TriviaItem[];
    };

    const fetchCollectionItems = async () => {
        try {
            if (!normalizedCollectionId) {
                throw new Error('Collection id is missing');
            }

            const apiUrl = `${getBackendUrl()}/collections/${normalizedCollectionId}/items?t=${Date.now()}`;
            const response = await fetchWithToken(apiUrl);
            if (!response.ok) throw new Error('Network error');
            const rawData = await response.json();
            const normalizedItems = normalizeTriviaItems(rawData);
            setItems(normalizedItems);

            const cats = Array.from(new Set(normalizedItems.map(item => item.category))).filter(Boolean);
            setCategories(cats);

        } catch (error) {
            Alert.alert('エラー', 'データの取得に失敗しました');
        } finally {
            setLoading(false);
        }
    };

    const fetchHistoryItems = async () => {
        if (!normalizedCollectionId) return;

        const requestId = ++searchRequestId.current;
        const offset = (currentPage - 1) * HISTORY_PAGE_SIZE;
        setLoading(true);

        try {
            const params = [
                `q=${encodeURIComponent(debouncedSearch.trim())}`,
                `sort=${encodeURIComponent(sortType)}`,
                `limit=${HISTORY_PAGE_SIZE}`,
                `offset=${offset}`,
            ];
            if (selectedCategory) {
                params.push(`category=${encodeURIComponent(selectedCategory)}`);
            }

            const apiUrl = `${getBackendUrl()}/collections/${normalizedCollectionId}/items/search?${params.join('&')}`;
            const response = await fetchWithToken(apiUrl);
            if (!response.ok) throw new Error('Network error');
            const rawData = await response.json();
            if (requestId !== searchRequestId.current) return;

            const nextItems = normalizeTriviaItems(rawData?.items);
            setItems(nextItems);
            setCategories(Array.isArray(rawData?.categories)
                ? rawData.categories.filter((value: unknown): value is string => typeof value === 'string' && value.length > 0)
                : []);
            setTotal(Number.isFinite(Number(rawData?.total)) ? Number(rawData.total) : nextItems.length);
        } catch (error) {
            if (requestId === searchRequestId.current) {
                Alert.alert('エラー', '検索結果の取得に失敗しました');
            }
        } finally {
            if (requestId === searchRequestId.current) {
                setLoading(false);
            }
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => setDebouncedSearch(searchText), 300);
        return () => clearTimeout(timer);
    }, [searchText]);

    useEffect(() => {
        if (isHistoryCollection) {
            fetchHistoryItems();
        } else {
            fetchCollectionItems();
        }
    }, [normalizedCollectionId, isHistoryCollection, debouncedSearch, selectedCategory, sortType, currentPage]);

    const applySortAndFilter = (cat: string | null, sort: 'default' | 'total' | 'user', data: TriviaItem[]) => {
        let result = [...data];
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

    useEffect(() => {
        if (isHistoryCollection) {
            setFilteredItems(items);
        } else {
            applySortAndFilter(selectedCategory, sortType, items);
        }
    }, [items, selectedCategory, sortType, isHistoryCollection]);

    const handleFilter = (category: string | null) => {
        setCurrentPage(1);
        setSelectedCategory(category);
        if (!isHistoryCollection) applySortAndFilter(category, sortType, items);
    };

    const handleSort = (sort: 'default' | 'total' | 'user') => {
        setCurrentPage(1);
        setSortType(sort);
        if (!isHistoryCollection) applySortAndFilter(selectedCategory, sort, items);
    };

    const totalPages = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE));
    const firstVisiblePage = Math.max(1, Math.min(currentPage - 2, totalPages - 4));
    const visiblePages = Array.from(
        { length: Math.min(5, totalPages) },
        (_, index) => firstVisiblePage + index,
    );

    const openTrivia = useCallback((item: TriviaItem) => {
        router.push({
            pathname: '/details',
            params: {
                id: item.id,
                user_hee_count: item.user_hee_count,
                image_url: item.image_url ?? ''
            }
        });
    }, [router]);

    const handleItemPress = useCallback(async (item: TriviaItem) => {
        if (isOpeningItemRef.current) return;
        isOpeningItemRef.current = true;

        const navigate = () => openTrivia(item);
        pendingNavigationRef.current = navigate;
        const didShowAd = await tryShowInterstitial('history_item_tap');

        if (!didShowAd && pendingNavigationRef.current) {
            pendingNavigationRef.current = null;
            isOpeningItemRef.current = false;
            navigate();
        }
    }, [openTrivia, tryShowInterstitial]);

    const renderItem = ({ item }: { item: TriviaItem }) => (
        <Pressable
            style={styles.itemContainer}
            onPress={() => handleItemPress(item)}
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
            {isHistoryCollection && (
                <View style={styles.searchSection}>
                    <View style={styles.searchContainer}>
                        <Ionicons name="search" size={20} color={Colors.light.subtext} />
                        <TextInput
                            value={searchText}
                            onChangeText={(value) => {
                                setCurrentPage(1);
                                setSearchText(value);
                            }}
                            placeholder="見た雑学を検索"
                            placeholderTextColor={Colors.light.subtext}
                            style={styles.searchInput}
                            returnKeyType="search"
                            autoCorrect={false}
                            maxLength={100}
                        />
                        {searchText.length > 0 && (
                            <Pressable onPress={() => {
                                setCurrentPage(1);
                                setSearchText('');
                            }} hitSlop={10}>
                                <Ionicons name="close-circle" size={20} color={Colors.light.subtext} />
                            </Pressable>
                        )}
                    </View>
                    {!loading && (
                        <Text style={styles.resultCount}>{total}件</Text>
                    )}
                </View>
            )}
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
                <View style={styles.listArea}>
                    <FlatList
                        data={filteredItems}
                        renderItem={renderItem}
                        keyExtractor={item => String(item.id)}
                        contentContainerStyle={styles.listContent}
                        ListEmptyComponent={
                            <View style={styles.emptyContainer}>
                                <Text style={styles.emptyText}>
                                    {isHistoryCollection && debouncedSearch.trim()
                                        ? '検索に一致する雑学はありません'
                                        : 'まだ保存された雑学はありません'}
                                </Text>
                            </View>
                        }
                    />
                    {isHistoryCollection && total > 0 && (
                        <View style={styles.pagination}>
                            <Pressable
                                style={[styles.pageButton, currentPage === 1 && styles.pageButtonDisabled]}
                                disabled={currentPage === 1}
                                onPress={() => setCurrentPage((page) => Math.max(1, page - 1))}
                            >
                                <Ionicons name="chevron-back" size={18} color={currentPage === 1 ? '#BBB' : Colors.light.primary} />
                            </Pressable>
                            {visiblePages.map((page) => (
                                <Pressable
                                    key={page}
                                    style={[styles.pageButton, currentPage === page && styles.pageButtonActive]}
                                    onPress={() => setCurrentPage(page)}
                                >
                                    <Text style={[styles.pageButtonText, currentPage === page && styles.pageButtonTextActive]}>{page}</Text>
                                </Pressable>
                            ))}
                            <Pressable
                                style={[styles.pageButton, currentPage === totalPages && styles.pageButtonDisabled]}
                                disabled={currentPage === totalPages}
                                onPress={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                            >
                                <Ionicons name="chevron-forward" size={18} color={currentPage === totalPages ? '#BBB' : Colors.light.primary} />
                            </Pressable>
                        </View>
                    )}
                </View>
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
        paddingBottom: 20,
    },
    listArea: {
        flex: 1,
    },
    searchSection: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 20,
        marginBottom: 12,
        gap: 10,
    },
    searchContainer: {
        flex: 1,
        minHeight: 46,
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 14,
        borderRadius: 14,
        backgroundColor: Colors.light.cardBackground,
        borderWidth: 1,
        borderColor: Colors.light.border,
        gap: 10,
    },
    searchInput: {
        flex: 1,
        paddingVertical: 10,
        fontSize: 16,
        color: Colors.light.text,
    },
    resultCount: {
        minWidth: 42,
        textAlign: 'right',
        color: Colors.light.subtext,
        fontSize: 13,
        fontWeight: '700',
    },
    pagination: {
        minHeight: 62,
        flexDirection: 'row',
        justifyContent: 'center',
        alignItems: 'center',
        gap: 7,
        paddingHorizontal: 12,
        paddingBottom: 10,
        backgroundColor: Colors.light.background,
    },
    pageButton: {
        width: 36,
        height: 36,
        borderRadius: 18,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: Colors.light.cardBackground,
        borderWidth: 1,
        borderColor: Colors.light.border,
    },
    pageButtonActive: {
        backgroundColor: Colors.light.primary,
        borderColor: Colors.light.primary,
    },
    pageButtonDisabled: {
        opacity: 0.55,
    },
    pageButtonText: {
        color: Colors.light.primary,
        fontSize: 14,
        fontWeight: '800',
    },
    pageButtonTextActive: {
        color: 'white',
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
