import { ActivityIndicator, Alert, View, Text, StyleSheet, Dimensions, Linking, Pressable, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import Animated, {
    FadeInDown,
} from 'react-native-reanimated';
import { useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Ionicons } from '@expo/vector-icons';
import { Theme, Colors } from '../constants/Colors';
import { TriviaGeofenceEnableResult, TriviaGeofenceManager } from '../managers/TriviaGeofenceManager';

const { width } = Dimensions.get('window');

// Widget Preview Component
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

const TutorialStep = ({
    title,
    description,
    icon,
    index,
    currentIndex
}: {
    title: string,
    description: string,
    icon?: string,
    index: number,
    currentIndex: number
}) => {
    const isActive = index === currentIndex;

    if (!isActive) return null;

    return (
        <Animated.View entering={FadeInDown.springify()} style={styles.stepContainer}>
            <View style={styles.iconContainer}>
                {index === 1 ? (
                    <WidgetPreview />
                ) : icon ? (
                    <Ionicons name={icon as any} size={80} color={Colors.light.primary} />
                ) : (
                    <View style={{ width: 200, height: 200, backgroundColor: '#FFF8E1', borderRadius: 20 }} />
                )}
            </View>
            <Text style={styles.title}>{title}</Text>
            <Text style={styles.description}>{description}</Text>
        </Animated.View>
    );
};

export default function TutorialScreen() {
    const router = useRouter();
    const [step, setStep] = useState(0);
    const [isEnablingNotifications, setIsEnablingNotifications] = useState(false);

    const steps = [
        {
            title: "毎日雑学へようこそ！",
            description: "このアプリは、あなたの日常にちょっとした「へぇ〜」をお届けします。",
            icon: "bulb", // Changed to bulb
        },
        {
            title: "ウィジェットを追加しよう",
            description: "ホーム画面にウィジェットを追加するとアプリを開かずに今日の雑学をチェックできます。\n\nホーム画面に置いておくだけで、あなたの脳内にユニークな雑学が自動インストールされます。",
            icon: "apps", // Replaced by WidgetPreview
        },
        {
            title: "1日3つまで",
            description: "無料で読めるのは1日3つまで。\n\n厳選された雑学を毎日楽しみにしていてくださいね！",
            icon: "time",
        },
        {
            title: "近くの雑学を見つけよう",
            description: "雑学スポットの近くに行くと、新しい雑学が解放されます。通知を設定すると、アプリを開いていないときもお知らせします。\n\n位置情報は端末内での開放判定にのみ使い、移動履歴は保存しません。",
            icon: "location",
        }
    ];

    const finishTutorial = async () => {
        await AsyncStorage.setItem('hasSeenTutorial', 'true');
        await AsyncStorage.setItem('pendingSwipeGuide', 'true');
        router.replace('/');
    };

    const showPermissionResult = (result: TriviaGeofenceEnableResult) => {
        if (result === 'enabled') return;

        const message = result === 'notification-denied'
            ? '通知が許可されていません。あとからiPhoneの設定またはアプリの設定画面で変更できます。'
            : result === 'native-build-outdated'
                ? 'バックグラウンド通知に対応した最新のdevelopment buildをインストールしてください。'
            : result === 'foreground-location-denied'
                ? '位置情報が許可されていません。あとから設定すると、近くの雑学を見つけられます。'
                : result === 'background-location-denied'
                    ? 'バックグラウンド通知には、位置情報を「常に」に設定する必要があります。'
                    : 'この端末ではバックグラウンド通知を設定できませんでした。';

        Alert.alert('あとから設定できます', message, [
            { text: '閉じる', style: 'cancel' },
            ...(result === 'unsupported' || result === 'native-build-outdated'
                ? []
                : [{ text: 'iPhoneの設定を開く', onPress: () => Linking.openSettings() }]),
        ]);
    };

    const handleNext = async () => {
        if (step < steps.length - 1) {
            setStep(step + 1);
        } else {
            try {
                setIsEnablingNotifications(true);
                const result = await TriviaGeofenceManager.enable();
                await finishTutorial();
                showPermissionResult(result);
            } catch (e) {
                console.error(e);
                await finishTutorial();
            } finally {
                setIsEnablingNotifications(false);
            }
        }
    };

    const handleSkipNotifications = async () => {
        try {
            await finishTutorial();
        } catch (error) {
            console.error(error);
        }
    };

    const isNotificationStep = step === steps.length - 1;

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.content}>
                <TutorialStep
                    {...steps[step]}
                    index={step}
                    currentIndex={step}
                />
            </View>

            <View style={[styles.footer, isNotificationStep && styles.notificationFooter]}>
                <View style={styles.dots}>
                    {steps.map((_, i) => (
                        <View
                            key={i}
                            style={[
                                styles.dot,
                                i === step ? styles.activeDot : styles.inactiveDot
                            ]}
                        />
                    ))}
                </View>

                <Pressable
                    style={[
                        styles.button,
                        isNotificationStep && styles.notificationButton,
                        isEnablingNotifications && styles.buttonDisabled,
                    ]}
                    onPress={handleNext}
                    disabled={isEnablingNotifications}
                >
                    {isEnablingNotifications ? (
                        <ActivityIndicator color="white" />
                    ) : (
                        <>
                            <Text style={styles.buttonText}>
                                {step === steps.length - 1 ? "通知を設定する" : "次へ"}
                            </Text>
                            <Ionicons name="arrow-forward" size={20} color="white" />
                        </>
                    )}
                </Pressable>

                {isNotificationStep && (
                    <Pressable
                        style={styles.skipButton}
                        onPress={handleSkipNotifications}
                        disabled={isEnablingNotifications}
                    >
                        <Text style={styles.skipButtonText}>今はしない</Text>
                    </Pressable>
                )}
            </View>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: Colors.light.background,
    },
    content: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        padding: 30,
    },
    stepContainer: {
        alignItems: 'center',
        width: '100%',
    },
    iconContainer: {
        marginBottom: 40,
        alignItems: 'center',
        justifyContent: 'center',
        // Removed fixed shadow to allow widget to handle it
    },
    title: {
        fontSize: 28,
        fontWeight: '900',
        color: Colors.light.primary,
        marginBottom: 20,
        textAlign: 'center',
    },
    description: {
        fontSize: 16,
        color: Colors.light.text,
        textAlign: 'center',
        lineHeight: 24,
        paddingHorizontal: 10,
    },
    footer: {
        padding: 30,
        paddingBottom: Platform.OS === 'ios' ? 20 : 40,
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
    },
    notificationFooter: {
        flexDirection: 'column',
        gap: 14,
    },
    dots: {
        flexDirection: 'row',
        gap: 8,
    },
    dot: {
        height: 8,
        borderRadius: 4,
    },
    activeDot: {
        width: 24,
        backgroundColor: Colors.light.primary,
    },
    inactiveDot: {
        width: 8,
        backgroundColor: '#DDD',
    },
    button: {
        flexDirection: 'row',
        backgroundColor: Colors.light.primary,
        paddingVertical: 12,
        paddingHorizontal: 24,
        borderRadius: 30,
        alignItems: 'center',
        gap: 8,
        ...Theme.shadow.small,
    },
    buttonText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 16,
    },
    buttonDisabled: {
        opacity: 0.65,
    },
    notificationButton: {
        width: '100%',
        justifyContent: 'center',
    },
    skipButton: {
        paddingVertical: 12,
        paddingHorizontal: 8,
    },
    skipButtonText: {
        color: Colors.light.subtext,
        fontSize: 14,
        fontWeight: '600',
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
