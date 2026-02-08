import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator, Alert, Platform } from 'react-native';
import { useState, useEffect } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import { Config } from '../../constants/Config';

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

export default function CollectionDetailsScreen() {
    const { id, title } = useLocalSearchParams();
    const router = useRouter();
    const [items, setItems] = useState<TriviaItem[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (id) {
            fetchCollectionItems();
        }
    }, [id]);

    const fetchCollectionItems = async () => {
        try {
            const apiUrl = `${getBackendUrl()}/collections/${id}/items`;
            const response = await fetch(apiUrl);
            if (!response.ok) throw new Error('Network error');
            const data = await response.json();
            setItems(data);
        } catch (error) {
            Alert.alert('エラー', 'データの取得に失敗しました');
        } finally {
            setLoading(false);
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
                <Text style={styles.headerTitle}>{title || 'フォルダの中身'}</Text>
                <View style={{ width: 24 }} />
            </View>

            {loading ? (
                <View style={styles.center}>
                    <ActivityIndicator size="large" color="#007AFF" />
                </View>
            ) : (
                <FlatList
                    data={items}
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

import { Theme, Colors } from '../../constants/Colors'; // Import Colors

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
    },
    headerTitle: {
        fontSize: 24,
        fontWeight: '900',
        color: Colors.light.primary,
        flex: 1,
        textAlign: 'center',
        marginRight: 40, // Balance back button
    },
    center: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
    },
    listContent: {
        padding: 20,
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
    },
    emptyContainer: {
        padding: 40,
        alignItems: 'center',
    },
    emptyText: {
        color: Colors.light.subtext,
        fontSize: 16,
        fontWeight: 'bold',
    }
});
