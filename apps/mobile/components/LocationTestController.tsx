import { Ionicons } from '@expo/vector-icons';
import { useEffect, useMemo, useRef, useState } from 'react';
import { PanResponder, Pressable, StyleSheet, Text, View } from 'react-native';
import { Colors, Theme } from '../constants/Colors';

const JOYSTICK_RADIUS = 42;
const KNOB_RADIUS = 18;

type Props = {
    active: boolean;
    targetName: string;
    distanceMeters?: number;
    unlockRadiusMeters?: number;
    bottomOffset: number;
    speedMetersPerSecond: number;
    onActivate: () => void;
    onDeactivate: () => void;
    onMove: (eastMeters: number, northMeters: number) => void;
    onReset: () => void;
    onSpeedChange: (speed: number) => void;
};

const formatMeters = (meters?: number) => {
    if (meters == null) return '--';
    return meters >= 1000 ? `${(meters / 1000).toFixed(2)}km` : `${Math.round(meters)}m`;
};

export function LocationTestController({
    active,
    targetName,
    distanceMeters,
    unlockRadiusMeters,
    bottomOffset,
    speedMetersPerSecond,
    onActivate,
    onDeactivate,
    onMove,
    onReset,
    onSpeedChange,
}: Props) {
    const [stick, setStick] = useState({ x: 0, y: 0 });
    const stickRef = useRef(stick);
    const moveRef = useRef(onMove);
    const speedRef = useRef(speedMetersPerSecond);

    useEffect(() => {
        stickRef.current = stick;
    }, [stick]);

    useEffect(() => {
        moveRef.current = onMove;
    }, [onMove]);

    useEffect(() => {
        speedRef.current = speedMetersPerSecond;
    }, [speedMetersPerSecond]);

    useEffect(() => {
        if (!active) return;
        const timer = setInterval(() => {
            const current = stickRef.current;
            const strength = Math.min(1, Math.hypot(current.x, current.y) / JOYSTICK_RADIUS);
            if (strength < 0.08) return;

            const stepMeters = speedRef.current * 0.05 * strength;
            const magnitude = Math.hypot(current.x, current.y) || 1;
            moveRef.current(
                (current.x / magnitude) * stepMeters,
                (-current.y / magnitude) * stepMeters
            );
        }, 50);
        return () => clearInterval(timer);
    }, [active]);

    const panResponder = useMemo(() => PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderMove: (_, gesture) => {
            const magnitude = Math.hypot(gesture.dx, gesture.dy);
            const scale = magnitude > JOYSTICK_RADIUS ? JOYSTICK_RADIUS / magnitude : 1;
            setStick({ x: gesture.dx * scale, y: gesture.dy * scale });
        },
        onPanResponderRelease: () => setStick({ x: 0, y: 0 }),
        onPanResponderTerminate: () => setStick({ x: 0, y: 0 }),
    }), []);

    if (!active) {
        return (
            <Pressable style={[styles.startButton, { bottom: bottomOffset }]} onPress={onActivate}>
                <View style={styles.testBadge}><Text style={styles.testBadgeText}>TEST</Text></View>
                <Ionicons name="game-controller" size={18} color={Colors.light.primary} />
                <Text style={styles.startText}>仮想GPSを開始</Text>
            </Pressable>
        );
    }

    const isInside = distanceMeters != null && unlockRadiusMeters != null && distanceMeters <= unlockRadiusMeters;

    return (
        <View style={[styles.panel, { bottom: bottomOffset }]}>
            <View style={styles.panelHeader}>
                <View style={styles.headerCopy}>
                    <View style={styles.titleRow}>
                        <View style={styles.testBadge}><Text style={styles.testBadgeText}>TEST</Text></View>
                        <Text style={styles.title}>仮想GPS</Text>
                    </View>
                    <Text style={styles.target} numberOfLines={1}>{targetName}</Text>
                    <Text style={[styles.distance, isInside && styles.distanceInside]}>
                        {`距離 ${formatMeters(distanceMeters)} / 解放 ${formatMeters(unlockRadiusMeters)}`}
                    </Text>
                </View>
                <Pressable style={styles.realGpsButton} onPress={onDeactivate}>
                    <Ionicons name="navigate" size={16} color={Colors.light.primary} />
                    <Text style={styles.realGpsText}>実機GPS</Text>
                </Pressable>
            </View>

            <View style={styles.controlRow}>
                <View style={styles.speedBlock}>
                    <Text style={styles.speedLabel}>移動速度</Text>
                    {[10, 50, 200].map((speed) => (
                        <Pressable
                            key={speed}
                            style={[styles.speedButton, speedMetersPerSecond === speed && styles.speedButtonActive]}
                            onPress={() => onSpeedChange(speed)}
                        >
                            <Text style={[styles.speedText, speedMetersPerSecond === speed && styles.speedTextActive]}>
                                {speed === 10 ? '低速' : speed === 50 ? '標準' : '高速'}
                            </Text>
                        </Pressable>
                    ))}
                    <Pressable style={styles.resetButton} onPress={onReset}>
                        <Ionicons name="refresh" size={14} color={Colors.light.secondary} />
                        <Text style={styles.resetText}>位置・解放をリセット</Text>
                    </Pressable>
                </View>

                <View style={styles.joystick} {...panResponder.panHandlers}>
                    <View style={styles.axisVertical} />
                    <View style={styles.axisHorizontal} />
                    <View
                        style={[
                            styles.knob,
                            { transform: [{ translateX: stick.x }, { translateY: stick.y }] },
                        ]}
                    >
                        <Ionicons name="navigate" size={18} color="#FFFFFF" />
                    </View>
                </View>
            </View>
            <Text style={styles.note}>本番と同じ距離・解放判定を使用（バックグラウンド通知は実機GPSで確認）</Text>
        </View>
    );
}

const styles = StyleSheet.create({
    startButton: {
        position: 'absolute', left: 14, bottom: 14, minHeight: 42, borderRadius: 21,
        paddingHorizontal: 12, flexDirection: 'row', alignItems: 'center', gap: 7,
        backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: Colors.light.border,
        ...Theme.shadow.medium,
    },
    testBadge: { backgroundColor: '#252525', borderRadius: 5, paddingHorizontal: 6, paddingVertical: 3 },
    testBadgeText: { color: '#FFFFFF', fontSize: 9, fontWeight: '900', letterSpacing: 0.5 },
    startText: { color: Colors.light.primary, fontSize: 13, fontWeight: '900' },
    panel: {
        position: 'absolute', left: 12, right: 12, bottom: 12, borderRadius: 22,
        padding: 13, backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: Colors.light.border,
        ...Theme.shadow.medium,
    },
    panelHeader: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
    headerCopy: { flex: 1 },
    titleRow: { flexDirection: 'row', alignItems: 'center', gap: 7 },
    title: { fontSize: 16, fontWeight: '900', color: Colors.light.text },
    target: { marginTop: 4, fontSize: 12, fontWeight: '800', color: Colors.light.subtext },
    distance: { marginTop: 2, fontSize: 12, fontWeight: '900', color: Colors.light.secondary },
    distanceInside: { color: '#1A9B50' },
    realGpsButton: {
        minHeight: 34, borderRadius: 17, paddingHorizontal: 10, flexDirection: 'row',
        alignItems: 'center', gap: 4, backgroundColor: Colors.light.surface,
    },
    realGpsText: { fontSize: 11, fontWeight: '900', color: Colors.light.primary },
    controlRow: { marginTop: 9, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
    speedBlock: { flex: 1, flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6, paddingRight: 10 },
    speedLabel: { width: '100%', fontSize: 10, fontWeight: '800', color: Colors.light.subtext },
    speedButton: { height: 28, paddingHorizontal: 9, borderRadius: 14, backgroundColor: Colors.light.surface, justifyContent: 'center' },
    speedButtonActive: { backgroundColor: Colors.light.primary },
    speedText: { fontSize: 10, fontWeight: '900', color: Colors.light.subtext },
    speedTextActive: { color: '#FFFFFF' },
    resetButton: { marginTop: 2, width: '100%', flexDirection: 'row', alignItems: 'center', gap: 4 },
    resetText: { fontSize: 10, fontWeight: '900', color: Colors.light.secondary },
    joystick: {
        width: JOYSTICK_RADIUS * 2, height: JOYSTICK_RADIUS * 2, borderRadius: JOYSTICK_RADIUS,
        backgroundColor: '#F1F3F4', borderWidth: 2, borderColor: '#D9DDE0',
        alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
    },
    axisVertical: { position: 'absolute', width: 1, height: '100%', backgroundColor: '#D9DDE0' },
    axisHorizontal: { position: 'absolute', height: 1, width: '100%', backgroundColor: '#D9DDE0' },
    knob: {
        width: KNOB_RADIUS * 2, height: KNOB_RADIUS * 2, borderRadius: KNOB_RADIUS,
        backgroundColor: Colors.light.primary, alignItems: 'center', justifyContent: 'center',
    },
    note: { marginTop: 7, fontSize: 9, lineHeight: 12, fontWeight: '700', color: Colors.light.subtext },
});
