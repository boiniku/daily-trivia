import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Pressable, Animated, Easing, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors, Theme } from '../constants/Colors';
import { Config } from '../constants/Config';
import { useAuth } from '../contexts/AuthContext';
import * as Haptics from 'expo-haptics';
import { fetchWithToken } from '../utils/apiClient';

interface HeeButtonProps {
    triviaId: number;
    initialTotalCount?: number;
    onHeeAdded?: (count: number) => void;
}

export default function HeeButton({ triviaId, initialTotalCount = 0, onHeeAdded }: HeeButtonProps) {
    const [totalCount, setTotalCount] = useState(initialTotalCount);
    const [userCount, setUserCount] = useState(0);
    const [loading, setLoading] = useState(true);
    const { userId } = useAuth();
    const scaleAnim = useRef(new Animated.Value(1)).current;

    // For batching requests
    const pendingClicks = useRef(0);
    const timeoutRef = useRef<NodeJS.Timeout | null>(null);

    useEffect(() => {
        if (userId) {
            fetchStatus();
        }
    }, [triviaId, userId]);

    const fetchStatus = async () => {
        try {
            if (!userId) return;

            const response = await fetchWithToken(`${Config.BACKEND_URL}/trivia/${triviaId}/hee`);
            if (response.ok) {
                const data = await response.json();
                setTotalCount(data.total_count);
                setUserCount(data.user_count);
            }
        } catch (e) {
            console.error("Failed to fetch Hee status", e);
        } finally {
            setLoading(false);
        }
    };

    const handlePress = async () => {
        if (userCount >= 10) {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
            return;
        }

        // Optimistic update
        setUserCount(prev => prev + 1);
        setTotalCount(prev => prev + 1);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

        // Animation
        Animated.sequence([
            Animated.timing(scaleAnim, {
                toValue: 1.2,
                duration: 100,
                easing: Easing.out(Easing.quad),
                useNativeDriver: true
            }),
            Animated.timing(scaleAnim, {
                toValue: 1,
                duration: 100,
                easing: Easing.out(Easing.quad),
                useNativeDriver: true
            })
        ]).start();

        // Batch API calls
        pendingClicks.current += 1;

        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
        }

        timeoutRef.current = setTimeout(() => {
            sendHee(pendingClicks.current);
            pendingClicks.current = 0;
        }, 1000); // Send after 1 second of inactivity
    };

    const sendHee = async (count: number) => {
        try {
            if (!userId) return;

            const response = await fetchWithToken(`${Config.BACKEND_URL}/trivia/${triviaId}/hee`, {
                method: 'POST',
                body: JSON.stringify({ count: count })
            });

            if (response.ok) {
                const data = await response.json();
                // Sync with server source of truth
                if (data.total_count !== -1) {
                    setTotalCount(data.total_count);
                }
                setUserCount(data.user_count);
                console.log("Hee sent!", data);
            }
        } catch (e) {
            console.error("Failed to send Hee", e);
            // Revert on error? Maybe too complex for now, just log it.
        }
    };

    const isMaxed = userCount >= 10;

    return (
        <View style={styles.container}>
            {loading ? (
                <View style={styles.totalCountLoader}>
                    <ActivityIndicator size="small" color={Colors.light.text} />
                </View>
            ) : (
                <Text style={styles.totalCount}>{totalCount} へぇ</Text>
            )}

            <Pressable
                onPress={handlePress}
                disabled={isMaxed || loading}
                style={({ pressed }) => [
                    styles.button,
                    isMaxed && styles.buttonDisabled,
                    pressed && !isMaxed && { opacity: 0.8 }
                ]}
            >
                <Animated.View style={{ transform: [{ scale: scaleAnim }] }}>
                    <Ionicons
                        name={isMaxed ? "checkmark-circle" : "hand-left"}
                        size={20}
                        color="white"
                    />
                </Animated.View>
                <Text style={styles.buttonText}>
                    {isMaxed ? "MAX" : `へぇ (${10 - userCount})`}
                </Text>
            </Pressable>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        alignItems: 'center',
        marginVertical: 10, // Reduced from 20
    },
    totalCount: {
        fontSize: 14, // Reduced from 24
        fontWeight: '900',
        color: Colors.light.text,
        marginBottom: 4, // Reduced from 10
    },
    totalCountLoader: {
        height: 20,
        minWidth: 56,
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 4,
    },
    button: {
        backgroundColor: Colors.light.primary,
        paddingVertical: 8, // Reduced from 12
        paddingHorizontal: 20, // Reduced from 30
        borderRadius: 50,
        flexDirection: 'row',
        alignItems: 'center',
        ...Theme.shadow.small, // Reduced shadow
        borderWidth: 2,
        borderColor: 'white'
    },
    buttonDisabled: {
        backgroundColor: Colors.light.subtext,
        ...Theme.shadow.small,
    },
    buttonText: {
        color: 'white',
        fontWeight: 'bold',
        fontSize: 14, // Reduced from 18
        marginLeft: 6, // Reduced from 8
    }
});
