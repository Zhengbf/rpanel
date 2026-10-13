/** RPanel Logo：圆环 + 信号脉冲折线，currentColor */
export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <circle cx="16" cy="16" r="13" stroke="currentColor" strokeWidth="2.4" />
      <path d="M7 17 L11 17 L13.5 11 L16.5 21 L19 15.5 L20.5 17 L25 17"
        stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  )
}
