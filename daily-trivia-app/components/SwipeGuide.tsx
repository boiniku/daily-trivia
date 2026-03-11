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

export default function SwipeGuide() {
    const translateX = useSharedValue(0);

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

    return (
        <View style={styles.container} pointerEvents="none">
            <Animated.View style={[styles.overlay, overlayAnimatedStyle]}>
                <Animated.View style={[styles.iconContainer, animatedStyle]}>
                    <Ionicons name="hand-right" size={50} color="rgba(255, 255, 255, 0.9)" />
                </Animated.View>
                <View style={styles.textContainer}>
                    <Text style={styles.text}>左右にスワイプして</Text>
                    <Text style={styles.text}>次の雑学へ</Text>
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
        paddingVertical: 20,
        paddingHorizontal: 40,
        borderRadius: Theme.borderRadius.l,
        alignItems: 'center',
        justifyContent: 'center',
    },
    iconContainer: {
        marginBottom: 10,
    },
    textContainer: {
        alignItems: 'center',
    },
    text: {
        color: 'white',
        fontSize: 16, // Slightly smaller text
        fontWeight: 'bold',
        textShadowColor: 'rgba(0,0,0,0.5)',
        textShadowOffset: { width: 0, height: 1 },
        textShadowRadius: 3,
        marginTop: 4,
    }
});
