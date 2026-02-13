import { ActionSheetProvider } from '@expo/react-native-action-sheet';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { View } from 'react-native';
import { RevenueCatProvider } from '../contexts/RevenueCatContext';
import { AuthProvider } from '../contexts/AuthContext';
// TEMP: Disabled for minimal build test
import mobileAds from 'react-native-google-mobile-ads';

export default function RootLayout() {

  useEffect(() => {
    // TEMP: Disabled for minimal build test
    mobileAds()
      .initialize()
      .then(adapterStatuses => {
        // Initialization complete!
      })
      .catch(error => {
        console.error('AdMob init error:', error);
      });
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <ActionSheetProvider>
        <RevenueCatProvider>
          <AuthProvider>
            <View style={{ flex: 1 }}>
              <Stack screenOptions={{ headerShown: false }}>
                <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
                <Stack.Screen name="details" options={{ presentation: 'modal', headerShown: false }} />
              </Stack>
              <StatusBar style="auto" />
            </View>
          </AuthProvider>
        </RevenueCatProvider>
      </ActionSheetProvider>
    </GestureHandlerRootView>
  );
}
