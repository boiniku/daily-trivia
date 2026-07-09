import { TriviaSpot } from '../models/TriviaSpot';
import { getBackendUrl } from '../constants/Config';
import { fetchWithToken } from '../utils/apiClient';

const initialTriviaSpots: TriviaSpot[] = [];

export const getTriviaSpots = async (): Promise<TriviaSpot[]> => {
    try {
        const response = await fetchWithToken(`${getBackendUrl()}/trivia/map`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const remoteSpots = await response.json() as TriviaSpot[];
        return remoteSpots.map((spot) => ({
            ...spot,
            isUnlocked: false,
            unlockedAt: null,
        }));
    } catch (error) {
        console.warn('Falling back to bundled trivia spots:', error);
        return initialTriviaSpots.map((spot) => ({ ...spot }));
    }
};
