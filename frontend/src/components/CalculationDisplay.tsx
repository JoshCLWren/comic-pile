import type { CreatorMetricCalculation } from '../types/index'

interface CalculationDisplayProps {
  calculation: CreatorMetricCalculation
}

export function CalculationDisplay({ calculation }: CalculationDisplayProps) {
  return (
    <div className="surface-panel rounded-xl p-4 border" style={{ borderColor: 'var(--theme-border)' }}>
      <h3 className="text-sm font-semibold mb-3 uppercase tracking-wide" style={{ color: 'var(--theme-text-dim)' }}>
        Calculation
      </h3>
      <div className="space-y-2">
        <div className="text-sm font-mono" style={{ color: 'var(--theme-text-primary)' }}>
          {calculation.formula.split('\n').map((line, index) => (
            <div key={index}>{line}</div>
          ))}
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
          {calculation.numerator && (
            <div className="text-center">
              <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--theme-text-muted)' }}>
                Numerator
              </div>
              <div className="text-sm font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
                {calculation.numerator}
              </div>
            </div>
          )}
          
          {calculation.denominator && (
            <div className="text-center">
              <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--theme-text-muted)' }}>
                Denominator
              </div>
              <div className="text-sm font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
                {calculation.denominator}
              </div>
            </div>
          )}
          
          {calculation.percentage && (
            <div className="text-center">
              <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--theme-text-muted)' }}>
                Result
              </div>
              <div 
                className="text-lg font-bold"
                style={{ color: 'var(--theme-personal-accent)' }}
              >
                {calculation.percentage}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}