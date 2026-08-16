import { View, Text, StyleSheet, Pressable, Alert, AppState, ScrollView, ActivityIndicator, Linking, Platform, Switch } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useEffect, useState } from 'react';
import { useRouter } from 'expo-router';
import { Colors, Theme } from '../../constants/Colors';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import { useAuth } from '../../contexts/AuthContext';
import LoginModal from '../../components/LoginModal';
import { TriviaGeofenceManager, TriviaGeofenceStatus } from '../../managers/TriviaGeofenceManager';

export default function SettingsScreen() {
    const router = useRouter();
    const { isPro, currentOffering, purchasePackage, restorePurchases, retryLoadOfferings, loading } = useRevenueCat();
    const { userId, isGuest, signOut, deleteAccount } = useAuth();
    const [loginVisible, setLoginVisible] = useState(false);
    const [notificationStatus, setNotificationStatus] = useState<TriviaGeofenceStatus>('off');
    const [isUpdatingNotifications, setIsUpdatingNotifications] = useState(false);

    const refreshNotificationStatus = async () => {
        setNotificationStatus(await TriviaGeofenceManager.getStatus());
    };

    useEffect(() => {
        refreshNotificationStatus().catch(error => console.error('Notification status error:', error));
        const subscription = AppState.addEventListener('change', (state) => {
            if (state === 'active') {
                refreshNotificationStatus().catch(error => console.error('Notification status error:', error));
            }
        });
        return () => subscription.remove();
    }, []);

    const handleNotificationToggle = async (enabled: boolean) => {
        setIsUpdatingNotifications(true);
        try {
            if (!enabled) {
                await TriviaGeofenceManager.disable();
            } else {
                const result = await TriviaGeofenceManager.enable();
                if (result !== 'enabled') {
                    Alert.alert(
                        '許可が必要です',
                        result === 'notification-denied'
                            ? 'iPhoneの設定で通知を許可してください。'
                            : 'バックグラウンドで雑学を見つけるには、位置情報を「常に」に設定してください。',
                        [
                            { text: 'キャンセル', style: 'cancel' },
                            { text: 'iPhoneの設定を開く', onPress: () => Linking.openSettings() },
                        ]
                    );
                }
            }
            await refreshNotificationStatus();
        } catch (error) {
            console.error('Notification setting update failed:', error);
            Alert.alert('設定できませんでした', '時間をおいて、もう一度お試しください。');
        } finally {
            setIsUpdatingNotifications(false);
        }
    };

    const notificationStatusText = notificationStatus === 'active'
        ? 'アプリを開いていないときも通知します'
        : notificationStatus === 'notification-denied'
            ? 'iPhoneの通知設定がOFFです'
            : notificationStatus === 'location-denied'
                ? '位置情報を「常に」に設定してください'
                : '近くの雑学の通知はOFFです';


    const handlePurchase = async (pack: any) => {
        if (isPro) {
            Alert.alert('確認', 'すでにサブスクリプションに登録済みです。');
            return;
        }
        try {
            await purchasePackage(pack);
        } catch (e) {
            // Error managed in context
        }
    };

    const handleSignOut = async () => {
        Alert.alert(
            "ログアウト",
            "ログアウトしてもよろしいですか？",
            [
                { text: "キャンセル", style: "cancel" },
                {
                    text: "ログアウト",
                    style: "destructive",
                    onPress: async () => {
                        await signOut();
                    }
                }
            ]
        );
    };

    const handleDeleteAccount = async () => {
        Alert.alert(
            "アカウント削除",
            "本当にアカウントを削除しますか？\nこの操作は取り消せません。\n\n・お気に入り、閲覧履歴はすべて削除されます\n・サブスクリプションは別途解約が必要です",
            [
                { text: "キャンセル", style: "cancel" },
                {
                    text: "削除する",
                    style: "destructive", // Red button
                    onPress: async () => {
                        console.log("Delete confirmed by user in UI");
                        try {
                            await deleteAccount();
                            // Force navigation exactly to the tutorial
                            router.replace('/tutorial');
                        } catch (e) {
                            console.error("Delete account error in component:", e);
                        }
                    }
                }
            ]
        );
    };

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Text style={styles.title}>設定</Text>
            </View>

            <ScrollView contentContainerStyle={styles.content}>

                {/* Account Section */}
                <View style={styles.section}>
                    <Text style={styles.sectionHeader}>アカウント</Text>
                    <View style={styles.infoRow}>
                        <Text style={styles.infoLabel}>現在のステータス</Text>
                        <Text style={styles.infoValue}>{isGuest ? "ゲスト" : "ログイン済み"}</Text>
                    </View>


                    {isGuest ? (
                        <Pressable style={styles.loginButton} onPress={() => setLoginVisible(true)}>
                            <Ionicons name="logo-apple" size={20} color="white" style={{ marginRight: 8 }} />
                            <Text style={styles.loginButtonText}>ログイン / 新規登録</Text>
                        </Pressable>
                    ) : (
                        <Pressable style={styles.logoutButton} onPress={handleSignOut}>
                            <Text style={styles.logoutButtonText}>ログアウト</Text>
                        </Pressable>
                    )}
                </View>

                <View style={styles.section}>
                    <Text style={styles.sectionHeader}>サブスクリプション</Text>
                    {isPro ? (
                        <View style={styles.proBadge}>
                            <Text style={styles.proText}>プレミアムプラン登録済み</Text>
                        </View>
                    ) : (
                        <View>
                            {loading ? (
                                <View style={{ alignItems: 'center', padding: 20 }}>
                                    <ActivityIndicator size="small" color={Colors.light.primary} />
                                    <Text style={styles.loadingText}>プランを読み込み中...</Text>
                                </View>
                            ) : currentOffering?.current?.availablePackages?.length ? (
                                currentOffering.current.availablePackages.map((pack) => {
                                    let priceDisplay = pack.product.priceString;
                                    let suffix = '';

                                    // Custom pricing display
                                    const isMonthly = (pack.packageType as any) === 'MONTHLY' || pack.product.identifier.toLowerCase().includes('month');
                                    const isAnnual = (pack.packageType as any) === 'ANNUAL' || pack.product.identifier.toLowerCase().includes('year') || pack.product.identifier.toLowerCase().includes('annual');
                                    const isLifetime = (pack.packageType as any) === 'LIFETIME' || pack.product.identifier.toLowerCase().includes('lifetime');

                                    if (isMonthly) {
                                        suffix = " / 月";
                                    } else if (isAnnual) {
                                        suffix = " / 年";
                                    } else if (isLifetime) {
                                        suffix = " (買い切り)";
                                    } else {
                                        suffix = ''; // Default or unknown
                                    }

                                    return (
                                        <Pressable
                                            key={pack.identifier}
                                            style={styles.premiumButton}
                                            onPress={() => handlePurchase(pack)}
                                        >
                                            <View>
                                                <Text style={styles.premiumButtonText}>
                                                    {pack.product.title}
                                                </Text>
                                                <Text style={styles.premiumPrice}>
                                                    {priceDisplay}{suffix}
                                                </Text>
                                            </View>
                                            <Text style={styles.premiumDesc}>
                                                {isAnnual ? "12ヶ月分お得に！広告なし、閲覧数無制限" : "広告なし、閲覧数無制限"}
                                            </Text>
                                        </Pressable>
                                    );
                                })
                            ) : (
                                <View style={{ alignItems: 'center', padding: 20 }}>
                                    <Text style={styles.loadingText}>プランを取得できませんでした。</Text>
                                    <Text style={{ fontSize: 12, color: Colors.light.subtext, marginBottom: 10, textAlign: 'center' }}>
                                        ネットワーク接続を確認するか、設定をご確認ください。
                                    </Text>
                                    <Pressable onPress={() => retryLoadOfferings()} style={{ marginTop: 10, padding: 10 }}>
                                        <Text style={{ color: Colors.light.primary, fontWeight: 'bold' }}>再試行</Text>
                                    </Pressable>
                                </View>
                            )}
                        </View>
                    )}

                    {/* Feature List */}
                    {!isPro && (
                        <View style={styles.featuresContainer}>
                            <View style={styles.featureItem}>
                                <Ionicons name="infinite" size={24} color={Colors.light.primary} style={styles.featureIcon} />
                                <View style={styles.featureTextContainer}>
                                    <Text style={styles.featureTitle}>無制限に読み放題</Text>
                                    <Text style={styles.featureSub}>1日3つの制限なく、過去の雑学も全て見放題。</Text>
                                </View>
                            </View>
                            <View style={styles.featureItem}>
                                <Ionicons name="ban" size={24} color={Colors.light.primary} style={styles.featureIcon} />
                                <View style={styles.featureTextContainer}>
                                    <Text style={styles.featureTitle}>広告非表示</Text>
                                    <Text style={styles.featureSub}>バナーや動画広告がなくなり、快適に楽しめます。</Text>
                                </View>
                            </View>
                            <View style={styles.featureItem}>
                                <Ionicons name="folder-open" size={24} color={Colors.light.primary} style={styles.featureIcon} />
                                <View style={styles.featureTextContainer}>
                                    <Text style={styles.featureTitle}>保存機能の拡張</Text>
                                    <Text style={styles.featureSub}>カスタムフォルダを作成して雑学を整理できます。</Text>
                                </View>
                            </View>
                        </View>
                    )}

                    <Pressable style={styles.restoreButton} onPress={restorePurchases}>
                        <Text style={styles.restoreText}>購入を復元する</Text>
                    </Pressable>
                </View>

                <View style={styles.section}>
                    <Text style={styles.sectionHeader}>通知</Text>
                    <View style={styles.notificationRow}>
                        <View style={styles.notificationTextContainer}>
                            <Text style={styles.infoLabel}>近くの雑学</Text>
                            <Text style={styles.notificationDescription}>{notificationStatusText}</Text>
                        </View>
                        {isUpdatingNotifications ? (
                            <ActivityIndicator color={Colors.light.primary} />
                        ) : (
                            <Switch
                                value={notificationStatus !== 'off'}
                                onValueChange={handleNotificationToggle}
                                disabled={Platform.OS !== 'ios'}
                                trackColor={{ false: '#D8D8D8', true: Colors.light.accent }}
                                thumbColor={notificationStatus !== 'off' ? Colors.light.primary : '#F4F4F4'}
                            />
                        )}
                    </View>
                    <Text style={styles.notificationPrivacy}>
                        位置情報は端末内で雑学の開放を判定するために使い、移動履歴は保存しません。
                    </Text>
                </View>

                <View style={styles.section}>
                    <Text style={styles.sectionHeader}>アプリについて</Text>
                    <View style={styles.infoRow}>
                        <Text style={styles.infoLabel}>バージョン</Text>
                        <Text style={styles.infoValue}>1.0.5</Text>
                    </View>
                    <Pressable style={styles.infoRow} onPress={() => Linking.openURL('https://docs.google.com/document/d/1_K7priRhIk6OSG3c_YQBngnW4uVpTcCOdIEHVN7jFnw/edit?usp=sharing')}>
                        <Text style={styles.infoLabel}>利用規約</Text>
                        <Ionicons name="chevron-forward" size={20} color={Colors.light.subtext} />
                    </Pressable>
                    <Pressable style={styles.infoRow} onPress={() => Linking.openURL('https://docs.google.com/document/d/1lCV52E8lkax9EUt8jD1wsvE2wajtwL1XjTclhOqxz3A/edit?usp=sharing')}>
                        <Text style={styles.infoLabel}>プライバシーポリシー</Text>
                        <Ionicons name="chevron-forward" size={20} color={Colors.light.subtext} />
                    </Pressable>
                </View>

                {/* Danger Zone */}
                <View style={[styles.section, { borderColor: '#FFEBEE', backgroundColor: '#FFEBEE' }]}>
                    <Text style={[styles.sectionHeader, { color: '#D32F2F' }]}>危険な操作</Text>
                    <Pressable style={styles.deleteButton} onPress={handleDeleteAccount}>
                        <Text style={styles.deleteButtonText}>アカウントを削除する</Text>
                    </Pressable>
                    <Text style={styles.deleteNote}>
                        ※ 退会するとこれまでのデータはすべて消去されます。復元はできません。
                    </Text>
                </View>
            </ScrollView >

            <LoginModal visible={loginVisible} onClose={() => setLoginVisible(false)} />
        </SafeAreaView >
    );
}


const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: Colors.light.background,
    },
    header: {
        paddingHorizontal: 20,
        paddingTop: 20,
        paddingBottom: 10,
    },
    content: {
        padding: 20,
        paddingBottom: 120,
    },
    title: {
        fontSize: 32,
        fontWeight: '900',
        color: Colors.light.primary,
        marginBottom: 10,
    },
    featureItem: {
        flexDirection: 'row',
        alignItems: 'center',
        marginTop: 16,
        paddingHorizontal: 8,
    },
    featureIcon: {
        marginRight: 16,
        width: 30, // Fixed width for alignment
        textAlign: 'center',
    },
    featureTextContainer: {
        flex: 1,
    },
    featureTitle: {
        fontSize: 16,
        fontWeight: 'bold',
        color: Colors.light.text,
    },
    featureSub: {
        fontSize: 12,
        color: Colors.light.subtext,
        marginTop: 2,
    },
    featuresContainer: {
        marginTop: 8,
        paddingTop: 8,
        borderTopWidth: 1,
        borderTopColor: '#EEE',
    },
    section: {
        marginBottom: 24,
        backgroundColor: Colors.light.cardBackground,
        padding: 20,
        borderRadius: Theme.borderRadius.l,
        ...Theme.shadow.small,
        borderWidth: 2,
        borderColor: Colors.light.border,
    },
    sectionHeader: {
        fontSize: 18,
        fontWeight: 'bold',
        marginBottom: 16,
        color: Colors.light.text,
    },
    premiumButton: {
        backgroundColor: Colors.light.accent,
        padding: 20,
        borderRadius: Theme.borderRadius.m,
        alignItems: 'center',
        ...Theme.shadow.small,
        borderWidth: 2,
        borderColor: 'white',
        marginBottom: 12, // Spacing between buttons
    },
    premiumButtonText: {
        color: '#8B4500',
        fontWeight: 'bold',
        fontSize: 18,
        marginBottom: 2,
        textAlign: 'center',
    },
    premiumPrice: {
        color: '#8B4500',
        fontWeight: '900',
        fontSize: 20,
        marginBottom: 4,
        textAlign: 'center',
    },
    premiumDesc: {
        color: '#8B4500',
        fontSize: 12,
        opacity: 0.8,
        textAlign: 'center',
    },
    loadingText: {
        textAlign: 'center',
        padding: 20,
        color: Colors.light.subtext,
    },
    infoRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingVertical: 8,
    },
    infoLabel: {
        fontSize: 16,
        color: Colors.light.text,
        fontWeight: '500',
    },
    infoValue: {
        fontSize: 16,
        color: Colors.light.subtext,
        fontWeight: 'bold',
    },
    notificationRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
    },
    notificationTextContainer: {
        flex: 1,
    },
    notificationDescription: {
        color: Colors.light.subtext,
        fontSize: 12,
        marginTop: 4,
        lineHeight: 18,
    },
    notificationPrivacy: {
        color: Colors.light.subtext,
        fontSize: 12,
        lineHeight: 18,
        marginTop: 14,
    },
    proBadge: {
        backgroundColor: '#E8F5E9',
        padding: 16,
        borderRadius: Theme.borderRadius.m,
        alignItems: 'center',
        borderWidth: 2,
        borderColor: '#C8E6C9',
    },
    proText: {
        color: '#2E7D32',
        fontWeight: 'bold',
        fontSize: 16,
    },
    restoreButton: {
        marginTop: 12,
        padding: 12,
        alignItems: 'center',
    },
    restoreText: {
        color: Colors.light.subtext,
        fontSize: 14,
        textDecorationLine: 'underline',
    },
    loginButton: {
        backgroundColor: '#000', // Black for Apple
        padding: 16,
        borderRadius: Theme.borderRadius.m,
        alignItems: 'center',
        flexDirection: 'row',
        justifyContent: 'center',
        marginTop: 10,
    },
    loginButtonText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 16,
    },
    logoutButton: {
        marginTop: 10,
        padding: 10,
        alignItems: 'center',
        borderWidth: 1,
        borderColor: Colors.light.subtext,
        borderRadius: Theme.borderRadius.m,
    },
    logoutButtonText: {
        color: Colors.light.subtext,
        fontSize: 14,
    },
    deleteButton: {
        backgroundColor: '#D32F2F',
        padding: 16,
        borderRadius: Theme.borderRadius.m,
        alignItems: 'center',
        marginTop: 8,
    },
    deleteButtonText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 16,
    },
    deleteNote: {
        marginTop: 8,
        fontSize: 12,
        color: '#D32F2F',
        textAlign: 'center',
    }
});
