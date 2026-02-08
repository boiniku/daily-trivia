import { useState, useCallback } from 'react';
import { View, Text, StyleSheet, Pressable, FlatList, ActivityIndicator, Alert, Platform } from 'react-native';
import { useRouter, useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import Constants from 'expo-constants';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';

import { Config } from '../../constants/Config';

// Helper to determine backend URL (Duplicated code, should be refactored to a util)
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

    useFocusEffect(
        useCallback(() => {
            fetchCollections();
        }, [])
    );

    const fetchCollections = async () => {
        try {
            // Get user ID
            let userId = await AsyncStorage.getItem('user_id');
            if (!userId) {
                // If no user ID here, something is wrong or first time directly here
                userId = Crypto.randomUUID();
                await AsyncStorage.setItem('user_id', userId);
            }

            const apiUrl = `${getBackendUrl()}/collections?user_id=${userId}`;
            const response = await fetch(apiUrl);
            if (!response.ok) throw new Error('Network error');
            const data = await response.json();
            setCollections(data);
        } catch (error) {
            Alert.alert('エラー', '保存場所の取得に失敗しました');
        } finally {
            setLoading(false);
        }
    };

    const renderItem = ({ item }: { item: Collection }) => (
        <Pressable
            style={[styles.folderItem, item.is_locked && styles.folderLocked]}
            onPress={() => {
                if (!item.is_locked) {
                    // Navigate to collection details
                    router.push({
                        pathname: `/collection/[id]`,
                        params: { id: item.id, title: item.title }
                    });
                } else {
                    Alert.alert('制限', 'このフォルダを作成・編集するにはサブスクリプション登録が必要です');
                }
            }}
        >
            <View style={styles.iconContainer}>
                <Ionicons name={item.icon as any} size={32} color={item.is_locked ? '#ccc' : Colors.light.primary} />
                {item.is_locked && (
                    <View style={styles.lockBadge}>
                        <Ionicons name="lock-closed" size={12} color="white" />
                    </View>
                )}
            </View>
            <Text style={styles.folderTitle}>{item.title}</Text>
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
            <Text style={styles.headerTitle}>保存場所</Text>
            <FlatList
                data={collections}
                renderItem={renderItem}
                keyExtractor={item => item.id.toString()}
                numColumns={3}
                contentContainerStyle={styles.listContent}
            />
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
    headerTitle: {
        fontSize: 32,
        fontWeight: '900', // Playful bold
        paddingHorizontal: 20,
        paddingTop: 40,
        paddingBottom: 20,
        color: Colors.light.primary, // Red
        letterSpacing: -0.5,
    },
    listContent: {
        padding: 15,
        paddingBottom: 100,
    },
    folderItem: {
        flex: 1,
        backgroundColor: Colors.light.cardBackground,
        margin: 8,
        padding: 16,
        borderRadius: Theme.borderRadius.l, // 24 or 36
        alignItems: 'center',
        justifyContent: 'center',
        maxWidth: '31%',
        aspectRatio: 0.85,
        ...Theme.shadow.small,
        borderWidth: 2, // Thicker border
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
        width: 56, // Larger icon area
        height: 56,
        borderRadius: 28,
        backgroundColor: '#FFF8E1', // Pale yellow accent
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
    }
});
