```typescript
import React, { useEffect } from 'react';
import sseService from '../services/SSEService';

export function Game() {
  useEffect(() => {
    // Setup SSE event handlers
    const handleGameState = (state: GameState) => {
      console.log('Game state updated:', state);
      // Update your game state here
    };

    const handleGameWon = (data: GameWon) => {
      console.log('Game won:', data);
      // Handle win condition
    };

    const handleError = (error: any) => {
      console.error('SSE error:', error);
      // Handle error (show notification, etc)
    };

    // Subscribe to events
    sseService.on('gameState', handleGameState);
    sseService.on('gameWon', handleGameWon);
    sseService.on('error', handleError);

    // Connect to SSE
    sseService.connect();

    // Cleanup on component unmount
    return () => {
      sseService.off('gameState', handleGameState);
      sseService.off('gameWon', handleGameWon);
      sseService.off('error', handleError);
      sseService.disconnect();
    };
  }, []); // Empty dependency array means this effect runs once on mount

  return (
    <div>
      {/* Your game UI components */}
    </div>
  );
}
```
