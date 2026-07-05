import { promises as fs } from "node:fs";
import path from "node:path";
import process from "node:process";
import crypto from "node:crypto";
import { createClient } from "@supabase/supabase-js";
import dotenv from "dotenv";

dotenv.config();

const DEFAULT_BUCKET = "inspirations";

function parseArgs(argv) {
  const options = {
    manifest: path.resolve(process.cwd(), "manifest.json"),
    imagesDir: path.resolve(process.cwd(), "images"),
    bucket: DEFAULT_BUCKET,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];

    if (arg === "--manifest" && next) {
      options.manifest = path.resolve(next);
      i += 1;
    } else if (arg === "--images-dir" && next) {
      options.imagesDir = path.resolve(next);
      i += 1;
    } else if (arg === "--bucket" && next) {
      options.bucket = next;
      i += 1;
    }
  }

  return options;
}

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

async function fileExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function parseManifest(manifestPath) {
  const content = await fs.readFile(manifestPath, "utf8");
  const parsed = JSON.parse(content);
  if (!Array.isArray(parsed)) {
    throw new Error("Manifest must be a JSON array.");
  }
  return parsed;
}

function normalizeRecord(record) {
  const imagePath =
    typeof record.image_path === "string" ? record.image_path.trim() : "";
  const rawTitle = typeof record.title === "string" ? record.title.trim() : "";

  return {
    title: rawTitle || deriveTitleFromImagePath(imagePath),
    description:
      typeof record.description === "string" ? record.description.trim() : "",
    source_url:
      typeof record.source_url === "string" ? record.source_url.trim() : "",
    section:
      typeof record.section === "string" && record.section.trim()
        ? record.section.trim()
        : "Uploaded References",
    image_path: imagePath,
  };
}

function deriveTitleFromImagePath(imagePath) {
  if (!imagePath) return "Untitled";
  const parsed = path.parse(imagePath).name;
  const normalized = parsed
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return normalized || "Untitled";
}

function toSafeStorageImagePath(imagePath) {
  const safeAsciiPathPattern = /^[A-Za-z0-9._\- /]+$/;
  if (safeAsciiPathPattern.test(imagePath)) {
    return imagePath;
  }

  const ext = path.extname(imagePath) || "";
  const stem = path.basename(imagePath, ext);
  const asciiStem = stem
    .normalize("NFKD")
    .replace(/[^\x00-\x7F]/g, "")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .toLowerCase();
  const hash = crypto
    .createHash("sha1")
    .update(imagePath)
    .digest("hex")
    .slice(0, 8);

  return `${asciiStem || "image"}-${hash}${ext.toLowerCase()}`;
}

function isLikelyImageFile(imagePath) {
  const ext = path.extname(imagePath).toLowerCase();
  return [".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"].includes(ext);
}

async function uploadImageIfMissing(supabase, bucket, imagePath, localPath) {
  const fileBuffer = await fs.readFile(localPath);

  const { error } = await supabase.storage
    .from(bucket)
    .upload(imagePath, fileBuffer, { upsert: false });

  if (!error) return { status: "uploaded" };

  const message = String(error.message || "").toLowerCase();
  if (
    message.includes("already exists") ||
    message.includes("duplicate") ||
    error.statusCode === "409"
  ) {
    return { status: "skipped" };
  }

  throw new Error(`Storage upload failed for ${imagePath}: ${error.message}`);
}

async function upsertDbRowIfMissing(supabase, record) {
  const { data: existing, error: selectError } = await supabase
    .from("inspirations")
    .select("id")
    .eq("image_path", record.image_path)
    .limit(1);

  if (selectError) {
    throw new Error(
      `DB select failed for ${record.image_path}: ${selectError.message}`
    );
  }

  if (existing && existing.length > 0) {
    return { status: "skipped" };
  }

  const { error: insertError } = await supabase
    .from("inspirations")
    .insert(record);

  if (insertError) {
    throw new Error(
      `DB insert failed for ${record.image_path}: ${insertError.message}`
    );
  }

  return { status: "inserted" };
}

async function main() {
  const { manifest, imagesDir, bucket } = parseArgs(process.argv.slice(2));
  const supabaseUrl = requiredEnv("SUPABASE_URL");
  const serviceKey = requiredEnv("SUPABASE_SERVICE_KEY");

  const supabase = createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const records = await parseManifest(manifest);
  const stats = {
    total: records.length,
    uploaded: 0,
    imagesSkipped: 0,
    rowsInserted: 0,
    rowsSkipped: 0,
    missingLocalFiles: 0,
    invalidRecords: 0,
    failed: 0,
  };

  console.log(`Using manifest: ${manifest}`);
  console.log(`Using images directory: ${imagesDir}`);
  console.log(`Target storage bucket: ${bucket}`);
  console.log(`Records to process: ${records.length}\n`);

  for (let index = 0; index < records.length; index += 1) {
    const normalized = normalizeRecord(records[index]);

    if (!normalized.image_path) {
      stats.invalidRecords += 1;
      console.warn(
        `[${index + 1}/${records.length}] Invalid record (missing image_path). Skipping.`
      );
      continue;
    }

    if (!isLikelyImageFile(normalized.image_path)) {
      stats.invalidRecords += 1;
      console.warn(
        `[${index + 1}/${records.length}] Non-image file: ${normalized.image_path}. Skipping.`
      );
      continue;
    }

    const localImagePath = normalized.image_path;
    const storageImagePath = toSafeStorageImagePath(localImagePath);
    const localPath = path.join(imagesDir, localImagePath);

    if (!(await fileExists(localPath))) {
      stats.missingLocalFiles += 1;
      console.warn(
        `[${index + 1}/${records.length}] Missing file: ${localImagePath}`
      );
      continue;
    }

    try {
      const imageResult = await uploadImageIfMissing(
        supabase,
        bucket,
        storageImagePath,
        localPath
      );

      if (imageResult.status === "uploaded") stats.uploaded += 1;
      if (imageResult.status === "skipped") stats.imagesSkipped += 1;

      const dbRecord = { ...normalized, image_path: storageImagePath };
      const rowResult = await upsertDbRowIfMissing(supabase, dbRecord);
      if (rowResult.status === "inserted") stats.rowsInserted += 1;
      if (rowResult.status === "skipped") stats.rowsSkipped += 1;

      console.log(
        `[${index + 1}/${records.length}] OK ${localImagePath} -> ${storageImagePath} (img: ${imageResult.status}, row: ${rowResult.status})`
      );
    } catch (error) {
      stats.failed += 1;
      console.error(
        `[${index + 1}/${records.length}] FAILED ${normalized.image_path}: ${error.message}`
      );
    }
  }

  console.log("\nDone.");
  console.log(JSON.stringify(stats, null, 2));

  if (stats.failed > 0) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(`Fatal: ${error.message}`);
  process.exit(1);
});
