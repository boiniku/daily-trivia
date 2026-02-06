import React from 'react';
import { View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator } from 'react-native';
import { useRevenueCat } from '../contexts/RevenueCatContext';
import { Colors, Theme } from '../constants/Colors';
import { Ionicons } from '@expo/vector-icons';

export default function Paywall() {
    const { currentOffering, purchasePackage, restorePurchases } = useRevenueCat();

    if (!currentOffering) {
        return (
            <View style={styles.loadingContainer}>
                <ActivityIndicator size="large" color={Colors.light.primary} />
                <Text style={styles.loadingText}>プランを読み込み中...</Text>
            </View>
        );
    }

    return (
        <ScrollView contentContainerStyle={styles.container}>
            <View style={styles.header}>
                <Ionicons name="star" size={60} color={Colors.light.accent} />
                <Text style={styles.title}>プレミアムプラン</Text>
                <Text style={styles.subtitle}>毎日雑学をもっと楽しもう！</Text>
            </View>

            <View style={styles.features}>
                <FeatureItem icon="infinite" text="過去の雑学が無制限に見放題" />
                <FeatureItem icon="time" text="1日3つの制限なし" />
                <FeatureItem icon="heart" text="お気に入り保存数 無制限" />
                <FeatureItem icon="happy" text="開発者を応援！" />
            </View>

            <View style={styles.packages}>
                {currentOffering.availablePackages.map((pack) => (
                    <Pressable
                        key={pack.identifier}
                        style={styles.packageButton}
                        onPress={() => purchasePackage(pack)}
                    >
                        <Text style={styles.packageTitle}>{pack.product.title}</Text>
                        <Text style={styles.packagePrice}>{pack.product.priceString}</Text>
                        <Text style={styles.packageDesc}>購入する</Text>
                    </Pressable>
                ))}
            </View>

            <Pressable onPress={restorePurchases} style={styles.restoreButton}>
                <Text style={styles.restoreText}>購入を復元する</Text>
            </Pressable>

            <Text style={styles.disclaimer}>
                ※ サブスクリプションはApple IDの設定からいつでも解約可能です。
            </Text>
        </ScrollView>
    );
}

function FeatureItem({ icon, text }: { icon: any, text: string }) {
    return (
        <View style={styles.featureItem}>
            <Ionicons name={icon} size={24} color={Colors.light.primary} style={{ marginRight: 15 }} />
            <Text style={styles.featureText}>{text}</Text>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        padding: 20,
        alignItems: 'center',
    },
    loadingContainer: {
        padding: 40,
        alignItems: 'center',
    },
    loadingText: {
        marginTop: 10,
        color: Colors.light.subtext,
    },
    header: {
        alignItems: 'center',
        marginBottom: 40,
    },
    title: {
        fontSize: 28,
        fontWeight: '900',
        color: Colors.light.text,
        marginTop: 10,
    },
    subtitle: {
        fontSize: 16,
        color: Colors.light.subtext,
        marginTop: 5,
    },
    features: {
        width: '100%',
        marginBottom: 40,
        backgroundColor: 'white',
        padding: 20,
        borderRadius: Theme.borderRadius.l,
        ...Theme.shadow.small,
    },
    featureItem: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: 15,
    },
    featureText: {
        fontSize: 16,
        color: Colors.light.text,
        fontWeight: '600',
    },
    packages: {
        width: '100%',
        marginBottom: 20,
    },
    packageButton: {
        backgroundColor: Colors.light.primary,
        padding: 20,
        borderRadius: 50,
        alignItems: 'center',
        marginBottom: 15,
        ...Theme.shadow.pop,
    },
    packageTitle: {
        color: 'white',
        fontSize: 14,
        fontWeight: 'bold',
        opacity: 0.9,
    },
    packagePrice: {
        color: 'white',
        fontSize: 24,
        fontWeight: '900',
        marginVertical: 4,
    },
    packageDesc: {
        color: 'white',
        fontSize: 16,
        fontWeight: 'bold',
    },
    restoreButton: {
        padding: 10,
    },
    restoreText: {
        color: Colors.light.subtext,
        textDecorationLine: 'underline',
    },
    disclaimer: {
        marginTop: 20,
        fontSize: 12,
        color: Colors.light.subtext,
        textAlign: 'center',
    },
});
