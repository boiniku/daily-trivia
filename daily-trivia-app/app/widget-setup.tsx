import { View, Text, StyleSheet, Dimensions, Pressable, Platform, ScrollView, Image } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Ionicons } from '@expo/vector-icons';
import { Theme, Colors } from '../constants/Colors';
import Animated, { FadeInDown } from 'react-native-reanimated';

const { width } = Dimensions.get('window');

// Widget Preview Component reused from tutorial
const WidgetPreview = () => (
    <View style={styles.widgetPreview}>
        {/* Background - Noon Theme */}
        <View style={[styles.widgetBackground, { backgroundColor: '#87CEEB' }]}>
            {/* Simple Cloud/Sun logic for mockup */}
            <View style={{ position: 'absolute', top: 10, left: 10, width: 30, height: 30, borderRadius: 15, backgroundColor: 'rgba(255,255,255,0.6)' }} />
            <View style={{ position: 'absolute', bottom: 10, right: 10, width: 100, height: 40, borderRadius: 20, backgroundColor: 'rgba(76, 175, 80, 0.6)' }} />
        </View>

        {/* Content */}
        <View style={styles.widgetContent}>
            <View style={styles.widgetHeader}>
                <Text style={styles.widgetHeaderText}>⛅️ こんにちは雑学</Text>
            </View>
            <View style={{ flex: 1, justifyContent: 'center' }}>
                <Text style={styles.widgetTitle}>富士山の高さ</Text>
                <Text style={styles.widgetText}>富士山の高さは3776メートルです。</Text>
            </View>
        </View>
    </View>
);

// iOS Home Screen "Edit Mode" Mockup
const HomeScreenMockup = () => (
    <View style={styles.mockupContainer}>
        {/* iOS StatusBar / Header Area */}
        <View style={styles.mockupHeader}>
            <View style={styles.mockupPlusButton}>
                <Ionicons name="add" size={24} color={Colors.light.background} />
                {/* Highlight ring for emphasis */}
                <View style={[StyleSheet.absoluteFill, styles.mockupHighlightRing]} />
            </View>
            <View style={styles.mockupDynamicIsland} />
            <Text style={styles.mockupDoneText}>完了</Text>
        </View>

        {/* Mock App Icons (Jiggling simulation via tilt) */}
        <View style={styles.mockupAppsRow}>
            {[1, 2, 3, 4].map((_, i) => (
                <View key={i} style={styles.mockupAppIconWrapper}>
                    <View style={[styles.mockupAppIcon, { backgroundColor: ['#F44336', '#4CAF50', '#2196F3', '#FFEB3B'][i] }]} />
                    <View style={styles.mockupMinusBadge}>
                        <Ionicons name="remove" size={12} color={Colors.light.text} />
                    </View>
                </View>
            ))}
        </View>

        <View style={styles.mockupAppsRow}>
            {[1, 2, 3, 4].map((_, i) => (
                <View key={i} style={styles.mockupAppIconWrapper}>
                    <View style={[styles.mockupAppIcon, { backgroundColor: ['#9C27B0', '#FF9800', '#00BCD4', '#8BC34A'][i] }]} />
                    <View style={styles.mockupMinusBadge}>
                        <Ionicons name="remove" size={12} color={Colors.light.text} />
                    </View>
                </View>
            ))}
        </View>
    </View>
);

export default function WidgetSetupScreen() {
    const router = useRouter();

    const handleUnderstood = async () => {
        try {
            await AsyncStorage.setItem('hasSeenWidgetGuide', 'true');
            router.back();
        } catch (e) {
            console.error(e);
            router.back(); // Still navigate back even if saving fails
        }
    };

    return (
        <SafeAreaView style={styles.container}>
            {/* Header */}
            <View style={styles.header}>
                <Pressable onPress={() => router.back()} style={styles.closeButton}>
                    <Ionicons name="close" size={28} color={Colors.light.text} />
                </Pressable>
                <Text style={styles.headerTitle}>ウィジェットの設定方法</Text>
                <View style={{ width: 44 }} /> {/* Spacer for centering */}
            </View>

            <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
                <Animated.View entering={FadeInDown.springify()} style={styles.topSection}>
                    <View style={styles.iconContainer}>
                        <WidgetPreview />
                    </View>
                    <Text style={styles.description}>
                        ホーム画面にウィジェットを追加すると、アプリを開かずに今日の雑学をチェックできます！
                    </Text>
                </Animated.View>

                <Animated.View entering={FadeInDown.delay(200).springify()} style={styles.stepsContainer}>
                    <Text style={styles.stepsTitle}>追加手順</Text>

                    <View style={styles.step}>
                        <View style={styles.stepNumber}><Text style={styles.stepNumberText}>1</Text></View>
                        <View style={styles.stepContent}>
                            <Text style={styles.stepText}>ホーム画面の何もない場所を<Text style={styles.bold}>長押し</Text>します。</Text>
                        </View>
                    </View>

                    <View style={styles.step}>
                        <View style={styles.stepNumber}><Text style={styles.stepNumberText}>2</Text></View>
                        <View style={styles.stepContent}>
                            <Text style={styles.stepText}>画面左上（または右上）の<Text style={styles.bold}>「＋」ボタン</Text>をタップします。</Text>
                        </View>
                    </View>

                    <View style={styles.imageContainer}>
                        <HomeScreenMockup />
                    </View>

                    <View style={styles.step}>
                        <View style={styles.stepNumber}><Text style={styles.stepNumberText}>3</Text></View>
                        <View style={styles.stepContent}>
                            <Text style={styles.stepText}>リストから<Text style={styles.bold}>「毎日雑学」</Text>を探して選択し、<Text style={styles.bold}>「ウィジェットを追加」</Text>をタップします。</Text>
                        </View>
                    </View>
                </Animated.View>
            </ScrollView>

            <View style={styles.footer}>
                <Pressable style={styles.button} onPress={handleUnderstood}>
                    <Text style={styles.buttonText}>理解した</Text>
                    <Ionicons name="checkmark-circle" size={20} color="white" />
                </Pressable>
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
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: 16,
        paddingVertical: 12,
        borderBottomWidth: 1,
        borderBottomColor: Colors.light.border,
    },
    closeButton: {
        padding: 8,
    },
    headerTitle: {
        fontSize: 18,
        fontWeight: 'bold',
        color: Colors.light.text,
    },
    scrollContent: {
        flexGrow: 1,
        padding: 24,
        paddingBottom: 40,
    },
    topSection: {
        alignItems: 'center',
        marginBottom: 40,
    },
    iconContainer: {
        marginBottom: 30,
        alignItems: 'center',
        justifyContent: 'center',
        marginTop: 20,
    },
    description: {
        fontSize: 16,
        color: Colors.light.text,
        textAlign: 'center',
        lineHeight: 24,
    },
    stepsContainer: {
        backgroundColor: Colors.light.cardBackground,
        borderRadius: 20,
        padding: 24,
        ...Theme.shadow.small,
    },
    stepsTitle: {
        fontSize: 20,
        fontWeight: 'bold',
        color: Colors.light.primary,
        marginBottom: 20,
    },
    step: {
        flexDirection: 'row',
        marginBottom: 20,
        alignItems: 'flex-start',
    },
    stepNumber: {
        width: 28,
        height: 28,
        borderRadius: 14,
        backgroundColor: Colors.light.accent,
        justifyContent: 'center',
        alignItems: 'center',
        marginRight: 12,
        marginTop: 2,
    },
    stepNumberText: {
        color: '#8B4500',
        fontWeight: 'bold',
        fontSize: 14,
    },
    stepContent: {
        flex: 1,
    },
    stepText: {
        fontSize: 16,
        color: Colors.light.text,
        lineHeight: 24,
    },
    bold: {
        fontWeight: 'bold',
    },
    imageContainer: {
        alignItems: 'center',
        marginVertical: 10,
        marginBottom: 30,
        width: '100%',
    },
    // Mockup Styles
    mockupContainer: {
        width: '100%',
        height: 180,
        backgroundColor: '#EAEAEA',
        borderRadius: 16,
        overflow: 'hidden',
        borderWidth: 1,
        borderColor: '#D4D4D4',
        padding: 10,
    },
    mockupHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingHorizontal: 8,
        marginTop: 10,
        marginBottom: 20,
    },
    mockupPlusButton: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: '#A0A0A0', // Subdued grey
        justifyContent: 'center',
        alignItems: 'center',
        position: 'relative',
    },
    mockupHighlightRing: {
        borderColor: Colors.light.primary,
        borderWidth: 3,
        borderRadius: 18,
        width: '100%',
        height: '100%',
        // Slight pulse or glow effect could go here
        shadowColor: Colors.light.primary,
        shadowOffset: { width: 0, height: 0 },
        shadowOpacity: 0.8,
        shadowRadius: 5,
    },
    mockupDynamicIsland: {
        width: 70,
        height: 20,
        backgroundColor: '#000',
        borderRadius: 10,
    },
    mockupDoneText: {
        fontSize: 14,
        fontWeight: 'bold',
        color: '#555',
        marginRight: 8,
    },
    mockupAppsRow: {
        flexDirection: 'row',
        justifyContent: 'space-around',
        marginBottom: 20,
        paddingHorizontal: 10,
    },
    mockupAppIconWrapper: {
        position: 'relative',
        transform: [{ rotate: '-2deg' }], // Jiggle effect
    },
    mockupAppIcon: {
        width: 44,
        height: 44,
        borderRadius: 10,
        backgroundColor: '#CCC',
    },
    mockupMinusBadge: {
        position: 'absolute',
        top: -6,
        left: -6,
        width: 18,
        height: 18,
        borderRadius: 9,
        backgroundColor: '#EEE',
        justifyContent: 'center',
        alignItems: 'center',
        borderWidth: 1,
        borderColor: '#CCC',
    },
    footer: {
        padding: 24,
        paddingBottom: Platform.OS === 'ios' ? 24 : 40,
        backgroundColor: Colors.light.background,
        borderTopWidth: 1,
        borderTopColor: Colors.light.border,
    },
    button: {
        flexDirection: 'row',
        backgroundColor: Colors.light.primary,
        paddingVertical: 16,
        borderRadius: 30,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        ...Theme.shadow.small,
    },
    buttonText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 18,
    },
    // Widget Preview Styles
    widgetPreview: {
        width: 300,
        height: 150,
        borderRadius: 22,
        overflow: 'hidden',
        position: 'relative',
        ...Theme.shadow.medium,
    },
    widgetBackground: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
    },
    widgetContent: {
        flex: 1,
        padding: 16,
        justifyContent: 'space-between',
    },
    widgetHeader: {
        backgroundColor: 'rgba(0,0,0,0.2)',
        paddingHorizontal: 10,
        paddingVertical: 5,
        borderRadius: 10,
        alignSelf: 'flex-start',
    },
    widgetHeaderText: {
        color: 'white',
        fontSize: 12,
        fontWeight: 'bold',
    },
    widgetTitle: {
        color: 'white',
        fontSize: 22,
        fontWeight: '900',
        marginBottom: 6,
        textShadowColor: 'rgba(0,0,0,0.3)',
        textShadowOffset: { width: 0, height: 1 },
        textShadowRadius: 2,
    },
    widgetText: {
        color: 'white',
        fontSize: 14,
        fontWeight: 'bold',
        lineHeight: 20,
        textShadowColor: 'rgba(0,0,0,0.3)',
        textShadowOffset: { width: 0, height: 1 },
        textShadowRadius: 2,
    }
});
