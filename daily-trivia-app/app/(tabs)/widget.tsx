import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable, ScrollView, Platform, Dimensions, Image, Alert, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Theme, Colors } from '../../constants/Colors';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import DefaultPreference from 'react-native-default-preference';
import { reloadAllTimelines, saveWidgetThemeImage } from '../../modules/widget-control';
import { ensureThemeImage, getThemeImageUrl } from '../../utils/widgetThemeImages';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as ImagePicker from 'expo-image-picker';


type ThemeType = 'standard' | 'light' | 'dark' | 'rpg' | 'cat' | 'custom';

const THEMES: { id: ThemeType; label: string; isPremium: boolean }[] = [
    { id: 'standard', label: 'スタンダード（時間で変化）', isPremium: false },
    { id: 'light', label: 'ホワイト（白ベース）', isPremium: true },
    { id: 'dark', label: 'ダーク（黒ベース）', isPremium: true },
    { id: 'rpg', label: 'ドラクエ風（RPG）', isPremium: true },
    { id: 'cat', label: '猫柄（時間で変化）', isPremium: true },
    { id: 'custom', label: 'カスタム画像', isPremium: true },
];

const WIDGET_WIDTH = 260;
const WIDGET_HEIGHT = 120;

const CUSTOM_IMAGE_STORAGE_KEY = 'custom_widget_image_uri';

const WidgetPreview = ({ theme, previewTime, customImageUri }: { theme: ThemeType, previewTime: string, customImageUri: string | null }) => {
    const [cloudImageUrl, setCloudImageUrl] = useState<string | null>(null);

    useEffect(() => {
        let isMounted = true;
        const fetchUrl = async () => {
            if (theme === 'custom' || theme === 'standard') return;
            
            let themeName: string = theme;
            if (theme === 'rpg' || theme === 'cat') {
                themeName = `${theme}_${previewTime}`;
            }
            const url = await getThemeImageUrl(themeName);
            if (isMounted) setCloudImageUrl(url);
        };
        fetchUrl();
        return () => { isMounted = false; };
    }, [theme, previewTime]);

    if (theme === 'custom') {
        if (customImageUri) {
            return (
                <View style={styles.widgetContainer}>
                    <Image
                        source={{ uri: customImageUri }}
                        style={styles.widgetImage}
                        resizeMode="cover"
                    />
                </View>
            );
        }
        // カスタム画像未設定
        return (
            <View style={[styles.widgetContainer, styles.customPlaceholder]}>
                <Ionicons name="image-outline" size={36} color={Colors.light.subtext} />
                <Text style={styles.customPlaceholderText}>画像を選択してください</Text>
            </View>
        );
    }

    if (theme === 'standard') {
        return (
            <View style={[styles.widgetContainer, styles.customPlaceholder]}>
                <Ionicons name="time-outline" size={36} color={Colors.light.subtext} />
                <Text style={styles.customPlaceholderText}>時間で自動変化します</Text>
            </View>
        );
    }

    // Cloud themes (light, dark, rpg, cat)
    return (
        <View style={styles.widgetContainer}>
            {cloudImageUrl ? (
                <Image 
                    source={{ uri: cloudImageUrl }} 
                    style={styles.widgetImage} 
                    resizeMode="cover" 
                />
            ) : (
                <ActivityIndicator size="small" color={Colors.light.primary} />
            )}
        </View>
    );
};

export default function WidgetThemeScreen() {
    const router = useRouter();
    const { isPro } = useRevenueCat();
    const [selectedTheme, setSelectedTheme] = useState<ThemeType>('standard');
    const [standardPreviewTime, setStandardPreviewTime] = useState<'morning' | 'noon' | 'night'>('noon');
    const [loading, setLoading] = useState(true);
    const [customImageUri, setCustomImageUri] = useState<string | null>(null);
    const [savingCustomImage, setSavingCustomImage] = useState(false);

    useEffect(() => {
        loadCurrentTheme();
        loadCustomImage();
    }, []);

    const loadCurrentTheme = async () => {
        try {
            if (Platform.OS === 'ios') {
                await DefaultPreference.setName('group.com.dailytrivia.app');
                const theme = await DefaultPreference.get('widget_theme');
                if (theme === 'light' || theme === 'dark' || theme === 'standard' || theme === 'rpg' || theme === 'cat' || theme === 'custom') {
                    setSelectedTheme(theme as ThemeType);
                }
            }
        } catch (e) {
            console.error('Failed to load widget theme', e);
        } finally {
            setLoading(false);
        }
    };

    const loadCustomImage = async () => {
        try {
            const uri = await AsyncStorage.getItem(CUSTOM_IMAGE_STORAGE_KEY);
            if (uri) {
                setCustomImageUri(uri);
            }
        } catch (e) {
            console.error('Failed to load custom image', e);
        }
    };

    const handleThemeSelect = async (themeId: ThemeType, isPremium: boolean) => {
        if (isPremium && !isPro) {
            Alert.alert('このデザインは使用できません', 'このウィジェットデザインはプレミアムプラン専用です。タップで確認することはできますが、実際に適用するにはプランの登録が必要です。');
            return;
        }

        // カスタムテーマで画像未設定の場合
        if (themeId === 'custom' && !customImageUri) {
            Alert.alert('画像を選択してください', 'カスタムデザインを使うには、まず画像を登録してください。');
            return;
        }

        setSelectedTheme(themeId);

        try {
            if (Platform.OS === 'ios') {
                // クラウドテーマの画像をDL（キャッシュ済みならスキップ）
                await ensureThemeImage(themeId);
                
                await DefaultPreference.setName('group.com.dailytrivia.app');
                await DefaultPreference.set('widget_theme', themeId);
                reloadAllTimelines();
            }
        } catch (e) {
            console.error('Failed to save widget theme', e);
        }
    };

    const handlePickCustomImage = async () => {
        try {
            // 権限確認
            const permResult = await ImagePicker.requestMediaLibraryPermissionsAsync();
            if (!permResult.granted) {
                Alert.alert('権限が必要です', '画像ライブラリへのアクセスを許可してください。');
                return;
            }

            const result = await ImagePicker.launchImageLibraryAsync({
                mediaTypes: ['images'],
                allowsEditing: true,
                aspect: [13, 6], // ウィジェットの縦横比に近い
                quality: 0.9,
                base64: true,
            });

            if (!result.canceled && result.assets[0]) {
                const asset = result.assets[0];
                setSavingCustomImage(true);

                // プレビュー用にURIを保存
                setCustomImageUri(asset.uri);
                await AsyncStorage.setItem(CUSTOM_IMAGE_STORAGE_KEY, asset.uri);

                // App Group経由でウィジェットに画像を渡す
                if (Platform.OS === 'ios' && asset.base64) {
                    try {
                        await saveWidgetThemeImage('custom', asset.base64);
                    } catch (err) {
                        console.error('Failed to save custom image to widget:', err);
                    }
                }

                setSavingCustomImage(false);

                // カスタムが選択中なら即座にウィジェットリロード
                if (selectedTheme === 'custom') {
                    reloadAllTimelines();
                    setTimeout(() => reloadAllTimelines(), 500);
                }
            }
        } catch (e) {
            console.error('Image picker error:', e);
            setSavingCustomImage(false);
            Alert.alert('エラー', '画像の選択に失敗しました。');
        }
    };

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Text style={styles.headerTitle}>ウィジェットのデザイン</Text>
            </View>

            <ScrollView contentContainerStyle={styles.scrollContent}>
                <Text style={styles.hintText}>
                    ※ デザインの変更はシステムによって反映タイミングが異なります。万が一ウィジェットが切り替わらない場合は、スマホの再起動か配置し直しを行なってください。
                </Text>

                <Text style={[styles.previewHint, { marginTop: 16 }]}>
                    「スタンダード」はタップで時間帯プレビューを切り替えられます。
                </Text>

                <View style={styles.themeGrid}>
                    {THEMES.map((theme) => {
                        const isSelected = selectedTheme === theme.id;
                        const isCustom = theme.id === 'custom';
                        return (
                            <View
                                key={theme.id}
                                style={[
                                    styles.themeCard,
                                    isSelected && styles.themeCardSelected
                                ]}
                            >
                                <Pressable
                                    onPress={() => handleThemeSelect(theme.id, theme.isPremium)}
                                >
                                    <View style={styles.themeHeader}>
                                        <View style={[styles.radioButton, isSelected && styles.radioButtonSelected]}>
                                            {isSelected && <View style={styles.radioButtonInner} />}
                                        </View>
                                        <View style={styles.themeLabelContainer}>
                                            <Text style={[styles.themeLabel, isSelected && styles.themeLabelSelected]} numberOfLines={1}>
                                                {theme.label}
                                            </Text>
                                        </View>
                                        {theme.isPremium && (
                                            <View style={styles.proBadge}>
                                                <Text style={styles.proBadgeText}>PRO</Text>
                                            </View>
                                        )}
                                    </View>
                                </Pressable>
                                
                                <View style={[styles.previewContainer, theme.isPremium && !isPro && styles.previewLocked]}>
                                    <Pressable 
                                        onPress={() => {
                                            if (isCustom) {
                                                // カスタムの場合は画像選択
                                                if (!theme.isPremium || isPro) {
                                                    handlePickCustomImage();
                                                } else {
                                                    handleThemeSelect(theme.id, theme.isPremium);
                                                }
                                            } else if (theme.id === 'standard') {
                                                setStandardPreviewTime(prev => 
                                                    prev === 'morning' ? 'noon' : 
                                                    prev === 'noon' ? 'night' : 'morning'
                                                );
                                            } else {
                                                handleThemeSelect(theme.id, theme.isPremium);
                                            }
                                        }}
                                        disabled={theme.isPremium && !isPro} 
                                    >
                                        <WidgetPreview 
                                            theme={theme.id} 
                                            previewTime={theme.id === 'standard' ? standardPreviewTime : 'noon'} 
                                            customImageUri={customImageUri}
                                        />
                                    </Pressable>

                                    {/* カスタムテーマの画像変更ボタン */}
                                    {isCustom && customImageUri && (!theme.isPremium || isPro) && (
                                        <Pressable 
                                            style={styles.changeImageButton}
                                            onPress={handlePickCustomImage}
                                        >
                                            <Ionicons name="camera" size={16} color="#fff" />
                                            <Text style={styles.changeImageButtonText}>画像を変更</Text>
                                        </Pressable>
                                    )}

                                    {savingCustomImage && isCustom && (
                                        <View style={styles.lockOverlay}>
                                            <ActivityIndicator size="small" color="#fff" />
                                            <Text style={{ color: '#fff', marginTop: 4, fontSize: 12 }}>保存中...</Text>
                                        </View>
                                    )}

                                    {theme.isPremium && !isPro && (
                                        <Pressable 
                                            style={styles.lockOverlay} 
                                            onPress={() => handleThemeSelect(theme.id, theme.isPremium)}
                                        >
                                            <Ionicons name="lock-closed" size={32} color="#ffffff" />
                                        </Pressable>
                                    )}
                                </View>
                            </View>
                        );
                    })}
                </View>
            </ScrollView>
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
    },
    screenshotButton: {
        position: 'absolute',
        right: 20,
        padding: 8,
        borderRadius: 20,
        backgroundColor: '#F5F5F5',
    },
    backButton: {
        padding: 8,
        borderRadius: 20,
        backgroundColor: '#F5F5F5',
    },
    headerTitle: {
        fontSize: 18,
        fontWeight: 'bold',
        color: Colors.light.text,
        flex: 1,
        textAlign: 'center',
    },
    scrollContent: {
        padding: 20,
        paddingBottom: 120,
    },
    previewHint: {
        fontSize: 12,
        color: Colors.light.primary,
        marginBottom: 16,
        marginLeft: 4,
        fontWeight: 'bold',
    },
    themeGrid: {
        flexDirection: 'column',
        gap: 20,
    },
    themeCard: {
        backgroundColor: Colors.light.cardBackground,
        borderRadius: Theme.borderRadius.m,
        overflow: 'hidden',
        borderWidth: 1,
        borderColor: Colors.light.border,
        padding: 16,
    },
    themeCardSelected: {
        backgroundColor: 'rgba(255, 152, 0, 0.05)',
        borderColor: Colors.light.primary,
        borderWidth: 2,
    },
    themeHeader: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: 12,
    },
    themeLabelContainer: {
        flex: 1,
    },
    radioButton: {
        width: 20,
        height: 20,
        borderRadius: 10,
        borderWidth: 2,
        borderColor: Colors.light.subtext,
        marginRight: 12,
        justifyContent: 'center',
        alignItems: 'center',
    },
    radioButtonSelected: {
        borderColor: Colors.light.primary,
    },
    radioButtonInner: {
        width: 10,
        height: 10,
        borderRadius: 5,
        backgroundColor: Colors.light.primary,
    },
    themeLabel: {
        fontSize: 16,
        color: Colors.light.text,
    },
    themeLabelSelected: {
        fontWeight: 'bold',
        color: Colors.light.primary,
    },
    proBadge: {
        backgroundColor: Colors.light.accent,
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 10,
        marginLeft: 8,
    },
    proBadgeText: {
        color: '#FFFFFF',
        fontSize: 10,
        fontWeight: 'bold',
    },
    previewContainer: {
        alignItems: 'center',
        position: 'relative',
        borderRadius: 18,
        overflow: 'hidden',
    },
    previewLocked: {
        opacity: 0.8,
    },
    lockOverlay: {
        ...StyleSheet.absoluteFillObject,
        backgroundColor: 'rgba(0,0,0,0.4)',
        alignItems: 'center',
        justifyContent: 'center',
    },
    widgetContainer: {
        width: WIDGET_WIDTH,
        height: WIDGET_HEIGHT,
        alignItems: 'center',
        justifyContent: 'center',
    },
    widgetImage: {
        width: '100%',
        height: '100%',
    },
    hintText: {
        fontSize: 12,
        color: Colors.light.subtext,
        lineHeight: 18,
        paddingHorizontal: 4,
    },
    customPlaceholder: {
        backgroundColor: '#F0F0F0',
        borderRadius: 18,
        borderWidth: 2,
        borderColor: '#E0E0E0',
        borderStyle: 'dashed',
    },
    customPlaceholderText: {
        fontSize: 12,
        color: Colors.light.subtext,
        marginTop: 6,
    },
    changeImageButton: {
        position: 'absolute',
        bottom: 8,
        right: 8,
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: 'rgba(0,0,0,0.6)',
        paddingHorizontal: 10,
        paddingVertical: 5,
        borderRadius: 12,
        gap: 4,
    },
    changeImageButtonText: {
        color: '#fff',
        fontSize: 11,
        fontWeight: 'bold',
    },
});
