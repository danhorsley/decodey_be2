```typescript
interface GameState {
  game_id: string | null;
  mistakes: number;
  completed: boolean;
  remaining_attempts: number;
  active: boolean;
}

interface GameWon {
  game_id: string;
  score: number;
  mistakes: number;
  time_taken: number;
}

type SSEEventCallback = (data: any) => void;

class SSEService {
  private eventSource: EventSource | null = null;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private maxReconnectDelay = 30000; // Maximum reconnect delay of 30 seconds
  private currentReconnectDelay = 1000; // Start with 1 second delay
  private eventCallbacks: Map<string, SSEEventCallback[]> = new Map();

  constructor() {
    // Initialize event callback arrays
    this.eventCallbacks.set('connected', []);
    this.eventCallbacks.set('gameState', []);
    this.eventCallbacks.set('gameWon', []);
    this.eventCallbacks.set('error', []);
  }

  connect() {
    if (this.eventSource) {
      this.disconnect();
    }

    const token = localStorage.getItem('token');
    if (!token) {
      console.error('No authentication token available');
      return;
    }

    try {
      this.eventSource = new EventSource('/events', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      // Handle connection opened
      this.eventSource.onopen = () => {
        console.log('SSE connection established');
        this.currentReconnectDelay = 1000; // Reset reconnect delay on successful connection
      };

      // Handle specific events
      this.eventSource.addEventListener('connected', (event) => {
        const data = JSON.parse(event.data);
        this.notifyCallbacks('connected', data);
      });

      this.eventSource.addEventListener('gameState', (event) => {
        const data = JSON.parse(event.data) as GameState;
        this.notifyCallbacks('gameState', data);
      });

      this.eventSource.addEventListener('gameWon', (event) => {
        const data = JSON.parse(event.data) as GameWon;
        this.notifyCallbacks('gameWon', data);
      });

      this.eventSource.addEventListener('error', (event) => {
        const data = event.data ? JSON.parse(event.data) : { message: 'Connection error' };
        this.notifyCallbacks('error', data);
        this.handleError();
      });

    } catch (error) {
      console.error('Error creating SSE connection:', error);
      this.handleError();
    }
  }

  private handleError() {
    this.disconnect();
    
    // Implement exponential backoff for reconnection
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }

    this.reconnectTimeout = setTimeout(() => {
      console.log(`Attempting to reconnect in ${this.currentReconnectDelay/1000} seconds`);
      this.connect();
      // Increase reconnect delay for next attempt (exponential backoff)
      this.currentReconnectDelay = Math.min(this.currentReconnectDelay * 2, this.maxReconnectDelay);
    }, this.currentReconnectDelay);
  }

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
  }

  // Subscribe to specific events
  on(event: 'connected' | 'gameState' | 'gameWon' | 'error', callback: SSEEventCallback) {
    const callbacks = this.eventCallbacks.get(event) || [];
    callbacks.push(callback);
    this.eventCallbacks.set(event, callbacks);
  }

  // Unsubscribe from specific events
  off(event: 'connected' | 'gameState' | 'gameWon' | 'error', callback: SSEEventCallback) {
    const callbacks = this.eventCallbacks.get(event) || [];
    const index = callbacks.indexOf(callback);
    if (index !== -1) {
      callbacks.splice(index, 1);
      this.eventCallbacks.set(event, callbacks);
    }
  }

  private notifyCallbacks(event: string, data: any) {
    const callbacks = this.eventCallbacks.get(event) || [];
    callbacks.forEach(callback => callback(data));
  }
}

// Create a singleton instance
const sseService = new SSEService();
export default sseService;
```
