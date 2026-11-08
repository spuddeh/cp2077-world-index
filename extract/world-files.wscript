// world-files.wscript - reads the world's files other than sectors into NDJSON for build_world.py.
//
// Output, under the dump directory's wscript\raw\world-index\<GAME>-<EDITION>\world\ (or OUT_DIR):
//   filelist.json                    every path under base\worlds, for the file catalogue
//   <world>-<kind>.ndjson            one line per element of the world's single files
//   <kind>-<NN>.ndjson               one line per per-area file, CHUNK files per NDJSON
//   errors-<PART>.json               the files of this run that could not be read, with the reason
//   mod-served-<PART>.json           the paths of this run a mod archive serves; build_world.py refuses any the game also ships
// Baked and opaque files (.gidata, .envprobe, .geometry_cache, .lights, .cminimap) are in the catalogue only.
// A run is one PART. A per-area part writes files FROM to the end, each as soon as it is read, so a run cut short at the
// 30-minute cap keeps every file it finished; run the rest by setting FROM. A per-area part reads its files through
// wkit.Batch, at most SLICE files and BATCH_MB of file bytes at a time on THREADS threads; a file the batch could
// not read is read again on its own.

// ---- CONFIG ----
const GAME    = "2.5";      // the game version the loaded archives belong to; names the output folder
const EDITION = "ep1";      // "ep1": the copy a game with Phantom Liberty loads; "base": the copy a game without it loads
const PART    = "single";   // single, inplace, prefab, acoustic, smartobjects or community
const FROM    = 0;          // the first NDJSON file of a per-area part
const CHUNK   = 200;        // per-area files per NDJSON
const THREADS = 8;          // worker threads per batch; 0 takes half the logical processors
const SLICE   = 50;         // most files per batch: each one's JSON is held until its slice is written
const BATCH_MB = 40;        // most file bytes per batch, in MB: a batch's JSON is about 13 characters per file byte and is all
                            // held by the script engine at once, which ends the server when it runs out of room
const OUT_DIR = null;       // null: world-index/<GAME>-<EDITION>/world/; another folder keeps an earlier extract intact
// ----------------

const BS = String.fromCharCode(92);
const OUT = OUT_DIR ? OUT_DIR.replace(/[\/\\]?$/, "/") : "world-index/" + GAME + "-" + EDITION + "/world/";
// The copy Batch reads: "base" is the first copy no mod archive serves, as vanilla() requires.
const COPY = EDITION === "base" ? "basegame" : "base";
const WORLDS = ["03_night_city", "04_main_menu"];

function vanilla(f) {
    const a = f.Archive ? (f.Archive.ArchiveAbsolutePath ?? f.Archive.Name ?? "") : "";
    return a.indexOf(BS + "archive" + BS + "pc" + BS + "content" + BS) >= 0 || a.indexOf(BS + "archive" + BS + "pc" + BS + "ep1" + BS) >= 0;
}
function fileOf(path) {
    if (EDITION === "base") { return wkit.BaseGameFile(path); }
    const f = wkit.GetFileFromArchive(path, OpenAs.GameFile);
    if (f && !vanilla(f)) { throw new Error("served by a mod archive: " + path); }
    return f;
}
// WolvenKit fails at random on a package holding many identical chunks; a read that succeeds is complete.
function read(path) {
    const f = fileOf(path);
    if (!f) { return null; }
    for (let attempt = 0; attempt < 10; attempt++) {
        const text = wkit.GameFileToJson(f);
        if (text) { return JSON.parse(text).Data; }
    }
    throw new Error("not readable after 10 attempts");
}

// Plain data: handles become their object, and a type name stays only where the class says something.
const PLAIN = new Set(["Vector2", "Vector3", "Vector4", "Quaternion", "Transform", "Box", "worldTrafficStaticCollisionSphere"]);
function clean(v) {
    if (v === null || typeof v !== "object") { return v; }
    if (Array.isArray(v)) { return v.map(clean); }
    if (v.$value !== undefined) { return v.$value; }
    if (v.DepotPath !== undefined) { return clean(v.DepotPath); }
    if (v.Elements !== undefined && Object.keys(v).length <= 2) { return clean(v.Elements); }
    if (v.HandleId !== undefined && v.Data !== undefined) { return clean(v.Data); }
    const o = {};
    for (const k of Object.keys(v)) {
        if (k === "$type" && PLAIN.has(v[k])) { continue; }
        o[k] = clean(v[k]);
    }
    return o;
}

// A buffer's bytes arrive as base64 text; its size is the decoded length.
function decodedLength(b64) {
    const pad = b64.endsWith("==") ? 2 : b64.endsWith("=") ? 1 : 0;
    return b64.length / 4 * 3 - pad;
}

const errors = [];
function save(name, lines) { wkit.SaveToRaw(OUT + name + ".ndjson", lines.length ? lines.join("\n") + "\n" : "\n"); }
function each(world, kind, array, shape) {
    const lines = [];
    (array || []).forEach(function (v, i) { lines.push(JSON.stringify(shape ? shape(v, i) : { i: i, v: clean(v) })); });
    save(world + "-" + kind, lines);
    logger.Info(world + " " + kind + ": " + lines.length);
}
// The Data of one Batch result; undefined when the batch could not read it, so read() tries it on its own.
function batchData(text) {
    if (!text) { return undefined; }
    const o = JSON.parse(text);
    return o.Data !== undefined ? o.Data : undefined;
}
function chunkOf(path, section, data) {
    try {
        const d = data !== undefined ? data : read(path);
        if (!d) { errors.push({ path: path, error: "no copy in this edition" }); return null; }
        return section(d.RootChunk, d);
    } catch (e) {
        errors.push({ path: path, error: String(e).slice(0, 300) });
        return null;
    }
}

if (PART === "single") {
    const list = [];
    for (const f of wkit.GetArchiveFiles()) {
        const p = String(f.FileName ?? f.Name ?? "");
        if (p.indexOf(BS + "worlds" + BS) >= 0) { list.push(p); }
    }
    wkit.SaveToRaw(OUT + "filelist.json", JSON.stringify(list.sort()));
    logger.Info("world files " + list.length);
    for (const w of WORLDS) {
        const C = ["base", "worlds", w, "_compiled", "default"].join(BS) + BS;
        const T = ["base", "worlds", w, "sectors", "_generated", "traffic"].join(BS) + BS;
        chunkOf(C + w + ".streamingworld", function (r) { each(w, "world", [r]); });
        chunkOf(C + w + ".mappins", function (r) {
            each(w, "mappins", r.cookedData);
            each(w, "mappins_gps", r.cookedGpsData);
            each(w, "mappins_multi", r.cookedMultiData);
        });
        chunkOf(C + w + ".poimappins", function (r) { each(w, "poi", r.cookedData); });
        chunkOf(C + w + ".areas", function (r) { each(w, "areas", r.cookedData); });
        chunkOf(C + w + ".loot", function (r) {
            const d = r.data.Data;
            each(w, "loot", d.nodeRefsHash, function (hash, i) { return { hash: hash, records: clean(d.tweakDbIds[i]) }; });
        });
        chunkOf(C + w + ".devices", function (r) { each(w, "devices", r.data.Data.unk1); });
        chunkOf(C + w + "_init.devices", function (r) { each(w, "devices_init", r.data.Data.unk1); });
        chunkOf(C + w + ".locopaths", function (r) { each(w, "locopaths", r.paths); });
        chunkOf(C + w + ".streamingquerydata", function (r) {
            each(w, "roads", r.roadDatas);
            each(w, "road_links", [r.connectedRoadDataIndices]);
        });
        chunkOf(C + w + ".psrep", function (r) {
            const d = r.buffer && r.buffer.Data;
            if (!d) { each(w, "persistent", []); return; }
            each(w, "persistent", d.Chunks, function (c, i) { return { cruid: d.CruidDict[String(i)], v: clean(c) }; });
        });
        chunkOf(T + "all.traffic_persistent", function (r) { each(w, "lanes", r.data.lanes); });
        chunkOf(T + "all.lane_polygons", function (r) { each(w, "lane_polygons", r.data); });
        chunkOf(T + "all.lane_connections", function (r) { each(w, "lane_connections", r.data); });
        chunkOf(T + "all.traffic_collisions", function (r) { each(w, "lane_collisions", r.data.Data.laneCollisions); });
        chunkOf(T + "all.spatial_representation", function (r) { each(w, "lane_neighbors", r.neighborGroups); });
        chunkOf(T + "traffic.null_areas", function (r) {
            each(w, "null_collisions", r.nullAreasCollisionData.Data.nullAreaCollisions);
            each(w, "null_blockades", r.nullAreaBlockadeData.Data.nullAreasBlockades);
        });
    }
} else {
    const EXT = { inplace: ".streamingsector_inplace", prefab: ".cookedprefab", acoustic: ".acousticdata", smartobjects: ".smartobjects", community: ".community" }[PART];
    const paths = [], modServed = [], size = {};
    for (const f of wkit.GetArchiveFiles()) {
        const p = String(f.FileName ?? f.Name ?? "");
        if (!p.endsWith(EXT) || (PART !== "community" && p.indexOf(BS + "worlds" + BS) < 0)) { continue; }
        size[p] = Number(f.Size ?? 0);
        if (EDITION === "base") {
            if (wkit.BaseGameFile(p)) { paths.push(p); }
        } else if (vanilla(f)) {
            paths.push(p);
        } else {
            modServed.push(p);
        }
    }
    paths.sort();
    wkit.SaveToRaw(OUT + "mod-served-" + PART + ".json", JSON.stringify(modServed.sort()));
    logger.Info(PART + " files " + paths.length + ", largest " + Math.round(Math.max(0, ...paths.map(p => size[p])) / 1e6) + " MB");
    // The end of the batch that starts at k: SLICE files or BATCH_MB of bytes, and always at least one file.
    const batchEnd = function (k) {
        let end = k + 1, bytes = size[paths[k]];
        while (end < paths.length && end - k < SLICE && bytes + size[paths[end]] <= BATCH_MB * 1e6) { bytes += size[paths[end]]; end++; }
        return end;
    };
    const pad = function (n) { return (n < 10 ? "0" : "") + n; };
    let lines = [];
    let batch = [], batchStart = 0;
    const started = Date.now();
    for (let k = FROM * CHUNK; k < paths.length; k++) {
        if (k >= batchStart + batch.length) {
            batchStart = k;
            batch = wkit.Batch("GameFileToJson", paths.slice(k, batchEnd(k)), THREADS, COPY);
        }
        const data = batchData(batch[k - batchStart]);
        batch[k - batchStart] = null;
        const row = chunkOf(paths[k], function (r, d) {
            const embedded = (d.EmbeddedFiles || []).map(function (e) { return clean(e.FileName); });
            if (PART === "inplace") { return { path: paths[k], resources: clean(r.inplaceResources), embedded: embedded }; }
            if (PART === "prefab") { return { path: paths[k], dependencies: clean(r.dependencies), embedded: embedded }; }
            if (PART === "community") { return { path: paths[k], template: clean(r.communityTemplate) }; }
            if (PART === "acoustic") {
                return { path: paths[k], cells: r.cells.map(function (c) { return { sector: c.sectorId, bytes: c.nodes && c.nodes.Bytes ? decodedLength(c.nodes.Bytes) : 0 }; }) };
            }
            return {
                path: paths[k], box: clean(r.localBoundingBox), nodes: clean(r.compiledNodesData), members: clean(r.soMembership),
                properties: clean(r.propertyDictionary), transforms: clean(r.transformDictionary), sequences: clean(r.transformSequenceDictionary)
            };
        }, data);
        if (row) { lines.push(JSON.stringify(row)); }
        if ((k + 1) % CHUNK === 0 || k === paths.length - 1) {
            const n = Math.floor(k / CHUNK);
            save(PART + "-" + pad(n), lines);
            lines = [];
            logger.Info(PART + " file " + pad(n) + " done, " + Math.round((Date.now() - started) / 1000) + " s so far");
        }
    }
}
wkit.SaveToRaw(OUT + "errors-" + PART + (PART === "single" ? "" : "-" + FROM) + ".json", JSON.stringify(errors));
logger.Info("DONE " + PART + ": " + errors.length + " unread " + JSON.stringify(errors.slice(0, 4)));
