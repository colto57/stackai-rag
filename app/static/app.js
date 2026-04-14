const uploadBtn = document.getElementById("uploadBtn");
const clearFilesBtn = document.getElementById("clearFilesBtn");
const askBtn = document.getElementById("askBtn");
const pdfInput = document.getElementById("pdfInput");
const queryInput = document.getElementById("queryInput");
const uploadStatus = document.getElementById("uploadStatus");
const chatLog = document.getElementById("chatLog");
const memorySummary = document.getElementById("memorySummary");
const memoryFileList = document.getElementById("memoryFileList");
const selectedSummary = document.getElementById("selectedSummary");
const selectedFileList = document.getElementById("selectedFileList");

const pendingFiles = new Map();
const knownMemoryHashes = new Set();
const knownMemorySignatures = new Set();

function escapeHtml(text) {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function applyInlineMarkdown(text) {
  return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function renderAssistantContent(text) {
  const lines = text.split(/\r?\n/);
  const htmlParts = [];
  let inUl = false;
  let inOl = false;

  function closeLists() {
    if (inUl) {
      htmlParts.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      htmlParts.push("</ol>");
      inOl = false;
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeLists();
      continue;
    }
    const bulletMatch = line.match(/^[-*]\s+(.+)/);
    if (bulletMatch) {
      if (inOl) {
        htmlParts.push("</ol>");
        inOl = false;
      }
      if (!inUl) {
        htmlParts.push("<ul>");
        inUl = true;
      }
      htmlParts.push(`<li>${applyInlineMarkdown(escapeHtml(bulletMatch[1]))}</li>`);
      continue;
    }
    const numberedMatch = line.match(/^\d+\.\s+(.+)/);
    if (numberedMatch) {
      if (inUl) {
        htmlParts.push("</ul>");
        inUl = false;
      }
      if (!inOl) {
        htmlParts.push("<ol>");
        inOl = true;
      }
      htmlParts.push(`<li>${applyInlineMarkdown(escapeHtml(numberedMatch[1]))}</li>`);
      continue;
    }
    closeLists();
    htmlParts.push(`<p>${applyInlineMarkdown(escapeHtml(line))}</p>`);
  }
  closeLists();
  return htmlParts.join("");
}

function prettifyMeta(metaText) {
  return metaText.replaceAll(" | ", "\n").replaceAll("; ", "\n- ");
}

function appendMessage(role, content, metaText = "") {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  const body = document.createElement("div");
  body.className = "msg-content";
  if (role === "bot") {
    body.innerHTML = renderAssistantContent(content);
  } else {
    const pre = document.createElement("pre");
    pre.textContent = content;
    body.appendChild(pre);
  }
  div.appendChild(body);

  if (metaText) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.style.whiteSpace = "pre-line";
    meta.textContent = role === "bot" ? prettifyMeta(metaText) : metaText;
    div.appendChild(meta);
  }
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function fileKey(file) {
  return `${file.name}__${file.size}__${file.lastModified}`;
}

function fileSignature(name, size) {
  return `${String(name || "").toLowerCase()}__${Number(size || 0)}`;
}

function renderPendingFiles() {
  const entries = Array.from(pendingFiles.values());
  selectedSummary.textContent = `Pending upload: ${entries.length} file${entries.length === 1 ? "" : "s"}`;
  if (entries.length === 0) {
    selectedFileList.textContent = "No files selected for upload.";
    return;
  }
  selectedFileList.innerHTML = "";
  entries.forEach((entry) => {
    const sizeMb = (entry.file.size / (1024 * 1024)).toFixed(2);
    const duplicateTag = entry.isDuplicate ? " [already uploaded]" : "";
    const item = document.createElement("div");
    item.className = "file-item";
    item.textContent = `${entry.file.name} (${sizeMb} MB)${duplicateTag}`;
    selectedFileList.appendChild(item);
  });
}

function renderMemoryFiles(data) {
  knownMemoryHashes.clear();
  knownMemorySignatures.clear();
  (data.files || []).forEach((file) => {
    if (file.file_hash) {
      knownMemoryHashes.add(file.file_hash);
    }
    knownMemorySignatures.add(fileSignature(file.filename, file.file_size_bytes));
  });

  memorySummary.textContent = `In-memory documents: ${data.total_documents} | Indexed chunks: ${data.total_chunks}`;
  if (!data.files || data.files.length === 0) {
    memoryFileList.textContent = "No files currently in memory.";
    return;
  }
  memoryFileList.innerHTML = "";
  data.files.forEach((file) => {
    const div = document.createElement("div");
    div.className = "file-item";
    div.textContent = `${file.filename} (${file.pages} pages)`;
    memoryFileList.appendChild(div);
  });
}

async function refreshMemoryFiles() {
  const res = await fetch("/memory/files");
  if (!res.ok) {
    throw new Error("Could not fetch file memory.");
  }
  renderMemoryFiles(await res.json());
}

async function sha256Hex(file) {
  if (!globalThis.crypto || !globalThis.crypto.subtle) {
    return "";
  }
  try {
    const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    const bytes = Array.from(new Uint8Array(digest));
    return bytes.map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch (_) {
    return "";
  }
}

async function clearMemory() {
  const res = await fetch("/memory/files", { method: "DELETE" });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || "Failed to clear files");
  }
  renderMemoryFiles(await res.json());
}

pdfInput.addEventListener("change", async () => {
  const chosen = Array.from(pdfInput.files);
  if (chosen.length === 0) {
    return;
  }
  const pendingSignatures = new Set(
    Array.from(pendingFiles.values()).map((entry) => fileSignature(entry.file.name, entry.file.size))
  );

  // Show queued files immediately.
  chosen.forEach((file) => {
    const key = fileKey(file);
    const signature = fileSignature(file.name, file.size);
    pendingFiles.set(key, {
      file,
      fileHash: "",
      isDuplicate: knownMemorySignatures.has(signature) || pendingSignatures.has(signature),
    });
    pendingSignatures.add(signature);
  });
  renderPendingFiles();
  uploadStatus.classList.remove("status-warn");
  uploadStatus.textContent = `Queued ${chosen.length} file${chosen.length === 1 ? "" : "s"} for upload.`;

  // Optional async hash pass for better duplicate detection.
  const updates = await Promise.all(
    chosen.map(async (file) => ({ file, hash: await sha256Hex(file) }))
  );
  let hasDuplicate = false;
  updates.forEach(({ file, hash }) => {
    const key = fileKey(file);
    const existing = pendingFiles.get(key);
    if (!existing) return;
    const duplicateByHash = !!hash && knownMemoryHashes.has(hash);
    const updated = {
      ...existing,
      fileHash: hash,
      isDuplicate: existing.isDuplicate || duplicateByHash,
    };
    if (updated.isDuplicate) {
      hasDuplicate = true;
    }
    pendingFiles.set(key, updated);
  });
  renderPendingFiles();
  if (hasDuplicate) {
    uploadStatus.textContent = "Warning: one or more queued files may already exist in memory.";
    uploadStatus.classList.add("status-warn");
  }

  pdfInput.value = "";
});

uploadBtn.addEventListener("click", async () => {
  const entries = Array.from(pendingFiles.values());
  if (entries.length === 0) {
    uploadStatus.textContent = "Select at least one PDF file.";
    return;
  }
  const duplicates = entries.filter((entry) => entry.isDuplicate);
  if (duplicates.length > 0) {
    const names = duplicates.slice(0, 5).map((entry) => entry.file.name).join(", ");
    const suffix = duplicates.length > 5 ? ", ..." : "";
    const ok = window.confirm(`Are you sure you want to upload duplicate file(s)? ${names}${suffix}`);
    if (!ok) {
      uploadStatus.textContent = "Upload cancelled due to duplicate files.";
      return;
    }
  }

  uploadBtn.disabled = true;
  try {
    const form = new FormData();
    entries.forEach((entry) => form.append("files", entry.file));
    const res = await fetch("/ingest", {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt || "Upload failed");
    }
    const data = await res.json();
    const ingested = data.files
      .map((f) => `${f.filename}: ${f.status} (${f.chunks} chunks)${f.reason ? ` - ${f.reason}` : ""}`)
      .join(" | ");
    uploadStatus.textContent = `Indexed docs=${data.total_documents}, chunks=${data.total_chunks}. ${ingested}`;
    uploadStatus.classList.remove("status-warn");
    pendingFiles.clear();
    renderPendingFiles();
    await refreshMemoryFiles();
  } catch (err) {
    uploadStatus.textContent = `Upload error: ${err.message}`;
    uploadStatus.classList.add("status-warn");
  } finally {
    uploadBtn.disabled = false;
  }
});

clearFilesBtn.addEventListener("click", async () => {
  clearFilesBtn.disabled = true;
  try {
    await clearMemory();
    pendingFiles.clear();
    renderPendingFiles();
    uploadStatus.textContent = "Cleared all in-memory files and index.";
    uploadStatus.classList.remove("status-warn");
  } catch (err) {
    uploadStatus.textContent = `Clear error: ${err.message}`;
    uploadStatus.classList.add("status-warn");
  } finally {
    clearFilesBtn.disabled = false;
  }
});

askBtn.addEventListener("click", async () => {
  const query = queryInput.value.trim();
  if (!query) return;
  appendMessage("user", query);
  queryInput.value = "";
  askBtn.disabled = true;
  try {
    const res = await fetch("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt || "Query failed");
    }
    const data = await res.json();
    const citeSummary = data.citations && data.citations.length
      ? `Citations: ${data.citations.map((c) => `${c.document} p.${c.page_start}-${c.page_end}`).join("; ")}`
      : `Status: ${data.status}`;
    appendMessage("bot", data.answer, `${citeSummary} | intent=${data.intent}`);
  } catch (err) {
    appendMessage("bot", `Error: ${err.message}`);
  } finally {
    askBtn.disabled = false;
  }
});

queryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!askBtn.disabled) {
      askBtn.click();
    }
  }
});

// User requested clearing files when leaving or refreshing the page.
window.addEventListener("pagehide", () => {
  fetch("/memory/files", { method: "DELETE", keepalive: true }).catch(() => {});
});

(async () => {
  try {
    await clearMemory();
    uploadStatus.textContent = "Started a fresh session: previous uploaded files were cleared.";
  } catch (_) {
    // keep going even if clear fails
  }
  try {
    await refreshMemoryFiles();
  } catch (err) {
    memorySummary.textContent = `Memory status unavailable: ${err.message}`;
    memoryFileList.textContent = "";
  }
  renderPendingFiles();
})();
