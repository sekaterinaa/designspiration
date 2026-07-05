import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = "https://hxxcwswrwgftolfbuosf.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_GJkQX8HfXOOcyQgLHYF0Fg_TDAadrX1";
const BUCKET = "inspirations";

const statusEl = document.querySelector("#status");
const galleryEl = document.querySelector("#gallery");
const lightboxEl = document.createElement("div");
let isLightboxOpen = false;

lightboxEl.className = "lightbox";
lightboxEl.innerHTML = `
  <button class="lightbox-close" type="button" aria-label="Close image">✕</button>
  <img class="lightbox-image" alt="" />
  <p class="lightbox-caption"></p>
`;
document.body.append(lightboxEl);

const lightboxImageEl = lightboxEl.querySelector(".lightbox-image");
const lightboxCaptionEl = lightboxEl.querySelector(".lightbox-caption");
const lightboxCloseEl = lightboxEl.querySelector(".lightbox-close");

const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: { persistSession: false },
});

function buildPublicImageUrl(imagePath) {
  return `${SUPABASE_URL}/storage/v1/object/public/${BUCKET}/${encodeURIComponent(imagePath)}`;
}

function escapeHtml(input) {
  return String(input ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderCards(rows) {
  if (!rows.length) {
    statusEl.textContent = "No inspirations yet.";
    return;
  }

  statusEl.textContent = `${rows.length} inspirations loaded`;
  const cardsHtml = rows
    .map((row) => {
      const title = row.title || "Untitled";
      const description = row.description?.trim() || "No description yet.";
      const section = row.section || "Uncategorized";
      const imageUrl = buildPublicImageUrl(row.image_path);

      return `
        <article class="card">
          <div class="card-image-wrap">
            <img
              class="card-image"
              src="${imageUrl}"
              alt="${escapeHtml(title)}"
              data-image-url="${imageUrl}"
              data-image-title="${escapeHtml(title)}"
              loading="lazy"
              decoding="async"
            />
          </div>
          <div class="card-body">
            <h2 class="card-title">${escapeHtml(title)}</h2>
            <p class="card-description">${escapeHtml(description)}</p>
            <div class="card-meta">${escapeHtml(section)}</div>
          </div>
        </article>
      `;
    })
    .join("");

  galleryEl.innerHTML = cardsHtml;
}

function openLightbox(imageUrl, title) {
  lightboxImageEl.src = imageUrl;
  lightboxImageEl.alt = title;
  lightboxCaptionEl.textContent = title;
  lightboxEl.classList.add("open");
  document.body.classList.add("no-scroll");
  isLightboxOpen = true;
}

function closeLightbox() {
  if (!isLightboxOpen) return;
  lightboxEl.classList.remove("open");
  document.body.classList.remove("no-scroll");
  lightboxImageEl.src = "";
  lightboxImageEl.alt = "";
  lightboxCaptionEl.textContent = "";
  isLightboxOpen = false;
}

galleryEl.addEventListener("click", (event) => {
  const imageEl = event.target.closest(".card-image");
  if (!imageEl) return;
  const imageUrl = imageEl.dataset.imageUrl || "";
  const title = imageEl.dataset.imageTitle || "Reference image";
  if (!imageUrl) return;
  openLightbox(imageUrl, title);
});

lightboxCloseEl.addEventListener("click", closeLightbox);

lightboxEl.addEventListener("click", (event) => {
  const clickedBackdrop = event.target === lightboxEl;
  if (clickedBackdrop) closeLightbox();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeLightbox();
});

function dedupeByImagePath(rows) {
  const seen = new Set();
  const unique = [];

  for (const row of rows) {
    const key = row?.image_path || "";
    if (!key || seen.has(key)) continue;
    seen.add(key);
    unique.push(row);
  }

  return unique;
}

async function loadGallery() {
  statusEl.textContent = "Loading gallery...";
  statusEl.classList.remove("error");

  const { data, error } = await supabase
    .from("inspirations")
    .select("title, description, section, image_path, created_at")
    .order("created_at", { ascending: false });

  if (error) {
    statusEl.textContent = `Could not load data: ${error.message}`;
    statusEl.classList.add("error");
    return;
  }

  const allRows = data ?? [];
  const uniqueRows = dedupeByImagePath(allRows);
  const removedDuplicates = allRows.length - uniqueRows.length;

  renderCards(uniqueRows);
  if (removedDuplicates > 0) {
    statusEl.textContent = `${uniqueRows.length} inspirations loaded (${removedDuplicates} duplicate images hidden)`;
  }
}

loadGallery();
