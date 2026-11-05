// world-index.wscript - reads every streaming sector of the loaded game into NDJSON for build.py.
//
// The sector list comes from the game's three streaming blocks (Night City, Phantom Liberty, the main menu world),
// plus every sector in the game archives that no block lists: the game never streams those, and each descriptor
// says which block lists it (block null for none). Interior sectors with LOD suffixes other than _0 are included. Each sector goes through wkit.WorldIndexSector (a custom host build
// that has it), which reads 2.31 and 2.5 sectors into the same shape. Output, under the dump directory's
// wscript\raw\world-index\<GAME>\:
//   sectors.json        every descriptor: path, block, category, level, streaming box, variants, quest prefab
//   part-<NN>.ndjson     one line per sector, CHUNK sectors per file
//   errors-<NN>.json     the sectors of part-<NN> that could not be read, with the reason
//   part-extra-<NN>.ndjson, errors-extra-<NN>.json   the same, for an ONLY = "extra" run
// A run writes the part files FROM to TO. Each file is written as soon as its sectors are read, so a run cut
// short keeps every file it finished; run the rest by setting FROM. A whole game is 53 files: 2.5 reads about
// 30 files in 15 minutes, 2.31 (read through the 2.31 helper) about 26 in 27 minutes, against the 30-minute cap.
// ONLY = "extra" reads just the main menu sectors and the unlisted ones into part-extra-<NN>.ndjson, for adding them to
// an extract made with the two Night City blocks alone.
//
// Run it in the host with a 30-minute timeout.

// ---- CONFIG ----
const GAME  = "2.5";        // the game version the loaded archives belong to; names the output folder
const FROM  = 0, TO = 25;    // the first and last part-<NN> file this run writes
const ONLY  = null;           // "extra": the main menu and unlisted sectors only, into part-extra-<NN>.ndjson
const CHUNK = 500;          // sectors per NDJSON file
// ----------------

const BS = String.fromCharCode(92);
const PRE = ["base", "worlds", "03_night_city", "_compiled", "default"].join(BS) + BS;
const BLOCKS = [
    { name: "night_city", path: PRE + "blocks" + BS + "all.streamingblock" },
    { name: "ep1", path: PRE + "ep1" + BS + "blocks" + BS + "all.streamingblock" },
    { name: "main_menu", path: ["base", "worlds", "04_main_menu", "_compiled", "default", "blocks", "all.streamingblock"].join(BS) }
];
const OUT = "world-index/" + GAME + "/";

function load(p) { return JSON.parse(wkit.GameFileToJson(wkit.GetFileFromArchive(p, OpenAs.GameFile))); }
function v3(v) { return [v.X, v.Y, v.Z]; }
function pad(n) { return (n < 10 ? "0" : "") + n; }

const descriptors = [];
const seen = new Set();
for (const b of BLOCKS) {
    for (const d of load(b.path).Data.RootChunk.descriptors) {
        const path = d.data.DepotPath.$value;
        if (seen.has(path)) { continue; }
        seen.add(path);
        const lo = v3(d.streamingBox.Min), hi = v3(d.streamingBox.Max);
        descriptors.push({
            path: path, block: b.name, category: d.category, level: d.level,
            min: Math.abs(lo[0]) < 1e30 ? lo : null, max: Math.abs(lo[0]) < 1e30 ? hi : null,
            prefab: (d.questPrefabNodeRef && d.questPrefabNodeRef.$value !== "0") ? d.questPrefabNodeRef.$value : null,
            variants: (d.variants || []).map(function (v) { return { name: v.name.$value, on: v.enabledByDefault === 1 || v.enabledByDefault === true, range: v.rangeIndex }; })
        });
    }
}
// Sectors in the game archives that no block lists. A mod archive's copy is never one of them: a path a mod
// provides is skipped unless the base game ships it too, and then the base copy is the one read.
function vanilla(f) {
    const a = f.Archive ? (f.Archive.ArchiveAbsolutePath ?? f.Archive.Name ?? "") : "";
    return a.indexOf(BS + "archive" + BS + "pc" + BS + "content" + BS) >= 0 || a.indexOf(BS + "archive" + BS + "pc" + BS + "ep1" + BS) >= 0;
}
let modded = 0;
for (const f of wkit.GetArchiveFiles()) {
    const path = f.FileName ?? f.Name;
    if (!path || !path.endsWith(".streamingsector") || seen.has(path)) { continue; }
    if (!vanilla(f)) { modded++; continue; }
    seen.add(path);
    descriptors.push({ path: path, block: null, category: null, level: null, min: null, max: null, prefab: null, variants: [] });
}
descriptors.sort(function (a, b) { return a.path < b.path ? -1 : a.path > b.path ? 1 : 0; });
if (FROM === 0 || ONLY === "extra") { wkit.SaveToRaw(OUT + "sectors.json", JSON.stringify(descriptors)); }
logger.Info("sectors " + descriptors.length + ": " + descriptors.filter(function (d) { return d.block === null; }).length
    + " listed by no block; " + modded + " sector paths served only by mod archives were left out");

// The sectors this run reads, and the part file each lands in.
const todo = ONLY === "extra"
    ? descriptors.filter(function (d) { return d.block === "main_menu" || d.block === null; })
    : descriptors.slice(FROM * CHUNK, Math.min(descriptors.length, (TO + 1) * CHUNK));
const first = 0, last = todo.length;
logger.Info(ONLY === "extra" ? "extra: " + todo.length + " sectors"
    : "files " + pad(FROM) + ".." + pad(TO) + " read sectors " + (FROM * CHUNK) + ".." + (FROM * CHUNK + todo.length - 1)
      + "; the last file is " + pad(Math.ceil(descriptors.length / CHUNK) - 1));

let errors = [], unreadable = 0;
let lines = [], chunk = ONLY === "extra" ? 0 : FROM, rows = 0;
const prefix = ONLY === "extra" ? "part-extra-" : "part-", errPrefix = ONLY === "extra" ? "errors-extra-" : "errors-";
const started = Date.now();
for (let k = first; k < last; k++) {
    const path = todo[k].path;
    let text;
    try { text = wkit.WorldIndexSector(path); } catch (e) { text = JSON.stringify({ path: path, error: String(e) }); }
    const parsed = JSON.parse(text);
    if (parsed.error || parsed.found === false) {
        errors.push({ path: path, error: parsed.error || "not in the loaded archives" });
    } else {
        rows += parsed.rows.length;
        lines.push(text);
    }
    if ((k + 1) % CHUNK === 0 || k === last - 1) {
        wkit.SaveToRaw(OUT + prefix + pad(chunk) + ".ndjson", lines.join("\n") + "\n");
        wkit.SaveToRaw(OUT + errPrefix + pad(chunk) + ".json", JSON.stringify(errors));
        logger.Info(prefix + pad(chunk) + ": " + lines.length + " sectors, " + errors.length + " unreadable, "
            + Math.round((Date.now() - started) / 1000) + " s so far");
        unreadable += errors.length;
        lines = [];
        errors = [];
        chunk++;
    }
}
logger.Info("DONE files " + pad(FROM) + ".." + pad(chunk - 1) + ": " + (last - first - unreadable) + " sectors, " + rows
    + " rows, " + unreadable + " unreadable, " + Math.round((Date.now() - started) / 1000) + " s");
