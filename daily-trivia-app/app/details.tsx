import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, StyleSheet, ScrollView, Pressable, Modal, FlatList, ActivityIndicator, Alert, TouchableOpacity, Platform, Linking, Image } from 'react-native';
import { BannerAd, BannerAdSize } from 'react-native-google-mobile-ads';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Theme, Colors } from '../constants/Colors';
import { useRevenueCat } from '../contexts/RevenueCatContext';
import { useState, useEffect } from 'react';
import { Config } from '../constants/Config';
import { useAuth } from '../contexts/AuthContext';
import HeeButton from '../components/HeeButton';
import { fetchWithToken } from '../utils/apiClient';

const getBackendUrl = () => {
    return Config.BACKEND_URL;
};

interface Collection {
    id: number;
    title: string;
    icon: string;
    is_locked: boolean;
    hee_count?: number;
    user_hee_count?: number;
}

export default function DetailsScreen() {
    const params = useLocalSearchParams();
    const router = useRouter();
    const { isPro } = useRevenueCat();
    const { userId } = useAuth();

    const getSingleParam = (value: string | string[] | undefined) => {
        if (Array.isArray(value)) return value[0] ?? '';
        return value ?? '';
    };

    const idParam = getSingleParam(params.id);
    const triviaId = Number(idParam);
    const hasValidTriviaId = Number.isFinite(triviaId);
    const initialUserHeeCount = Number(getSingleParam(params.user_hee_count));

    // State to hold potentially fetched full data
    const [fullData, setFullData] = useState({
        title: getSingleParam(params.title) || 'タイトルなし',
        explanation: getSingleParam(params.explanation) || '解説データがありません',
        source: getSingleParam(params.source) || '',
        category: getSingleParam(params.category) || '未分類',
        content: getSingleParam(params.content) || '',
        image_url: getSingleParam(params.image_url) || '',
        user_hee_count: Number.isFinite(initialUserHeeCount) ? initialUserHeeCount : 0
    });
    const [loadingDetails, setLoadingDetails] = useState(false);


    // Always fetch by id for consistency and to avoid relying on long route params.
    useEffect(() => {
        const fetchFullDetails = async () => {
            if (!hasValidTriviaId) return;
            setLoadingDetails(true);
            try {
                const response = await fetchWithToken(`${getBackendUrl()}/trivia/${triviaId}`);
                if (response.ok) {
                    const data = await response.json();
                    setFullData(prev => ({
                        title: data.title || prev.title,
                        explanation: data.explanation || '解説データがありません',
                        source: data.source || prev.source,
                        category: data.category || prev.category,
                        content: data.content || prev.content,
                        image_url: data.image_url || prev.image_url,
                        user_hee_count: data.user_hee_count !== undefined ? data.user_hee_count : prev.user_hee_count
                    }));
                }
            } catch (e) {
                console.error("Failed to fetch full trivia details", e);
            } finally {
                setLoadingDetails(false);
            }
        };
        fetchFullDetails();
    }, [hasValidTriviaId, triviaId]);

    const triviaImageUrl = (() => {
        const rawUrl = fullData.image_url.trim();
        if (!rawUrl) return '';
        if (/^https?:\/\//i.test(rawUrl) || rawUrl.startsWith('data:')) return rawUrl;
        const baseUrl = Config.TRIVIA_IMAGE_R2_BASE_URL.trim().replace(/\/+$/, '');
        const path = rawUrl.replace(/^\/+/, '');
        return baseUrl ? `${baseUrl}/${path}` : '';
    })();

    // Add to Folder State
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [collections, setCollections] = useState<Collection[]>([]);
    const [loadingCollections, setLoadingCollections] = useState(false);
    const [adding, setAdding] = useState(false);

    const fetchCollections = async () => {
        setLoadingCollections(true);
        try {
            if (!userId) return;
            const apiUrl = `${getBackendUrl()}/collections`;
            const response = await fetchWithToken(apiUrl);
            if (!response.ok) throw new Error('Fetch failed');
            const data = await response.json();
            // Filter out locked collections or "Past Trivia" if needed?
            // Usually "Past Trivia" is auto-managed, but user might want to explicitly add there?
            // Let's allow all unlocked collections.
            // Filter out "Past Trivia" (History) so user can't manually add to it
            // Allow "Favorites" (even if locked in some contexts, here it's just a folder to add to)
            // But logic says: "collection.is_locked" is true for favorites. 
            // We want to allow Favorites (idk title yet, assume "お気に入り") but disallow "過去に見た雑学".
            // Actually, "Favorites" is created with is_locked=True in backend.
            // So we should filter: (NOT "過去に見た雑学")
            setCollections(data.filter((c: Collection) => c.title !== "過去に見た雑学" && (isPro || !c.is_locked)));
        } catch (error) {
            Alert.alert('エラー', 'フォルダの取得に失敗しました');
        } finally {
            setLoadingCollections(false);
        }
    };

    const handleOpenModal = () => {
        setIsModalVisible(true);
        fetchCollections();
    };

    const addToCollection = async (collectionId: number) => {
        setAdding(true);
        try {
            if (!userId || !hasValidTriviaId) return;
            const response = await fetchWithToken(`${getBackendUrl()}/collections/${collectionId}/items`, {
                method: 'POST',
                body: JSON.stringify({
                    trivia_id: triviaId,
                })
            });

            if (!response.ok) {
                const text = await response.text();
                throw new Error(text);
            }

            Alert.alert('成功', 'フォルダに追加しました');
            setIsModalVisible(false);
        } catch (error) {
            console.error(error);
            Alert.alert('エラー', '追加に失敗しました');
        } finally {
            setAdding(false);
        }
    };

    return (
        <View style={styles.container}>
            <SafeAreaView edges={['top']} style={{ flex: 1 }}>
                <View style={styles.header}>
                    <Pressable onPress={() => {
                        if (router.canGoBack()) {
                            router.back();
                        } else {
                            router.replace('/');
                        }
                    }} style={styles.backButton}>
                        <Ionicons name="arrow-back" size={24} color={Colors.light.text} />
                    </Pressable>
                    <Text style={styles.headerTitle}>解説</Text>

                    {/* Add to Folder Button (Pro only) */}
                    {isPro ? (
                        <Pressable onPress={handleOpenModal} style={styles.addButton}>
                            <Ionicons name="folder-open-outline" size={24} color={Colors.light.primary} />
                        </Pressable>
                    ) : (
                        <View style={{ width: 40 }} />
                    )}
                </View>

                <ScrollView contentContainerStyle={styles.content}>
                    <View style={styles.badgeContainer}>
                        <View style={styles.categoryBadge}>
                            <Ionicons name="library" size={12} color="white" style={{ marginRight: 4 }} />
                            <Text style={styles.categoryText}>{fullData.category}</Text>
                        </View>
                    </View>

                    <Text style={styles.title}>{fullData.title}</Text>

                    {triviaImageUrl ? (
                        <Image
                            source={{ uri: triviaImageUrl }}
                            style={styles.heroImage}
                            resizeMode="cover"
                            accessibilityLabel={`${fullData.title}の写真`}
                        />
                    ) : null}

                    <View style={styles.cardSection}>
                        <Text style={styles.mainContent}>{fullData.content}</Text>
                    </View>

                    {/* Action Buttons Row */}
                    <View style={styles.actionRow}>
                        {hasValidTriviaId ? (
                            <HeeButton triviaId={triviaId} onHeeAdded={(count) => {
                                setFullData(prev => ({
                                    ...prev,
                                    user_hee_count: prev.user_hee_count + count
                                }));
                            }} />
                        ) : (
                            <View />
                        )}

                        <Pressable style={styles.shareButton} onPress={() => {
                            const shareText = `【${fullData.title}】\n${fullData.content}\n\n#毎日雑学`;
                            // Use Universal Link for better handling
                            const shareUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}`;
                            Linking.openURL(shareUrl).catch((err) => console.error('An error occurred', err));
                        }}>
                            <Ionicons name="logo-twitter" size={20} color="white" />
                            <Text style={styles.shareButtonText}>ポスト</Text>
                        </Pressable>
                    </View>

                    {!hasValidTriviaId && (
                        <View style={styles.section}>
                            <Text style={styles.text}>雑学IDを読み取れなかったため、操作を一部無効化しています。</Text>
                        </View>
                    )}

                    <View style={styles.section}>
                        <View style={styles.sectionHeader}>
                            <Ionicons name="information-circle" size={20} color={Colors.light.primary} style={{ marginRight: 8 }} />
                            <Text style={styles.sectionTitle}>詳細解説</Text>
                        </View>
                        {loadingDetails ? (
                            <ActivityIndicator size="small" color={Colors.light.primary} style={{ marginTop: 10, alignSelf: 'flex-start' }} />
                        ) : (
                            <Text style={styles.text}>{fullData.explanation}</Text>
                        )}
                    </View>

                    {/* source ? (
                        <View style={[styles.section, { borderBottomWidth: 0 }]}>
                            <View style={styles.sectionHeader}>
                                <Ionicons name="book" size={20} color={Colors.light.subtext} style={{ marginRight: 8 }} />
                                <Text style={styles.sourceTitle}>出典・参考</Text>
                            </View>
                            <Text style={styles.sourceText}>{source}</Text>
                        </View>
                    ) : null */}
                </ScrollView>

                {/* Banner Ad */}
                {!isPro && (
                    <View style={styles.adsContainer}>
                        <BannerAd
                            unitId={Platform.OS === 'ios' ? Config.BANNER_ID_IOS : Config.BANNER_ID_ANDROID}
                            size={BannerAdSize.ANCHORED_ADAPTIVE_BANNER}
                            requestOptions={{
                                requestNonPersonalizedAdsOnly: true,
                            }}
                        />
                    </View>
                )}

                {/* Add to Folder Modal */}
                <Modal
                    visible={isModalVisible}
                    transparent={true}
                    animationType="slide"
                    onRequestClose={() => setIsModalVisible(false)}
                >
                    <View style={styles.modalOverlay}>
                        <View style={styles.modalContent}>
                            <View style={styles.modalHeader}>
                                <Text style={styles.modalTitle}>フォルダに追加</Text>
                                <Pressable onPress={() => setIsModalVisible(false)}>
                                    <Ionicons name="close" size={24} color="#999" />
                                </Pressable>
                            </View>

                            {loadingCollections ? (
                                <ActivityIndicator size="large" color={Colors.light.primary} style={{ margin: 20 }} />
                            ) : (
                                <FlatList
                                    data={collections}
                                    keyExtractor={item => item.id.toString()}
                                    renderItem={({ item }) => (
                                        <TouchableOpacity
                                            style={styles.collectionItem}
                                            onPress={() => addToCollection(item.id)}
                                            disabled={adding}
                                        >
                                            <View style={styles.collectionIconBg}>
                                                <Ionicons name={item.icon as any} size={20} color={Colors.light.primary} />
                                            </View>
                                            <Text style={styles.collectionTitle}>{item.title}</Text>
                                            {adding && <ActivityIndicator size="small" color={Colors.light.primary} />}
                                        </TouchableOpacity>
                                    )}
                                    ListEmptyComponent={
                                        <Text style={{ textAlign: 'center', padding: 20, color: '#666' }}>
                                            フォルダがありません。{'\n'}保存場所タブから作成してください。
                                        </Text>
                                    }
                                />
                            )}
                        </View>
                    </View>
                </Modal>

            </SafeAreaView>
        </View>
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
        justifyContent: 'space-between',
        paddingHorizontal: 20,
        paddingVertical: 10,
    },
    backButton: {
        padding: 8,
        borderRadius: 20,
        backgroundColor: '#F0F2F5',
    },
    addButton: {
        padding: 8,
        borderRadius: 20,
        backgroundColor: '#FFF8E1',
    },
    headerTitle: {
        fontSize: 18,
        fontWeight: 'bold',
        color: Colors.light.text,
    },
    content: {
        padding: 20,
        paddingBottom: 40,
    },
    badgeContainer: {
        flexDirection: 'row',
        marginBottom: 16,
        justifyContent: 'center',
    },
    categoryBadge: {
        backgroundColor: Colors.light.primary,
        paddingHorizontal: 12,
        paddingVertical: 6,
        borderRadius: 20,
        flexDirection: 'row',
        alignItems: 'center',
    },
    categoryText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 12,
        letterSpacing: 1,
    },
    title: {
        fontSize: 26,
        fontWeight: '800',
        marginBottom: 24,
        color: Colors.light.text,
        textAlign: 'center',
        lineHeight: 34,
        letterSpacing: -0.5,
    },
    cardSection: {
        backgroundColor: '#FFFFFF', // Explicit white
        padding: 24,
        borderRadius: Theme.borderRadius.l,
        ...Theme.shadow.small,
        marginBottom: 32,
        borderWidth: 2, // Thicker border
        borderColor: '#EFEFEF',
    },
    heroImage: {
        width: '100%',
        aspectRatio: 16 / 9,
        borderRadius: Theme.borderRadius.l,
        marginBottom: 24,
        backgroundColor: '#EFEFEF',
    },
    mainContent: {
        fontSize: 18,
        color: '#111111', // Absolute black for contrast
        lineHeight: 30, // More breathing room
        textAlign: 'center',
        fontWeight: '500',
    },
    section: {
        marginBottom: 24,
        paddingBottom: 24,
        borderBottomWidth: 1,
        borderBottomColor: '#EEE',
    },
    sectionHeader: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: 12,
    },
    sectionTitle: {
        fontSize: 18,
        fontWeight: 'bold',
        color: Colors.light.primary,
    },
    text: {
        fontSize: 16,
        lineHeight: 28,
        color: '#222222', // Darker for readability
        textAlign: 'justify',
    },
    sourceTitle: {
        fontSize: 14,
        fontWeight: 'bold',
        color: Colors.light.subtext,
    },
    sourceText: {
        fontSize: 14,
        color: Colors.light.subtext,
        fontStyle: 'italic',
    },
    // Modal Styles
    modalOverlay: {
        flex: 1,
        backgroundColor: 'rgba(0,0,0,0.5)',
        justifyContent: 'flex-end',
    },
    modalContent: {
        backgroundColor: 'white',
        borderTopLeftRadius: 24,
        borderTopRightRadius: 24,
        padding: 20,
        maxHeight: '60%',
        ...Theme.shadow.pop,
    },
    modalHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 20,
    },
    modalTitle: {
        fontSize: 20,
        fontWeight: 'bold',
        color: Colors.light.text,
    },
    collectionItem: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 16,
        borderBottomWidth: 1,
        borderBottomColor: '#F0F0F0',
    },
    collectionIconBg: {
        width: 40,
        height: 40,
        borderRadius: 20,
        backgroundColor: '#FFF8E1',
        justifyContent: 'center',
        alignItems: 'center',
        marginRight: 16,
    },
    collectionTitle: {
        fontSize: 16,
        fontWeight: 'bold',
        color: Colors.light.text,
        flex: 1,
    },
    adsContainer: {
        alignItems: 'center',
        justifyContent: 'center',
        paddingVertical: 10,
        backgroundColor: Colors.light.background,
    },
    actionRow: {
        flexDirection: 'row',
        justifyContent: 'center',
        alignItems: 'flex-end', // Align bottoms
        gap: 16,
        marginBottom: 20,
    },
    shareButton: {
        backgroundColor: '#000000', // X black
        paddingVertical: 8,
        paddingHorizontal: 20,
        borderRadius: 50,
        flexDirection: 'row',
        alignItems: 'center',
        ...Theme.shadow.small,
        borderWidth: 2,
        borderColor: 'white',
        marginBottom: 10, // Match the marginVertical: 10 in HeeButton.tsx
    },
    shareButtonText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 14,
        marginLeft: 6,
    }
});
