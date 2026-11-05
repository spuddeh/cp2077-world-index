// world-index.wscript - reads every streaming sector of the loaded game into NDJSON for build.py.
//
// The sector list comes from the base and Phantom Liberty streaming blocks, so interior sectors with LOD
// suffixes other than _0 are included. Each sector goes through wkit.WorldIndexSector (a custom host build
// that has it), which reads 2.31 and 2.5 sectors into the same shape. Output, under the dump directory's
// wscript\raw\world-index\<GAME>\:
//   sectors.json        every descriptor: path, category, level, streaming box, variants, quest prefab
//   part-<NN>.ndjson     one line per sector, CHUNK sectors per file
//   errors-<NN>.json     the sectors of part-<NN> that could not be read, with the reason
// A run writes the part files FROM to TO. Each file is written as soon as its sectors are read, so a run cut
// short keeps every file it finished; run the rest by setting FROM. A whole game is 53 files: 2.5 reads about
// 30 files in 15 minutes, 2.31 (read through the 2.31 helper) about 26 in 27 minutes, against the 30-minute cap.
//
// Run it in the host with a 30-minute timeout.

// ---- CONFIG ----
const GAME  = "2.5";        // the game version the loaded archives belong to; names the output folder
const FROM  = 0, TO = 25;    // the first and last part-<NN> file this run writes
const CHUNK = 500;          // sectors per NDJSON file
// ----------------

const BS = String.fromCharCode(92);
const PRE = ["base", "worlds", "03_night_city", "_compiled", "default"].join(BS) + BS;
const BLOCKS = [PRE + "blocks" + BS + "all.streamingblock", PRE + "ep1" + BS + "blocks" + BS + "all.streamingblock"];
const OUT = "world-index/" + GAME + "/";

function load(p) { return JSON.parse(wkit.GameFileToJson(wkit.GetFileFromArchive(p, OpenAs.GameFile))); }
function v3(v) { return [v.X, v.Y, v.Z]; }
function pad(n) { return (n < 10 ? "0" : "") + n; }

const descriptors = [];
const seen = new Set();
for (const b of BLOCKS) {
    for (const d of load(b).Data.RootChunk.descriptors) {
        const path = d.data.DepotPath.$value;
        if (seen.has(path)) { continue; }
        seen.add(path);
        const lo = v3(d.streamingBox.Min), hi = v3(d.streamingBox.Max);
        descriptors.push({
            path: path, category: d.category, level: d.level,
            min: Math.abs(lo[0]) < 1e30 ? lo : null, max: Math.abs(lo[0]) < 1e30 ? hi : null,
            prefab: (d.questPrefabNodeRef && d.questPrefabNodeRef.$value !== "0") ? d.questPrefabNodeRef.$value : null,
            variants: (d.variants || []).map(function (v) { return { name: v.name.$value, on: v.enabledByDefault === 1 || v.enabledByDefault === true, range: v.rangeIndex }; })
        });
    }
}
descriptors.sort(function (a, b) { return a.path < b.path ? -1 : a.path > b.path ? 1 : 0; });
if (FROM === 0) { wkit.SaveToRaw(OUT + "sectors.json", JSON.stringify(descriptors)); }

const first = FROM * CHUNK, last = Math.min(descriptors.length, (TO + 1) * CHUNK);
logger.Info("sectors " + descriptors.length + "; files " + pad(FROM) + ".." + pad(TO) + " read sectors " + first + ".." + (last - 1)
    + "; the last file is " + pad(Math.ceil(descriptors.length / CHUNK) - 1));

let errors = [], unreadable = 0;
let lines = [], chunk = FROM, rows = 0;
const started = Date.now();
for (let k = first; k < last; k++) {
    const path = descriptors[k].path;
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
        wkit.SaveToRaw(OUT + "part-" + pad(chunk) + ".ndjson", lines.join("\n") + "\n");
        wkit.SaveToRaw(OUT + "errors-" + pad(chunk) + ".json", JSON.stringify(errors));
        logger.Info("part-" + pad(chunk) + ": " + lines.length + " sectors, " + errors.length + " unreadable, "
            + Math.round((Date.now() - started) / 1000) + " s so far");
        unreadable += errors.length;
        lines = [];
        errors = [];
        chunk++;
    }
}
logger.Info("DONE files " + pad(FROM) + ".." + pad(chunk - 1) + ": " + (last - first - unreadable) + " sectors, " + rows
    + " rows, " + unreadable + " unreadable, " + Math.round((Date.now() - started) / 1000) + " s");
