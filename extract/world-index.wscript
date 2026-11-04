// world-index.wscript - reads every streaming sector of the loaded game into NDJSON for build.py.
//
// The sector list comes from the base and Phantom Liberty streaming blocks, so interior sectors with LOD
// suffixes other than _0 are included. Each sector goes through wkit.WorldIndexSector (a custom host build
// that has it), which reads 2.31 and 2.5 sectors into the same shape. Output, under the dump directory's
// wscript\raw\world-index\<GAME>\:
//   sectors.json        every descriptor: path, category, level, streaming box, variants, quest prefab
//   part-<NN>.ndjson     one line per sector, CHUNK sectors per file
//   errors-<PART>.json   sectors that could not be read, with the reason
// A run stops after one PART of PARTS; set PART and run again until every part is written.
//
// Run it in the host with a 30-minute timeout.

// ---- CONFIG ----
const GAME  = "2.5";        // the game version the loaded archives belong to; names the output folder
const PART  = 0, PARTS = 2;  // this run reads part PART of PARTS
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
if (PART === 0) { wkit.SaveToRaw(OUT + "sectors.json", JSON.stringify(descriptors)); }

// A part is a whole number of chunks, so two parts never write the same part-NN file.
const size = Math.ceil(descriptors.length / PARTS / CHUNK) * CHUNK;
const first = PART * size, last = Math.min(descriptors.length, first + size);
logger.Info("sectors " + descriptors.length + "; part " + PART + " of " + PARTS + " reads " + first + ".." + (last - 1));

const errors = [];
let lines = [], chunk = Math.floor(first / CHUNK), rows = 0;
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
        logger.Info("part-" + pad(chunk) + ": " + lines.length + " sectors, " + Math.round((Date.now() - started) / 1000) + " s so far");
        lines = [];
        chunk++;
    }
}
wkit.SaveToRaw(OUT + "errors-" + PART + ".json", JSON.stringify(errors));
logger.Info("DONE part " + PART + ": " + (last - first - errors.length) + " sectors, " + rows + " rows, " + errors.length + " unreadable, " + Math.round((Date.now() - started) / 1000) + " s");
