
import React from 'react';
import { Modal, View, Text, StyleSheet, Pressable, Platform, Alert } from 'react-native';
import { AppleAuthenticationButton, AppleAuthenticationButtonType, AppleAuthenticationButtonStyle } from 'expo-apple-authentication';
import { Ionicons } from '@expo/vector-icons';
import { Colors, Theme } from '../constants/Colors';
import { useAuth } from '../contexts/AuthContext';

interface LoginModalProps {
    visible: boolean;
    onClose: () => void;
}

export default function LoginModal({ visible, onClose }: LoginModalProps) {
    const { signInWithApple, loading } = useAuth();

    const handleAppleLogin = async () => {
        try {
            await signInWithApple();
            onClose();
            Alert.alert("成功", "ログインしました。データは自動的に引き継がれます。");
        } catch (e) {
            // Error handled in context
        }
    };

    return (
        <Modal
            animationType="slide"
            transparent={true}
            visible={visible}
            onRequestClose={onClose}
        >
            <View style={styles.centeredView}>
                <View style={styles.modalView}>
                    <Pressable style={styles.closeButton} onPress={onClose}>
                        <Ionicons name="close" size={24} color={Colors.light.subtext} />
                    </Pressable>

                    <Text style={styles.modalTitle}>ログイン / 新規登録</Text>
                    <Text style={styles.modalSubtitle}>
                        アカウントを連携すると、機種変更時もデータを引き継ぐことができます。今のデータはそのまま維持されます。
                    </Text>

                    {Platform.OS === 'ios' && (
                        <AppleAuthenticationButton
                            buttonType={AppleAuthenticationButtonType.SIGN_IN}
                            buttonStyle={AppleAuthenticationButtonStyle.BLACK}
                            cornerRadius={50} // match app style
                            style={styles.appleButton}
                            onPress={handleAppleLogin}
                        />
                    )}

                    {/* Placeholder for Google Login (Future) */}
                    {/* 
                    <Pressable style={styles.googleButton}>
                        <Text>Sign in with Google</Text>
                    </Pressable>
                    */}
                </View>
            </View>
        </Modal>
    );
}

const styles = StyleSheet.create({
    centeredView: {
        flex: 1,
        justifyContent: 'flex-end', // Bottom sheet style
        backgroundColor: 'rgba(0,0,0,0.5)',
    },
    modalView: {
        backgroundColor: 'white',
        borderTopLeftRadius: Theme.borderRadius.l,
        borderTopRightRadius: Theme.borderRadius.l,
        padding: 30,
        alignItems: 'center',
        shadowColor: '#000',
        shadowOffset: {
            width: 0,
            height: -2,
        },
        shadowOpacity: 0.25,
        shadowRadius: 4,
        elevation: 5,
        paddingBottom: 50, // Safe area
    },
    closeButton: {
        position: 'absolute',
        right: 20,
        top: 20,
        padding: 5,
    },
    modalTitle: {
        fontSize: 20,
        fontWeight: 'bold',
        marginBottom: 10,
        color: Colors.light.text,
    },
    modalSubtitle: {
        fontSize: 14,
        color: Colors.light.subtext,
        textAlign: 'center',
        marginBottom: 30,
        lineHeight: 20,
    },
    appleButton: {
        width: '100%',
        height: 50,
        marginBottom: 10,
    },
});
