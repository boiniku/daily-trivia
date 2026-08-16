import AsyncStorage from '@react-native-async-storage/async-storage';
import { TriviaSpot } from '../models/TriviaSpot';

const STORAGE_KEY = 'triviaMapSpotCacheV1';

type CachedTriviaSpot = Omit<TriviaSpot, 'unlockedAt'> & {
    unlockedAt: string | null;
};

export const TriviaSpotCache = {
    async save(spots: TriviaSpot[]) {
        const cached: CachedTriviaSpot[] = spots.map((spot) => ({
            ...spot,
            unlockedAt: spot.unlockedAt?.toISOString() ?? null,
        }));
        await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(cached));
    },

    async read(): Promise<TriviaSpot[]> {
        const json = await AsyncStorage.getItem(STORAGE_KEY);
        if (!json) return [];

        try {
            const cached = JSON.parse(json) as CachedTriviaSpot[];
            if (!Array.isArray(cached)) return [];

            return cached.map((spot) => ({
                ...spot,
                unlockedAt: spot.unlockedAt ? new Date(spot.unlockedAt) : null,
            }));
        } catch {
            return [];
        }
    },
};
