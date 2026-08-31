/* Plan-view silhouettes, one per object class.
 *
 * ⛔ WHAT THE INSERT ACTUALLY KNOWS IS A POSITION AND A CLASS. It does not know
 * an outline: there is no camera looking down, and the taxel sheet measures
 * pressure at 96 sites, not a shape. So these are ICONS drawn at a measured
 * point, not silhouettes traced from a sensor, and the caption under the map
 * says so. Drawing something that looks like an X-ray without saying which part
 * of it is measured would be the most dishonest thing in this repository.
 *
 * ⭐ WHY DRAW THEM AT ALL. The first map was three rectangles and six dots, and a
 * dot cannot answer the only question anyone asks a bag — "is my wallet in
 * there" — any faster than the list beside it already does. A shape at a place
 * is read in one glance; a dot with a name has to be read twice.
 *
 * ⛔ AND THE SECOND MAP WAS A PLAN VIEW, WHICH WAS ALSO WRONG. Looking straight
 * down at a 225 x 78 mm floor is the view the sensors have and the worst one a
 * person can be given: nobody recognises their own bag from above, and objects
 * that stand upright in it appear as thin slivers. This draws the bag from the
 * FRONT, the way it is seen while it is being opened, with its contents standing
 * on the sensing floor — which is also how they really sit, because the insert
 * is 78 mm deep and everything in it stands.
 *
 * ⚠️ THE FOOTPRINTS ARE REAL, THE OUTLINES ARE NOT. Each box below is the plan
 * area that object type actually occupies in a 225 x 78 mm insert, so a wallet
 * covers a third of a compartment and a lipstick does not. That is the part
 * worth being right about: it is what makes the map legible as a bag rather
 * than as a chart with pictures on it.
 */

/* Plan footprint, [width, depth] mm — what an object occupies on the FLOOR.
 * The simulator uses it to keep two objects out of the same place. */
export const FOOTPRINT = {
  unknown: [40, 30], wallet: [95, 22], phone: [72, 13], keys: [46, 24],
  pouch: [100, 38], cosmetic: [22, 22], glasses: [112, 34],
  earbuds: [52, 28], card: [85, 8], bottle: [58, 58],
};

/* Front elevation, [width, height] mm — what is drawn, standing on the floor.
 * ⚠️ The insert's wall is 150 mm, so nothing here is taller than that: a phone
 * at 146 mm just clears it, which is true of the object and of the bag. */
export const FRONT = {
  unknown: [50, 60], wallet: [95, 88], phone: [72, 146], keys: [46, 68],
  pouch: [100, 72], cosmetic: [22, 74], glasses: [112, 40],
  earbuds: [52, 54], card: [85, 54], bottle: [58, 132],
};

/* Each icon draws into a box of the given width/height, centred on (0, 0).
 * Stroke and fill come from the map, so nothing here picks a colour. */
const DRAW = {
  wallet: (w, h) => `
    <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${h * 0.10}"/>
    <line x1="${-w / 2}" y1="${-h * 0.06}" x2="${w / 2}" y2="${-h * 0.06}"/>
    <rect x="${-w * 0.34}" y="${h * 0.06}" width="${w * 0.30}" height="${h * 0.26}"
          rx="${h * 0.04}"/>
    <circle cx="${w * 0.30}" cy="${h * 0.14}" r="${h * 0.07}"/>`,
  phone: (w, h) => `
    <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${w * 0.16}"/>
    <rect x="${-w * 0.40}" y="${-h * 0.42}" width="${w * 0.80}" height="${h * 0.84}"
          rx="${w * 0.10}"/>
    <circle cx="${-w * 0.22}" cy="${-h * 0.36}" r="${w * 0.07}"/>
    <circle cx="${-w * 0.22}" cy="${-h * 0.24}" r="${w * 0.07}"/>`,
  keys: (w, h) => `
    <circle cx="0" cy="${-h * 0.34}" r="${h * 0.15}"/>
    <path d="M ${-w * 0.10} ${-h * 0.20} L ${-w * 0.30} ${h * 0.30}
             l ${w * 0.10} 0 l 0 ${h * 0.10} l ${-w * 0.08} 0" fill="none"/>
    <path d="M ${w * 0.06} ${-h * 0.20} L ${w * 0.22} ${h * 0.36}
             l ${-w * 0.10} 0 l 0 ${h * 0.10}" fill="none"/>
    <path d="M ${-w * 0.02} ${-h * 0.20} L ${w * 0.00} ${h * 0.44}" fill="none"/>`,
  pouch: (w, h) => `
    <path d="M ${-w * 0.44} ${-h / 2} h ${w * 0.88}
             a ${h * 0.16} ${h * 0.16} 0 0 1 ${w * 0.06} ${h * 0.16}
             v ${h * 0.68} a ${h * 0.16} ${h * 0.16} 0 0 1 ${-w * 0.06} ${h * 0.16}
             h ${-w * 0.88} a ${h * 0.16} ${h * 0.16} 0 0 1 ${-w * 0.06} ${-h * 0.16}
             v ${-h * 0.68} a ${h * 0.16} ${h * 0.16} 0 0 1 ${w * 0.06} ${-h * 0.16} z"/>
    <line x1="${-w * 0.44}" y1="${-h * 0.30}" x2="${w * 0.44}" y2="${-h * 0.30}"/>
    <circle cx="${w * 0.30}" cy="${-h * 0.30}" r="${h * 0.06}"/>`,
  cosmetic: (w, h) => `
    <rect x="${-w * 0.36}" y="${-h * 0.46}" width="${w * 0.72}" height="${h * 0.40}"
          rx="${w * 0.30}"/>
    <rect x="${-w * 0.40}" y="${-h * 0.10}" width="${w * 0.80}" height="${h * 0.56}"
          rx="${w * 0.16}"/>`,
  glasses: (w, h) => `
    <circle cx="${-w * 0.27}" cy="0" r="${h * 0.36}"/>
    <circle cx="${w * 0.27}" cy="0" r="${h * 0.36}"/>
    <path d="M ${-w * 0.27 + h * 0.36} 0 q ${w * 0.06} ${-h * 0.22} ${w * 0.12} 0"
          fill="none"/>
    <path d="M ${-w * 0.27 - h * 0.36} ${-h * 0.06} L ${-w * 0.50} ${h * 0.26}"
          fill="none"/>
    <path d="M ${w * 0.27 + h * 0.36} ${-h * 0.06} L ${w * 0.50} ${h * 0.26}"
          fill="none"/>`,
  earbuds: (w, h) => `
    <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${h * 0.30}"/>
    <line x1="${-w * 0.44}" y1="${-h * 0.10}" x2="${w * 0.44}" y2="${-h * 0.10}"/>
    <circle cx="${-w * 0.18}" cy="${h * 0.16}" r="${h * 0.13}"/>
    <circle cx="${w * 0.18}" cy="${h * 0.16}" r="${h * 0.13}"/>`,
  card: (w, h) => `
    <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${h * 0.10}"/>
    <rect x="${-w * 0.42}" y="${-h * 0.30}" width="${w * 0.84}" height="${h * 0.14}"/>
    <rect x="${-w * 0.36}" y="${h * 0.04}" width="${w * 0.22}" height="${h * 0.20}"
          rx="${h * 0.04}"/>`,
  bottle: (w, h) => `
    <path d="M ${-w * 0.16} ${-h / 2} h ${w * 0.32} v ${h * 0.10}
             q 0 ${h * 0.06} ${w * 0.14} ${h * 0.10}
             q ${w * 0.20} ${h * 0.06} ${w * 0.20} ${h * 0.22}
             v ${h * 0.42} a ${w * 0.14} ${w * 0.14} 0 0 1 ${-w * 0.14} ${w * 0.14}
             h ${-w * 0.72} a ${w * 0.14} ${w * 0.14} 0 0 1 ${-w * 0.14} ${-w * 0.14}
             v ${-h * 0.42} q 0 ${-h * 0.16} ${w * 0.20} ${-h * 0.22}
             q ${w * 0.14} ${-h * 0.04} ${w * 0.14} ${-h * 0.10} z"/>`,
  unknown: (w, h) => `
    <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${h * 0.1}"
          stroke-dasharray="4 3"/>`,
};

/* `x` is the centre and `floor` is where the object stands: shapes sit ON the
 * sensing floor rather than floating at a point, because that is what they do. */
/* Returns the shape with its BASE at y = 0, so the caller can stand it on a
 * floor by translating to that floor and nothing else. */
export function silhouette(className) {
  const [w, h] = FRONT[className] || FRONT.unknown;
  const draw = DRAW[className] || DRAW.unknown;
  return { w, h, markup: `<g transform="translate(0 ${-h / 2})">${draw(w, h)}</g>` };
}
