import { useState, useCallback, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable, FlatList, ActivityIndicator, Alert, Platform, Modal, TextInput, RefreshControl } from 'react-native';
import { useRouter, useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import Constants from 'expo-constants';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';

import { Config } from '../../constants/Config';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import { BannerAd, BannerAdSize, TestIds, useRewardedAd } from 'react-native-google-mobile-ads';
import { Theme, Colors } from '../../constants/Colors';
import { useAuth } from '../../contexts/AuthContext';
import { fetchWithToken } from '../../utils/apiClient';

// Helper to determine backend URL
const getBackendUrl = () => {
    return Config.BACKEND_URL;
};

interface Collection {
    id: number;
    title: string;
    icon: string;
    count: number;
    is_locked: boolean;
}

export default function CollectionsScreen() {
    const router = useRouter();
    const [collections, setCollections] = useState<Collection[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const { isPro } = useRevenueCat();
    const { userId } = useAuth();

    const { isLoaded, isClosed, load, show } = useRewardedAd(Platform.OS === 'ios' ? Config.REWARDED_ID_IOS : Config.REWARDED_ID_ANDROID);
    const [selectedCollection, setSelectedCollection] = useState<Collection | null>(null);

    // Create Collection State
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [newFolderName, setNewFolderName] = useState('');
    const [creating, setCreating] = useState(false);

    useEffect(() => {
        load();
    }, [load]);

    useEffect(() => {
        if (isClosed) {
            if (selectedCollection) {
                handleNavigate(selectedCollection);
                setSelectedCollection(null);
            }
            load();
        }
    }, [isClosed, selectedCollection, load]);

    const handleNavigate = (item: Collection) => {
        router.push({
            pathname: `/collection/[id]`,
            params: { id: item.id, title: item.title }
        });
    };

    useFocusEffect(
        useCallback(() => {
            if (userId) {
                fetchCollections();
            }
        }, [userId])
    );

    // Watch for userId changes (login/logout)
    useEffect(() => {
        if (userId) {
            fetchCollections();
        }
    }, [userId]);

    const fetchCollections = async () => {
        try {
            if (!userId) return;

            const apiUrl = `${getBackendUrl()}/collections`;
            const response = await fetchWithToken(apiUrl);

            if (!response.ok) {
                // Try to parse error
                const text = await response.text();
                console.warn("Fetch collections failed:", response.status, text);
                // Don't throw immediately, maybe return empty?
                // But if status is 500/400, it's an error.
                throw new Error(`Server Error: ${response.status}`);
            }

            const data = await response.json();
            setCollections(data);
        } catch (error) {
            console.error('Fetch collections error:', error);
            // Suppress alert on initial load if it's just a network blip, 
            // but user complained about the error message.
            // We'll show a more friendly message or just retry.
            // Alert.alert('エラー', '保存場所の更新に失敗しました');
        } finally {
            setLoading(false);
        }
    };

    const onRefresh = async () => {
        setRefreshing(true);
        await fetchCollections();
        setRefreshing(false);
    };

    const handleCreateCollection = async () => {
        if (!newFolderName.trim()) {
            Alert.alert('エラー', 'フォルダ名を入力してください');
            return;
        }

        try {
            setCreating(true);
            if (!userId) return;

            const response = await fetchWithToken(`${getBackendUrl()}/collections`, {
                method: 'POST',
                body: JSON.stringify({
                    title: newFolderName,
                    icon: 'folder-outline' // Default icon
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Create failed' }));
                throw new Error(errorData.detail || 'Create failed');
            }

            await fetchCollections(); // Refresh list
            setNewFolderName('');
            setIsModalVisible(false);
        } catch (error: any) {
            Alert.alert('エラー', `フォルダの作成に失敗しました: ${error.message}`);
        } finally {
            setCreating(false);
        }
    };

    const handleDeleteCollection = async (item: Collection) => {
        Alert.alert(
            "フォルダを削除",
            `「${item.title}」を削除しますか？\n中の雑学は保存されなくなります。`,
            [
                { text: "キャンセル", style: "cancel" },
                {
                    text: "削除",
                    style: "destructive",
                    onPress: async () => {
                        try {
                            const response = await fetchWithToken(`${getBackendUrl()}/collections/${item.id}`, {
                                method: 'DELETE',
                            });
                            if (!response.ok) {
                                throw new Error("Delete failed");
                            }
                            await fetchCollections();
                        } catch (e) {
                            Alert.alert("エラー", "削除に失敗しました");
                        }
                    }
                }
            ]
        );
    };

    const renderItem = ({ item }: { item: Collection }) => (
        <Pressable
            style={[styles.folderItem, item.is_locked && styles.folderLocked]}
            onPress={() => {
                // Allow if not locked OR if user is Pro
                // Pro users can access locked folders (favorites)
                const isAccessible = !item.is_locked || isPro;

                if (isAccessible) {
                    setSelectedCollection(item);
                    // Standard navigation logic
                    if (!isPro && isLoaded && item.title !== "過去に見た雑学") {
                        show();
                    } else {
                        handleNavigate(item);
                    }
                } else {
                    Alert.alert('制限', 'このフォルダを利用するにはサブスクリプションが必要です');
                }
            }}
            onLongPress={() => {
                // Allow deletion only for custom folders (not default ones)
                if (item.title !== "過去に見た雑学" && item.title !== "お気に入り") {
                    handleDeleteCollection(item);
                }
            }}
            delayLongPress={500}
        >
            <View style={styles.iconContainer}>
                <Ionicons name={item.icon as any} size={32} color={(item.is_locked && !isPro) ? '#ccc' : Colors.light.primary} />
                {item.is_locked && !isPro && (
                    <View style={styles.lockBadge}>
                        <Ionicons name="lock-closed" size={12} color="white" />
                    </View>
                )}
            </View>
            <Text style={styles.folderTitle} numberOfLines={1}>{item.title}</Text>
            <Text style={styles.folderCount}>{item.count} 項目</Text>
        </Pressable>
    );

    if (loading) {
        return (
            <SafeAreaView style={[styles.container, styles.center]}>
                <ActivityIndicator size="large" color="#007AFF" />
            </SafeAreaView>
        );
    }

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.headerRow}>
                <Text style={styles.headerTitle}>保存場所</Text>
                {isPro && (
                    <Pressable style={styles.addButton} onPress={() => setIsModalVisible(true)}>
                        <Ionicons name="add" size={24} color="white" />
                        <Text style={styles.addButtonText}>フォルダ作成</Text>
                    </Pressable>
                )}
            </View>

            <FlatList
                data={collections}
                renderItem={renderItem}
                keyExtractor={item => item.id.toString()}
                numColumns={3}
                contentContainerStyle={styles.listContent}
                style={{ flex: 1 }} // Ensure list takes available space
                refreshControl={
                    <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
                }
                alwaysBounceVertical={true}
            />

            <View style={{ alignItems: 'center', marginBottom: 90 }}>
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

            {/* Create Folder Modal */}
            <Modal
                transparent={true}
                visible={isModalVisible}
                animationType="fade"
                onRequestClose={() => setIsModalVisible(false)}
            >
                <View style={styles.modalOverlay}>
                    <View style={styles.modalContent}>
                        <Text style={styles.modalTitle}>新しいフォルダ</Text>
                        <TextInput
                            style={styles.input}
                            placeholder="フォルダ名 (例: 動物ネタ)"
                            value={newFolderName}
                            onChangeText={setNewFolderName}
                            autoFocus
                        />
                        <View style={styles.modalButtons}>
                            <Pressable
                                style={[styles.modalButton, styles.cancelButton]}
                                onPress={() => setIsModalVisible(false)}
                            >
                                <Text style={styles.cancelButtonText}>キャンセル</Text>
                            </Pressable>
                            <Pressable
                                style={[styles.modalButton, styles.createButton]}
                                onPress={handleCreateCollection}
                                disabled={creating}
                            >
                                {creating ? (
                                    <ActivityIndicator color="white" size="small" />
                                ) : (
                                    <Text style={styles.createButtonText}>作成</Text>
                                )}
                            </Pressable>
                        </View>
                    </View>
                </View>
            </Modal>
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
    headerRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingHorizontal: 20,
        paddingTop: 20, // Reduced top padding
        paddingBottom: 20,
    },
    headerTitle: {
        fontSize: 32,
        fontWeight: '900',
        color: Colors.light.primary,
        letterSpacing: -0.5,
    },
    addButton: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: Colors.light.accent,
        paddingVertical: 8,
        paddingHorizontal: 16,
        borderRadius: 20,
        ...Theme.shadow.small,
    },
    addButtonText: {
        color: '#8B4500',
        fontWeight: 'bold',
        marginLeft: 4,
        fontSize: 14,
    },
    listContent: {
        padding: 15,
        paddingBottom: 100, // Bottom padding for content
    },
    folderItem: {
        flex: 1,
        backgroundColor: Colors.light.cardBackground,
        margin: 8,
        padding: 16,
        borderRadius: Theme.borderRadius.l,
        alignItems: 'center',
        justifyContent: 'center',
        maxWidth: '31%',
        aspectRatio: 0.85,
        ...Theme.shadow.small,
        borderWidth: 2,
        borderColor: Colors.light.border,
    },
    folderLocked: {
        backgroundColor: '#F5F5F5',
        opacity: 0.7,
        borderWidth: 2,
        borderColor: '#EEE',
    },
    iconContainer: {
        marginBottom: 12,
        position: 'relative',
        width: 56,
        height: 56,
        borderRadius: 28,
        backgroundColor: '#FFF8E1',
        alignItems: 'center',
        justifyContent: 'center',
        borderWidth: 2,
        borderColor: 'white',
        ...Theme.shadow.small,
    },
    folderTitle: {
        fontSize: 14,
        fontWeight: 'bold',
        textAlign: 'center',
        marginBottom: 4,
        color: Colors.light.text,
    },
    folderCount: {
        fontSize: 12,
        color: Colors.light.subtext,
        fontWeight: '600',
    },
    lockBadge: {
        position: 'absolute',
        top: -4,
        right: -4,
        backgroundColor: Colors.light.subtext,
        borderRadius: 12,
        width: 24,
        height: 24,
        justifyContent: 'center',
        alignItems: 'center',
        borderWidth: 2,
        borderColor: 'white',
    },
    // Modal Styles
    modalOverlay: {
        flex: 1,
        backgroundColor: 'rgba(0,0,0,0.5)',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 20,
    },
    modalContent: {
        width: '100%',
        maxWidth: 320,
        backgroundColor: 'white',
        borderRadius: 24,
        padding: 24,
        alignItems: 'center',
        ...Theme.shadow.pop,
    },
    modalTitle: {
        fontSize: 20,
        fontWeight: 'bold',
        marginBottom: 20,
        color: Colors.light.text,
    },
    input: {
        width: '100%',
        backgroundColor: '#F5F5F5',
        padding: 16,
        borderRadius: 12,
        fontSize: 16,
        marginBottom: 24,
        borderWidth: 1,
        borderColor: '#E0E0E0',
    },
    modalButtons: {
        flexDirection: 'row',
        width: '100%',
        gap: 12,
    },
    modalButton: {
        flex: 1,
        paddingVertical: 14,
        borderRadius: 12,
        alignItems: 'center',
        justifyContent: 'center',
    },
    cancelButton: {
        backgroundColor: '#F5F5F5',
    },
    createButton: {
        backgroundColor: Colors.light.primary,
    },
    cancelButtonText: {
        color: '#666',
        fontWeight: 'bold',
        fontSize: 16,
    },
    createButtonText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 16,
    }
});

