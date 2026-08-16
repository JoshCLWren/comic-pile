import React from 'react';

interface RatingThread {
  id: number;
  title: string;
  format: string;
  rating: number;
}

const RatingView: React.FC<{ activeRatingThread: RatingThread, currentDie: number, rolledResult: number }> = ({ activeRatingThread, currentDie, rolledResult }) => {
  // Implementation here
  return <div></div>;
};

export default RatingView;