import React, { useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, {
    useSharedValue,
    useAnimatedStyle,
    withRepeat,
    withSequence,
    withTiming,
    Easing,
} from 'react-native-reanimated';
import { Ionicons } from '@expo/vector-icons';
import { Theme, Colors } from '../constants/Colors';

type GuideMode = 'tap' | 'swipe';

export default function SwipeGuide({ mode = 'swipe' }: { mode?: GuideMode }) {
    const translateX = useSharedValue(0);
    const tapScale = useSharedValue(1);

    useEffect(() => {
        // Horizontal swiping animation
        translateX.value = withRepeat(
            withSequence(
                withTiming(30, { duration: 800, easing: Easing.inOut(Easing.ease) }),
                withTiming(0, { duration: 800, easing: Easing.inOut(Easing.ease) }),
                withTiming(-30, { duration: 800, easing: Easing.inOut(Easing.ease) }),
                withTiming(0, { duration: 800, easing: Easing.inOut(Easing.ease) })
            ),
            -1, // Infinite
            true
        );
    }, []);

    const flashOpacity = useSharedValue(0.8);

    useEffect(() => {
        // Flashing animation (fades out and in every 3 seconds)
        flashOpacity.value = withRepeat(
            withSequence(
                withTiming(0.1, { duration: 1500, easing: Easing.inOut(Easing.ease) }),
                withTiming(0.8, { duration: 1500, easing: Easing.inOut(Easing.ease) })
            ),
            -1,
            true
        );
    }, []);

    useEffect(() => {
        tapScale.value = withRepeat(
            withSequence(
                withTiming(1.18, { duration: 220, easing: Easing.out(Easing.ease) }),
                withTiming(1, { duration: 180, easing: Easing.inOut(Easing.ease) }),
                withTiming(1.18, { duration: 220, easing: Easing.out(Easing.ease) }),
                withTiming(1, { duration: 600, easing: Easing.inOut(Easing.ease) })
            ),
            -1,
            false
        );
    }, []);

    const animatedStyle = useAnimatedStyle(() => {
        return {
            transform: [{ translateX: translateX.value }],
        };
    });

    const overlayAnimatedStyle = useAnimatedStyle(() => {
        return {
            opacity: flashOpacity.value,
        };
    });

    const tapAnimatedStyle = useAnimatedStyle(() => {
        return {
            transform: [{ scale: tapScale.value }],
        };
    });

    return (
        <View style={styles.container} pointerEvents="none">
            <Animated.View style={[styles.overlay, overlayAnimatedStyle]}>
                <View style={styles.guideRow}>
                    {mode === 'tap' ? (
                        <View style={styles.guideItemWide}>
                            <Animated.View style={[styles.iconContainer, tapAnimatedStyle]}>
                                <Ionicons name="finger-print" size={52} color="rgba(255, 255, 255, 0.9)" />
                            </Animated.View>
                            <Text style={styles.text}>雑学カードをダブルタップ</Text>
                            <Text style={styles.subText}>へぇを送れます</Text>
                        </View>
                    ) : (
                        <View style={styles.guideItemWide}>
                            <Animated.View style={[styles.iconContainer, animatedStyle]}>
                                <Ionicons name="hand-right" size={52} color="rgba(255, 255, 255, 0.9)" />
                            </Animated.View>
                            <Text style={styles.text}>左右にスワイプ</Text>
                            <Text style={styles.subText}>次の雑学へ</Text>
                        </View>
                    )}
                </View>
            </Animated.View>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        ...StyleSheet.absoluteFillObject,
        justifyContent: 'flex-start', // Move higher up instead of center
        alignItems: 'center',
        paddingTop: 80, // Offset from top
        zIndex: 100, // Make sure it's above the cards
    },
    overlay: {
        backgroundColor: 'rgba(0, 0, 0, 0.25)', // Lighter background
        paddingVertical: 18,
        paddingHorizontal: 22,
        borderRadius: Theme.borderRadius.l,
        alignItems: 'center',
        justifyContent: 'center',
    },
    guideRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
    },
    guideItemWide: {
        width: 240,
        alignItems: 'center',
    },
    iconContainer: {
        marginBottom: 10,
    },
    text: {
        color: 'white',
        fontSize: 16, // Slightly smaller text
        fontWeight: 'bold',
        textShadowColor: 'rgba(0,0,0,0.5)',
        textShadowOffset: { width: 0, height: 1 },
        textShadowRadius: 3,
        marginTop: 4,
        textAlign: 'center',
    },
    subText: {
        color: 'white',
        fontSize: 14,
        fontWeight: '600',
        textShadowColor: 'rgba(0,0,0,0.5)',
        textShadowOffset: { width: 0, height: 1 },
        textShadowRadius: 3,
        marginTop: 4,
        textAlign: 'center',
    }
});
