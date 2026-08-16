import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { GestureDetector, Gesture } from 'react-native-gesture-handler';
import Animated, { useSharedValue, useAnimatedStyle, withSpring, runOnJS, withTiming, withRepeat, withSequence, Easing, withDelay } from 'react-native-reanimated';
import { Theme, Colors } from '../constants/Colors';

interface TriviaItem {
    id: number;
    title: string;
    content: string;
    category: string;
}

interface TriviaCardProps {
    item: TriviaItem;
    onSwipe: ((direction: 'left' | 'right') => void) | undefined;
    onPressDetails: () => void;
    onDoubleTap?: () => void;
    style?: any;
    enabled?: boolean;
    width: number;
    height: number;
}

// Floating Question Mark Component
const FloatingMark = ({ delay = 0, size = 40, x = 0, y = 0, color = '#eee' }: { delay?: number, size?: number, x?: number, y?: number, color?: string }) => {
    const translateY = useSharedValue(0);

    useEffect(() => {
        translateY.value = withDelay(delay, withRepeat(
            withSequence(
                withTiming(-20, { duration: 1500, easing: Easing.inOut(Easing.quad) }),
                withTiming(0, { duration: 1500, easing: Easing.inOut(Easing.quad) })
            ),
            -1,
            true
        ));
    }, [delay, translateY]);

    const style = useAnimatedStyle(() => ({
        transform: [{ translateY: translateY.value }],
    }));

    return (
        <Animated.View style={[{ position: 'absolute', left: x, top: y, padding: 10 }, style]}>
            <Text style={{ fontSize: size, fontWeight: '900', color: color, opacity: 0.5, includeFontPadding: false }}>
                ?
            </Text>
        </Animated.View>
    );
};

export default function TriviaCard({
    item,
    onSwipe,
    onPressDetails,
    onDoubleTap,
    style,
    enabled = true,
    width,
    height,
}: TriviaCardProps) {
    const isCompact = height < 460;
    const isVeryCompact = height < 370;
    const translationX = useSharedValue(0);
    const translationY = useSharedValue(0);
    const rotation = useSharedValue(0);
    const scale = useSharedValue(1);

    // Double Tap Animation values
    const thumbOpacity = useSharedValue(0);
    const thumbScale = useSharedValue(0.5);
    const thumbTranslateY = useSharedValue(0);
    const thumbTranslateX = useSharedValue(0);
    const thumbRotate = useSharedValue(0);

    const [showThumb, setShowThumb] = useState(false);

    const pan = Gesture.Pan()
        .enabled(enabled)
        .onBegin(() => {
            scale.value = withSpring(1.05); // Pop up when touched
        })
        .onUpdate((event) => {
            translationX.value = event.translationX;
            translationY.value = event.translationY * 0.1;
            rotation.value = event.translationX / 15;
        })
        .onEnd((event) => {
            scale.value = withSpring(1);
            if (Math.abs(event.translationX) > 40) { // Changed from 60 to 40
                const direction = event.translationX > 0 ? 'right' : 'left';
                translationX.value = withTiming(direction === 'right' ? 500 : -500, { duration: 300 });
                if (onSwipe) {
                    runOnJS(onSwipe)(direction);
                }
            } else {
                translationX.value = withSpring(0, { damping: 12, stiffness: 120 }); // Bouncy result
                translationY.value = withSpring(0);
                rotation.value = withSpring(0);
            }
        });

    const triggerDoubleTapEvents = () => {
        setShowThumb(true);
        if (onDoubleTap) {
            onDoubleTap();
        }
        setTimeout(() => setShowThumb(false), 900);
    };

    const doubleTap = Gesture.Tap()
        .numberOfTaps(2)
        .enabled(enabled)
        .onStart(() => {
            // Trigger the "へぇ" animation
            const angleDirection = Math.random() > 0.5 ? 1 : -1;
            const randomAngle = angleDirection * (Math.random() * 10 + 10); // 10 to 20 degrees
            const randomTranslateX = angleDirection * (Math.random() * 30 + 30); // 30 to 60 px movement horizontally

            thumbOpacity.value = 1;
            thumbScale.value = 0.5;
            thumbTranslateY.value = 0;
            thumbTranslateX.value = 0;
            thumbRotate.value = 0;
            
            thumbScale.value = withSpring(1.2, { damping: 8 });
            thumbTranslateY.value = withTiming(-100, { duration: 800 });
            thumbTranslateX.value = withTiming(randomTranslateX, { duration: 800 });
            thumbRotate.value = withTiming(randomAngle, { duration: 800 });
            
            thumbOpacity.value = withDelay(400, withTiming(0, { duration: 400 }));
            // Call JS functions safely
            runOnJS(triggerDoubleTapEvents)();
        });

    const composedGesture = Gesture.Simultaneous(pan, doubleTap);

    const animatedStyle = useAnimatedStyle(() => {
        return {
            transform: [
                { translateX: translationX.value },
                { translateY: translationY.value },
                { rotate: `${rotation.value}deg` },
                { scale: scale.value }
            ] as any,
        };
    });

    const thumbAnimatedStyle = useAnimatedStyle(() => ({
        opacity: thumbOpacity.value,
        transform: [
            { translateX: thumbTranslateX.value },
            { translateY: thumbTranslateY.value },
            { scale: thumbScale.value },
            { rotate: `${thumbRotate.value}deg` }
        ] as any,
    }));

    return (
        <GestureDetector gesture={composedGesture}>
            <Animated.View style={[styles.cardContainer, { width, height }, animatedStyle, style]}>
                
                {/* Background Decorations inside card */}
                <View style={[styles.card, isCompact && styles.cardCompact, isVeryCompact && styles.cardVeryCompact]}>
                    {/* Floating Background Elements */}
                    <View style={StyleSheet.absoluteFill} pointerEvents="none">
                        <FloatingMark delay={0} size={80} x={20} y={40} color="#FFCDD2" />
                        <FloatingMark delay={500} size={50} x={250} y={150} color="#EF9A9A" />
                    </View>

                    {/* Header */}
                    <View style={[styles.cardHeader, isCompact && styles.cardHeaderCompact]}>
                        <View style={[styles.categoryBadge, isCompact && styles.categoryBadgeCompact]}>
                            <Text style={[styles.categoryText, isVeryCompact && styles.categoryTextVeryCompact]}>{item.category || "雑学"}</Text>
                        </View>
                        {/* Circle Badge with ID or Icon */}
                        <View style={[styles.idBadge, isCompact && styles.idBadgeCompact]}>
                            <Ionicons name="sparkles" size={isCompact ? 14 : 16} color={Colors.light.primary} />
                        </View>
                    </View>

                    {/* Main Content */}
                    <View style={[styles.contentContainer, isCompact && styles.contentContainerCompact]}>
                        <View style={[
                            styles.iconCircle,
                            isCompact && styles.iconCircleCompact,
                            isVeryCompact && styles.iconCircleVeryCompact,
                        ]}>
                            <Ionicons name="bulb" size={isVeryCompact ? 34 : isCompact ? 42 : 56} color={Colors.light.accent} />
                        </View>
                        <Text
                            style={[styles.title, isCompact && styles.titleCompact, isVeryCompact && styles.titleVeryCompact]}
                            numberOfLines={isVeryCompact ? 2 : 3}
                            maxFontSizeMultiplier={1.3}
                        >
                            {item.title}
                        </Text>
                        {!isVeryCompact ? <View style={[styles.bgStripe, isCompact && styles.bgStripeCompact]} /> : null}
                        <Text
                            style={[styles.content, isCompact && styles.contentCompact, isVeryCompact && styles.contentVeryCompact]}
                            numberOfLines={isVeryCompact ? 3 : isCompact ? 4 : 5}
                            maxFontSizeMultiplier={1.3}
                        >
                            {item.content}
                        </Text>
                    </View>
                    
                    {/* "へぇ" animation overlay for double tap */}
                    <Animated.View style={[styles.heeAnimationContainer, thumbAnimatedStyle]} pointerEvents="none">
                        <Text style={styles.heeAnimationText}>へぇ</Text>
                    </Animated.View>

                    {/* Footer Button */}
                    <Pressable style={[styles.footerButton, isCompact && styles.footerButtonCompact]} onPress={onPressDetails}>
                        <Text style={[styles.readMore, isVeryCompact && styles.readMoreVeryCompact]} maxFontSizeMultiplier={1.3}>くわしく見る！</Text>
                        <View style={styles.arrowCircle}>
                            <Ionicons name="arrow-forward" size={16} color={Colors.light.primary} />
                        </View>
                    </Pressable>
                </View>
            </Animated.View>
        </GestureDetector>
    );
}

const styles = StyleSheet.create({
    cardContainer: {
        position: 'absolute',
        alignItems: 'center',
        justifyContent: 'center',
    },
    card: {
        width: '100%',
        height: '100%',
        backgroundColor: Colors.light.cardBackground,
        borderRadius: Theme.borderRadius.xl, // Very round
        ...Theme.shadow.pop, // Strong shadow
        padding: Theme.spacing.l,
        justifyContent: 'space-between',
        borderWidth: 4, // Bold border
        borderColor: Colors.light.border,
        overflow: 'hidden', // Contain animations
    },
    cardCompact: {
        padding: Theme.spacing.m,
        borderRadius: Theme.borderRadius.l,
    },
    cardVeryCompact: {
        padding: 12,
    },
    cardHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: Theme.spacing.m,
        zIndex: 1,
    },
    cardHeaderCompact: {
        marginBottom: 6,
    },
    categoryBadge: {
        backgroundColor: Colors.light.primary,
        paddingHorizontal: 16,
        paddingVertical: 8,
        borderRadius: 20,
    },
    categoryBadgeCompact: {
        paddingHorizontal: 12,
        paddingVertical: 6,
    },
    categoryText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 14,
        letterSpacing: 1,
    },
    categoryTextVeryCompact: {
        fontSize: 12,
    },
    idBadge: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: '#FFF0F0',
        alignItems: 'center',
        justifyContent: 'center',
    },
    idBadgeCompact: {
        width: 30,
        height: 30,
        borderRadius: 15,
    },
    contentContainer: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        paddingVertical: Theme.spacing.m,
        zIndex: 1,
    },
    contentContainerCompact: {
        paddingVertical: 4,
    },
    iconCircle: {
        width: 100,
        height: 100,
        borderRadius: 50,
        backgroundColor: '#FFF8E1', // Light yellow
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: Theme.spacing.l,
        borderWidth: 4,
        borderColor: 'white',
        ...Theme.shadow.small,
    },
    iconCircleCompact: {
        width: 72,
        height: 72,
        borderRadius: 36,
        marginBottom: 10,
        borderWidth: 3,
    },
    iconCircleVeryCompact: {
        width: 52,
        height: 52,
        borderRadius: 26,
        marginBottom: 6,
    },
    title: {
        fontSize: 24,
        fontWeight: '900', // Heavy font
        color: Colors.light.text,
        textAlign: 'center',
        marginBottom: Theme.spacing.m,
        lineHeight: 32,
    },
    titleCompact: {
        fontSize: 21,
        lineHeight: 27,
        marginBottom: 8,
    },
    titleVeryCompact: {
        fontSize: 18,
        lineHeight: 22,
        marginBottom: 4,
    },
    bgStripe: {
        width: '100%',
        height: 8,
        backgroundColor: '#F5F5F5',
        borderRadius: 4,
        marginBottom: Theme.spacing.m,
    },
    bgStripeCompact: {
        height: 5,
        marginBottom: 8,
    },
    content: {
        fontSize: 16,
        color: Colors.light.subtext,
        textAlign: 'center',
        lineHeight: 26,
        fontWeight: '600',
    },
    contentCompact: {
        fontSize: 14,
        lineHeight: 20,
    },
    contentVeryCompact: {
        fontSize: 13,
        lineHeight: 18,
    },
    footerButton: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#F5F5F5',
        paddingVertical: 14,
        borderRadius: Theme.borderRadius.l,
        zIndex: 1,
    },
    footerButtonCompact: {
        paddingVertical: 9,
        borderRadius: Theme.borderRadius.m,
    },
    readMore: {
        fontSize: 16,
        color: Colors.light.primary,
        fontWeight: 'bold',
        marginRight: 8,
    },
    readMoreVeryCompact: {
        fontSize: 14,
    },
    arrowCircle: {
        width: 24,
        height: 24,
        borderRadius: 12,
        backgroundColor: 'white',
        alignItems: 'center',
        justifyContent: 'center',
    },
    heeAnimationContainer: {
        position: 'absolute',
        top: '20%', // Moved higher up (20% from top instead of center)
        left: 0,
        right: 0,
        alignItems: 'center',
        justifyContent: 'center',
        elevation: 10,
        zIndex: 100,
    },
    heeAnimationText: {
        fontSize: 50, // Reduced from 100
        fontWeight: '900',
        color: '#FF3B30', // Red color
        textShadowColor: 'white',
        textShadowOffset: { width: 0, height: 0 },
        textShadowRadius: 10,
    }
});
