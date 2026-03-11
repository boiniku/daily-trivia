import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable, ScrollView, Platform, Image, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Theme, Colors } from '../constants/Colors';
import { getWidgetImageBase64 } from '../modules/widget-control';

const THEMES = [
    { displayTheme: 'standard', timeTheme: 'morning', label: 'Standard Morning' },
    { displayTheme: 'standard', timeTheme: 'noon', label: 'Standard Noon' },
    { displayTheme: 'standard', timeTheme: 'night', label: 'Standard Night' },
    { displayTheme: 'light', timeTheme: 'noon', label: 'Light' },
    { displayTheme: 'dark', timeTheme: 'noon', label: 'Dark' },
    { displayTheme: 'gameboy', timeTheme: 'noon', label: 'Gameboy' },
    { displayTheme: 'rpg', timeTheme: 'noon', label: 'RPG' },
];

export default function WidgetScreenshotScreen() {
    const router = useRouter();
    const [images, setImages] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        loadImages();
    }, []);

    const loadImages = async () => {
        if (Platform.OS !== 'ios') {
            setError('この機能はiOS（実機またはシミュレーター）でのみ利用可能です。');
            setLoading(false);
            return;
        }

        let loadedImages: Record<string, string> = {};
        let hasError = false;

        for (const t of THEMES) {
            try {
                const base64 = await getWidgetImageBase64(t.displayTheme, t.timeTheme);
                if (base64 && base64.length > 0) {
                    loadedImages[`${t.displayTheme}_${t.timeTheme}`] = `data:image/png;base64,${base64}`;
                } else {
                    console.warn(`Empty base64 for ${t.displayTheme} ${t.timeTheme}`);
                }
            } catch (err: any) {
                console.error('Failed to snapshot', t.label, err);
                hasError = true;
                setError(err.message || 'Error generating images (requires iOS 16+)');
                break;
            }
        }

        if (!hasError) {
            setImages(loadedImages);
        }
        setLoading(false);
    };

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Pressable onPress={() => router.back()} style={styles.backButton}>
                    <Ionicons name="arrow-back" size={24} color={Colors.light.primary} />
                </Pressable>
                <Text style={styles.headerTitle}>Widget Screenshots</Text>
                <View style={{ width: 40 }} />
            </View>

            <ScrollView contentContainerStyle={styles.scrollContent}>
                <Text style={styles.description}>
                    TestFlight等でこの画面を開き、ここで表示された全てのウィジェット一覧をスクショしてください。（iOS16以上必須）
                </Text>

                {loading && (
                    <View style={styles.loadingContainer}>
                        <ActivityIndicator size="large" color={Colors.light.primary} />
                        <Text style={{ marginTop: 12 }}>Generating Native SwiftUI Snapshots...</Text>
                    </View>
                )}

                {error && (
                    <View style={styles.errorContainer}>
                        <Text style={styles.errorText}>{error}</Text>
                    </View>
                )}

                {!loading && !error && Object.keys(images).length === 0 && (
                    <Text style={{ textAlign: 'center', marginTop: 20 }}>No images generated.</Text>
                )}

                {!loading && THEMES.map((t) => {
                    const key = `${t.displayTheme}_${t.timeTheme}`;
                    const sourceUrl = images[key];

                    if (!sourceUrl) return null;

                    return (
                        <View key={key} style={styles.imageBlock}>
                            <Text style={styles.imageLabel}>{t.label}</Text>
                            <View style={styles.imageWrapper}>
                                <Image 
                                    source={{ uri: sourceUrl }} 
                                    style={styles.widgetImage} 
                                    resizeMode="contain" 
                                />
                            </View>
                        </View>
                    );
                })}
                <View style={{ height: 40 }} />
            </ScrollView>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: { flex: 1, backgroundColor: '#FFFFFF' },
    header: { flexDirection: 'row', alignItems: 'center', padding: 20 },
    backButton: { padding: 8, borderRadius: 20, backgroundColor: '#F5F5F5' },
    headerTitle: { fontSize: 18, fontWeight: 'bold', color: Colors.light.text, flex: 1, textAlign: 'center' },
    scrollContent: { padding: 20, alignItems: 'center' },
    description: { fontSize: 14, color: '#666', marginBottom: 20, textAlign: 'center', lineHeight: 22 },
    loadingContainer: { alignItems: 'center', marginTop: 40 },
    errorContainer: { padding: 16, backgroundColor: '#FFEBEB', borderRadius: 8, marginTop: 20 },
    errorText: { color: '#D32F2F', fontSize: 14, textAlign: 'center' },
    imageBlock: { marginBottom: 30, alignItems: 'center' },
    imageLabel: { fontSize: 16, fontWeight: 'bold', marginBottom: 8, color: '#333' },
    imageWrapper: {
        width: 320,
        height: 150,
        borderRadius: 22,
        overflow: 'hidden',
        backgroundColor: '#F0F0F0',
        elevation: 5,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.1,
        shadowRadius: 10,
    },
    widgetImage: { width: '100%', height: '100%' }
});
