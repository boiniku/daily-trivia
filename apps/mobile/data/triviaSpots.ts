import { TriviaSpot } from '../models/TriviaSpot';
import { getBackendUrl } from '../constants/Config';
import { fetchWithToken } from '../utils/apiClient';
import { TriviaSpotCache } from '../managers/TriviaSpotCache';

const initialTriviaSpots: TriviaSpot[] = [];

export const getTriviaSpots = async (): Promise<TriviaSpot[]> => {
    try {
        const response = await fetchWithToken(`${getBackendUrl()}/trivia/map`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const remoteSpots = await response.json() as TriviaSpot[];
        const spots = remoteSpots.map((spot) => ({
            ...spot,
            isUnlocked: false,
            unlockedAt: null,
        }));
        await TriviaSpotCache.save(spots);
        return spots;
    } catch (error) {
        console.warn('Falling back to bundled trivia spots:', error);
        const cachedSpots = await TriviaSpotCache.read();
        if (cachedSpots.length > 0) return cachedSpots;
        return initialTriviaSpots.map((spot) => ({ ...spot }));
    }
};
