import { View, Text, StyleSheet, Pressable, Alert, ScrollView, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useState } from 'react';
import { Colors, Theme } from '../../constants/Colors';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import { useAuth } from '../../contexts/AuthContext';
import LoginModal from '../../components/LoginModal';

export default function SettingsScreen() {
    const { isPro, currentOffering, purchasePackage, restorePurchases, retryLoadOfferings, loading } = useRevenueCat();
    const { userId, isGuest, signOut, deleteAccount } = useAuth();
    const [loginVisible, setLoginVisible] = useState(false);

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
                        await deleteAccount();
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
                    <View style={{ marginBottom: 16 }}>
                        <Text style={{ fontSize: 10, color: Colors.light.subtext }}>ID: {userId}</Text>
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
                                    const isLifetime = (pack.packageType as any) === 'LIFETIME' || pack.product.identifier.toLowerCase().includes('lifetime');

                                    if (isMonthly) {
                                        suffix = " / 月";
                                    } else if (isLifetime) {
                                        suffix = " (買い切り)";
                                    } else {
                                        suffix = isLifetime ? ' (買い切り)' : ' / 月';
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
                                            <Text style={styles.premiumDesc}>広告なし、閲覧数無制限</Text>
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
                    <Text style={styles.sectionHeader}>アプリについて</Text>
                    <View style={styles.infoRow}>
                        <Text style={styles.infoLabel}>バージョン</Text>
                        <Text style={styles.infoValue}>1.0.0</Text>
                    </View>


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
