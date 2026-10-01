export type Point = readonly [number, number]
export type Polyline = readonly Point[]
export type Curve = readonly [Point, Point, Point]

const clamp = (value: number) => Math.min(1, Math.max(0, value))

export function pointOnPolyline(points: Polyline, f: number): Point {
  if (points.length === 1) {
    return points[0]
  }
  const lengths: number[] = []
  let total = 0
  for (let i = 1; i < points.length; i++) {
    const length = Math.hypot(
      points[i][0] - points[i - 1][0],
      points[i][1] - points[i - 1][1]
    )
    lengths.push(length)
    total += length
  }
  let left = clamp(f) * total
  for (let i = 0; i < lengths.length; i++) {
    if (left <= lengths[i] || i === lengths.length - 1) {
      const r = lengths[i] > 0 ? Math.min(1, left / lengths[i]) : 1
      return [
        points[i][0] + (points[i + 1][0] - points[i][0]) * r,
        points[i][1] + (points[i + 1][1] - points[i][1]) * r,
      ]
    }
    left -= lengths[i]
  }
  return points[points.length - 1]
}

export function pointOnCurve(curve: Curve, f: number): Point {
  const t = clamp(f)
  const u = 1 - t
  const [a, c, b] = curve
  return [
    u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
    u * u * a[1] + 2 * u * t * c[1] + t * t * b[1],
  ]
}

export function wireBetween(from: Point, to: Point): Curve {
  const control: Point = [
    from[0] + (to[0] - from[0]) * 0.55,
    from[1] + (to[1] - from[1]) * 0.15,
  ]
  return [from, control, to]
}

export function curvePath([a, c, b]: Curve): string {
  return `M${a[0]} ${a[1]} Q${c[0]} ${c[1]} ${b[0]} ${b[1]}`
}

export function ease(f: number): number {
  const t = clamp(f)
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2
}
