import { View, Text, StyleSheet, Pressable, SafeAreaView } from 'react-native';
import { Colors, Theme } from '../../constants/Colors';

export default function SettingsScreen() {
    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <Text style={styles.title}>設定</Text>
            </View>

            <View style={styles.content}>
                <View style={styles.section}>
                    <Text style={styles.sectionHeader}>サブスクリプション</Text>
                    <Pressable style={styles.premiumButton}>
                        <Text style={styles.premiumButtonText}>プレミアムプラン (月額300円)</Text>
                        <Text style={styles.premiumDesc}>広告なし、閲覧数無制限</Text>
                    </Pressable>
                </View>

                <View style={styles.section}>
                    <Text style={styles.sectionHeader}>アプリについて</Text>
                    <View style={styles.infoRow}>
                        <Text style={styles.infoLabel}>バージョン</Text>
                        <Text style={styles.infoValue}>1.0.0</Text>
                    </View>
                </View>
            </View>
        </SafeAreaView>
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
    },
    premiumButtonText: {
        color: '#8B4500',
        fontWeight: 'bold',
        fontSize: 18,
        marginBottom: 4,
    },
    premiumDesc: {
        color: '#8B4500',
        fontSize: 14,
        opacity: 0.8,
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
    }
});
