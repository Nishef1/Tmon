/** A small price line rebased to its first value. Green when it ended above where it began. */
export function Spark({
  values,
  width = 120,
  height = 36,
  label,
}: {
  values: number[];
  width?: number;
  height?: number;
  label?: string;
}) {
  if (values.length < 2) {
    return <span className="spark-none" style={{ width, height }} aria-hidden />;
  }
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pad = 2;
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - 2 * pad);
  const y = (v: number) => height - pad - ((v - lo) / span) * (height - 2 * pad);
  const line = values
    .map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
    .join("");
  const area = `${line}L${x(values.length - 1).toFixed(1)} ${height}L${x(0).toFixed(1)} ${height}Z`;
  const up = values[values.length - 1] >= values[0];
  const c = up ? "var(--up)" : "var(--down)";
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className="spark"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      preserveAspectRatio="none"
    >
      <path d={area} fill={c} opacity={0.12} />
      <path
        d={line}
        fill="none"
        stroke={c}
        strokeWidth={1.6}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r={2.2} fill={c} />
    </svg>
  );
}

/** Up, flat and down counts as one bar. */
export function BreadthBar({
  up,
  flat,
  down,
  label,
}: {
  up: number;
  flat: number;
  down: number;
  label: string;
}) {
  const n = up + flat + down || 1;
  return (
    <div className="ms-bar" role="img" aria-label={label}>
      <span className="bg-up" style={{ width: `${(up / n) * 100}%` }} />
      <span className="bg-line" style={{ width: `${(flat / n) * 100}%` }} />
      <span className="bg-down" style={{ width: `${(down / n) * 100}%` }} />
    </div>
  );
}
