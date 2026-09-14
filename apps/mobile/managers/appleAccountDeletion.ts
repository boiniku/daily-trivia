import { AppleAuthProvider, getAuth, reauthenticateWithCredential } from '@react-native-firebase/auth';
import * as AppleAuthentication from 'expo-apple-authentication';
import * as Crypto from 'expo-crypto';

/** Verify the current Apple identity and revoke its authorization before deletion. */
export async function authorizeAppleDeletion(expectedUid: string) {
    const auth = getAuth();
    const user = auth.currentUser;
    if (!user || user.uid !== expectedUid) throw new Error('削除するアカウントを再確認してください。');
    if (user.isAnonymous) return;
    const subject = user.providerData.find(provider => provider.providerId === 'apple.com')?.uid;
    if (!subject) throw new Error('Appleアカウントを確認できません。');
    const nonce = Crypto.randomUUID();
    const state = Crypto.randomUUID();
    const result = await AppleAuthentication.signInAsync({
        state, nonce: await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, nonce),
    });
    if (result.state !== state || result.user !== subject || !result.identityToken) {
        throw new Error('ログイン中のAppleアカウントと一致しません。データは削除していません。');
    }
    if (auth.currentUser?.uid !== expectedUid) throw new Error('アカウントが切り替わりました。');
    await reauthenticateWithCredential(user, AppleAuthProvider.credential(result.identityToken, nonce));
    if (result.authorizationCode) {
        // Installed RNFirebase 23.8 exposes revokeToken only on this instance API.
        await auth.revokeToken(result.authorizationCode);
    }
}
