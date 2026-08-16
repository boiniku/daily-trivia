import * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';
import { TRIVIA_GEOFENCE_TASK, TriviaGeofenceManager } from '../managers/TriviaGeofenceManager';

type TriviaGeofenceTaskData = {
    eventType: Location.GeofencingEventType;
    region: Location.LocationRegion;
};

try {
    TaskManager.defineTask<TriviaGeofenceTaskData>(TRIVIA_GEOFENCE_TASK, async ({ data, error }) => {
        if (error) {
            console.error('[TriviaGeofence] Background event failed:', error);
            return;
        }
        if (!data) return;

        try {
            await TriviaGeofenceManager.handleEvent(data.eventType, data.region);
        } catch (eventError) {
            console.error('[TriviaGeofence] Event handling failed:', eventError);
        }
    });
} catch (error) {
    console.warn('[TriviaGeofence] Failed to define task:', error);
}
