/** Great-circle polygon for the scan search radius (address at center). */
const EARTH_RADIUS_MILES = 3958.8;

export function scanRadiusPolygon(
  lat: number,
  lng: number,
  radiusMiles: number,
  steps = 96
): GeoJSON.Polygon {
  const ring: [number, number][] = [];
  const latRad = (lat * Math.PI) / 180;
  const angular = radiusMiles / EARTH_RADIUS_MILES;

  for (let i = 0; i <= steps; i++) {
    const bearing = (i / steps) * 2 * Math.PI;
    const sinLat = Math.sin(latRad);
    const cosLat = Math.cos(latRad);
    const sinAng = Math.sin(angular);
    const cosAng = Math.cos(angular);
    const outLat = Math.asin(sinLat * cosAng + cosLat * sinAng * Math.cos(bearing));
    const outLng =
      ((lng * Math.PI) / 180 +
        Math.atan2(
          Math.sin(bearing) * sinAng * cosLat,
          cosAng - sinLat * Math.sin(outLat)
        )) *
      (180 / Math.PI);
    ring.push([outLng, (outLat * 180) / Math.PI]);
  }

  return { type: "Polygon", coordinates: [ring] };
}

/** Lng/lat bounds that contain the full scan circle (for map fitBounds). */
export function scanRadiusBounds(
  lat: number,
  lng: number,
  radiusMiles: number
): [[number, number], [number, number]] {
  const ring = scanRadiusPolygon(lat, lng, radiusMiles).coordinates[0] ?? [];
  let minLng = lng;
  let maxLng = lng;
  let minLat = lat;
  let maxLat = lat;
  for (const [lo, la] of ring) {
    minLng = Math.min(minLng, lo);
    maxLng = Math.max(maxLng, lo);
    minLat = Math.min(minLat, la);
    maxLat = Math.max(maxLat, la);
  }
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ];
}
