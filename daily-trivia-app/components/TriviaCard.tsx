import React, { useEffect } from 'react';
import { View, Text, StyleSheet, Dimensions, Pressable, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { GestureDetector, Gesture } from 'react-native-gesture-handler';
import Animated, { useSharedValue, useAnimatedStyle, withSpring, runOnJS, withTiming, withRepeat, withSequence, Easing, withDelay } from 'react-native-reanimated';
import { Theme, Colors } from '../constants/Colors';

const SCREEN_WIDTH = Dimensions.get('window').width;
const CARD_WIDTH = SCREEN_WIDTH * 0.85; // Slightly narrower for pop effect
const CARD_HEIGHT = 500;

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
    style?: any;
    enabled?: boolean;
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
    }, []);

    const style = useAnimatedStyle(() => ({
        transform: [{ translateY: translateY.value }],
    }));

    return (
        <Animated.View style={[{ position: 'absolute', left: x, top: y, padding: 10 }, style]}>
            {/* Use Text for thicker font weight instead of Icon */}
            <Text style={{ fontSize: size, fontWeight: '900', color: color, opacity: 0.5, includeFontPadding: false }}>
                ?
            </Text>
        </Animated.View>
    );
};

export default function TriviaCard({ item, onSwipe, onPressDetails, style, enabled = true }: TriviaCardProps) {
    const translationX = useSharedValue(0);
    const translationY = useSharedValue(0);
    const rotation = useSharedValue(0);
    const scale = useSharedValue(1);

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
            if (Math.abs(event.translationX) > 120) {
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

    const animatedStyle = useAnimatedStyle(() => {
        return {
            transform: [
                { translateX: translationX.value },
                { translateY: translationY.value },
                { rotate: `${rotation.value}deg` },
                { scale: scale.value }
            ],
        };
    });

    return (
        <GestureDetector gesture={pan}>
            <Animated.View style={[styles.cardContainer, animatedStyle, style]}>
                {/* Background Decorations outside card? No, inside card looks cleaner */}
                <View style={styles.card}>
                    {/* Floating Background Elements */}
                    <View style={StyleSheet.absoluteFill} pointerEvents="none">
                        <FloatingMark delay={0} size={80} x={20} y={40} color="#FFCDD2" />
                        <FloatingMark delay={500} size={50} x={250} y={150} color="#EF9A9A" />
                    </View>

                    {/* Header */}
                    <View style={styles.cardHeader}>
                        <View style={styles.categoryBadge}>
                            <Text style={styles.categoryText}>{item.category || "雑学"}</Text>
                        </View>
                        {/* Circle Badge with ID or Icon */}
                        <View style={styles.idBadge}>
                            <Ionicons name="sparkles" size={16} color={Colors.light.primary} />
                        </View>
                    </View>

                    {/* Main Content */}
                    <View style={styles.contentContainer}>
                        <View style={styles.iconCircle}>
                            <Ionicons name="bulb" size={56} color={Colors.light.accent} />
                        </View>
                        <Text style={styles.title}>{item.title}</Text>
                        <View style={styles.bgStripe} />
                        <Text style={styles.content} numberOfLines={5}>
                            {item.content}
                        </Text>
                    </View>

                    {/* Footer Button */}
                    <Pressable style={styles.footerButton} onPress={onPressDetails}>
                        <Text style={styles.readMore}>くわしく見る！</Text>
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
        width: CARD_WIDTH,
        height: CARD_HEIGHT,
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
    cardHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: Theme.spacing.m,
        zIndex: 1,
    },
    categoryBadge: {
        backgroundColor: Colors.light.primary,
        paddingHorizontal: 16,
        paddingVertical: 8,
        borderRadius: 20,
    },
    categoryText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 14,
        letterSpacing: 1,
    },
    idBadge: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: '#FFF0F0',
        alignItems: 'center',
        justifyContent: 'center',
    },
    contentContainer: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        paddingVertical: Theme.spacing.m,
        zIndex: 1,
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
    title: {
        fontSize: 24,
        fontWeight: '900', // Heavy font
        color: Colors.light.text,
        textAlign: 'center',
        marginBottom: Theme.spacing.m,
        lineHeight: 32,
    },
    bgStripe: {
        width: '100%',
        height: 8,
        backgroundColor: '#F5F5F5',
        borderRadius: 4,
        marginBottom: Theme.spacing.m,
    },
    content: {
        fontSize: 16,
        color: Colors.light.subtext,
        textAlign: 'center',
        lineHeight: 26,
        fontWeight: '600',
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
    readMore: {
        fontSize: 16,
        color: Colors.light.primary,
        fontWeight: 'bold',
        marginRight: 8,
    },
    arrowCircle: {
        width: 24,
        height: 24,
        borderRadius: 12,
        backgroundColor: 'white',
        alignItems: 'center',
        justifyContent: 'center',
    }
});
