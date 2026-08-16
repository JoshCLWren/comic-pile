import React, { useState, useEffect } from 'react';

interface RateProps {
  issuesRemaining: number;
  onSubmit: () => void;
}

const Rate: React.FC<RateProps> = ({ issuesRemaining, onSubmit }) => {
  const [buttonText, setButtonText] = useState('Save & Continue');

  useEffect(() => {
    if (issuesRemaining === 1) {
      setButtonText('Save & Complete');
    }
  }, [issuesRemaining]);

  return (
    <button onClick={onSubmit}>{buttonText}</button>
  );
};

export default Rate;