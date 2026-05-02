import { ActionSheetProvider } from '@expo/react-native-action-sheet';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { InteractionManager, View } from 'react-native';
import { RevenueCatProvider } from '../contexts/RevenueCatContext';
import { AuthProvider } from '../contexts/AuthContext';

import { registerBackgroundFetchAsync } from '../tasks/backgroundFetch';

export default function RootLayout() {

  useEffect(() => {
    // Register background fetch
    registerBackgroundFetchAsync().catch(err => console.error("BG Register Error:", err));

    const task = InteractionManager.runAfterInteractions(() => {
      setTimeout(() => {
        import('react-native-google-mobile-ads')
          .then(({ default: mobileAds }) => mobileAds().initialize())
          .catch(error => {
            console.error('AdMob init error:', error);
          });
      }, 1500);
    });

    return () => task.cancel();
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
                <Stack.Screen name="widget-setup" options={{ presentation: 'modal', headerShown: false }} />
              </Stack>
              <StatusBar style="auto" />
            </View>
          </AuthProvider>
        </RevenueCatProvider>
      </ActionSheetProvider>
    </GestureHandlerRootView>
  );
}
