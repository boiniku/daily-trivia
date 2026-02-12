import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, StyleSheet, ScrollView, Pressable, Modal, FlatList, ActivityIndicator, Alert, TouchableOpacity, Platform } from 'react-native';
import { BannerAd, BannerAdSize, TestIds } from 'react-native-google-mobile-ads';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Theme, Colors } from '../constants/Colors';
import { useRevenueCat } from '../contexts/RevenueCatContext';
import { useState, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Config } from '../constants/Config';
import * as Crypto from 'expo-crypto';

const getBackendUrl = () => {
    return Config.BACKEND_URL;
};

interface Collection {
    id: number;
    title: string;
    icon: string;
    is_locked: boolean;
}

export default function DetailsScreen() {
    const params = useLocalSearchParams();
    const router = useRouter();
    const { isPro } = useRevenueCat();

    // Data passed from index.tsx
    const id = params.id as string;
    const title = params.title as string || 'タイトルなし';
    const explanation = params.explanation as string || '解説データがありません';
    const source = params.source as string || '';
    const category = params.category as string || '未分類';
    const content = params.content as string || '';

    // Add to Folder State
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [collections, setCollections] = useState<Collection[]>([]);
    const [loadingCollections, setLoadingCollections] = useState(false);
    const [adding, setAdding] = useState(false);

    const fetchCollections = async () => {
        setLoadingCollections(true);
        try {
            const userId = await AsyncStorage.getItem('user_id');
            const apiUrl = `${getBackendUrl()}/collections?user_id=${userId}`;
            const response = await fetch(apiUrl);
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
            setCollections(data.filter((c: Collection) => c.title !== "過去に見た雑学"));
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
            const userId = await AsyncStorage.getItem('user_id');
            const response = await fetch(`${getBackendUrl()}/collections/${collectionId}/items`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    trivia_id: id, // Assuming we have the ID, wait. params.id might be undefined if not passed?
                    // We need to ensure we have the trivia ID or content to save.
                    // The backend `POST /collections/{id}/items` expects `trivia_id`.
                    // Does `details.tsx` receive `id`? Yes, line 28.
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
                            <Text style={styles.categoryText}>{category}</Text>
                        </View>
                    </View>

                    <Text style={styles.title}>{title}</Text>

                    <View style={styles.cardSection}>
                        <Text style={styles.mainContent}>{content}</Text>
                    </View>

                    <View style={styles.section}>
                        <View style={styles.sectionHeader}>
                            <Ionicons name="information-circle" size={20} color={Colors.light.primary} style={{ marginRight: 8 }} />
                            <Text style={styles.sectionTitle}>詳細解説</Text>
                        </View>
                        <Text style={styles.text}>{explanation}</Text>
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
    }
});
