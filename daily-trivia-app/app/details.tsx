import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, StyleSheet, ScrollView, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Theme, Colors } from '../constants/Colors';

export default function DetailsScreen() {
    const params = useLocalSearchParams();
    const router = useRouter();

    // Data passed from index.tsx
    const title = params.title as string || 'タイトルなし';
    const explanation = params.explanation as string || '解説データがありません';
    const source = params.source as string || '';
    const category = params.category as string || '未分類';
    const content = params.content as string || '';

    return (
        <View style={styles.container}>
            <SafeAreaView edges={['top']} style={{ flex: 1 }}>
                <View style={styles.header}>
                    <Pressable onPress={() => router.back()} style={styles.backButton}>
                        <Ionicons name="arrow-back" size={24} color={Colors.light.text} />
                    </Pressable>
                    <Text style={styles.headerTitle}>解説</Text>
                    <View style={{ width: 24 }} />
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

                    {source ? (
                        <View style={[styles.section, { borderBottomWidth: 0 }]}>
                            <View style={styles.sectionHeader}>
                                <Ionicons name="book" size={20} color={Colors.light.subtext} style={{ marginRight: 8 }} />
                                <Text style={styles.sourceTitle}>出典・参考</Text>
                            </View>
                            <Text style={styles.sourceText}>{source}</Text>
                        </View>
                    ) : null}
                </ScrollView>
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
});
