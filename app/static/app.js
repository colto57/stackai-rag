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

async function sha256Hex(file) {
  if (!globalThis.crypto || !globalThis.crypto.subtle) {
    return "";
  }
  try {
    const buffer = await file.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", buffer);
    const bytes = Array.from(new Uint8Array(digest));
    return bytes.map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch (_) {
    return "";
  }
}

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
    const item = document.createElement("div");
    item.className = "file-item";
    const sizeMb = (entry.file.size / (1024 * 1024)).toFixed(2);
    const duplicateTag = entry.isDuplicate ? " [already uploaded]" : "";
    item.textContent = `${entry.file.name} (${sizeMb} MB)${duplicateTag}`;
    selectedFileList.appendChild(item);
  });
}

function renderMemoryFiles(data) {
  knownMemoryHashes.clear();
  knownMemorySignatures.clear();
  for (const file of data.files || []) {
    if (file.file_hash) {
      knownMemoryHashes.add(file.file_hash);
    }
    if (file.filename) {
      knownMemorySignatures.add(fileSignature(file.filename, file.file_size_bytes));
    }
  }

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
  const data = await res.json();
  renderMemoryFiles(data);
}

pdfInput.addEventListener("change", () => {
  const chosen = Array.from(pdfInput.files);
  const pendingHashes = new Set(Array.from(pendingFiles.values()).map((entry) => entry.fileHash));
  const pendingSignatures = new Set(
    Array.from(pendingFiles.values()).map((entry) => fileSignature(entry.file.name, entry.file.size))
  );

  // Add files immediately so UI never appears broken.
  const provisionalEntries = chosen.map((file) => {
    const sig = fileSignature(file.name, file.size);
    return {
      file,
      fileHash: "",
      isDuplicate: knownMemorySignatures.has(sig) || pendingSignatures.has(sig),
    };
  });
  provisionalEntries.forEach((entry) => {
    pendingFiles.set(fileKey(entry.file), entry);
  });
  renderPendingFiles();

  Promise.all(
    chosen.map(async (file) => {
      const hash = await sha256Hex(file);
      return {
        file,
        fileHash: hash,
        isDuplicate: false,
      };
    })
  )
    .then((enriched) => {
      let hasDuplicate = false;
      enriched.forEach((entry) => {
        const sig = fileSignature(entry.file.name, entry.file.size);
        const duplicateByHash = !!entry.fileHash && (knownMemoryHashes.has(entry.fileHash) || pendingHashes.has(entry.fileHash));
        const duplicateBySignature = knownMemorySignatures.has(sig) || pendingSignatures.has(sig);
        const isDuplicate = duplicateByHash || duplicateBySignature;
        hasDuplicate = hasDuplicate || isDuplicate;
        pendingFiles.set(fileKey(entry.file), {
          ...entry,
          isDuplicate,
        });
      });
      renderPendingFiles();
      if (hasDuplicate) {
        uploadStatus.textContent = "Warning: one or more selected files already exist in memory or queue.";
        uploadStatus.classList.add("status-warn");
      } else {
        uploadStatus.classList.remove("status-warn");
        uploadStatus.textContent = "";
      }
    })
    .catch((err) => {
      // Keep already-queued files visible even if hash inspection fails.
      uploadStatus.textContent = `Queued files. Duplicate hash check unavailable: ${err.message}`;
      uploadStatus.classList.add("status-warn");
    })
    .finally(() => {
      // Allow selecting same filenames again in later batches.
      pdfInput.value = "";
    });
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
    entries.forEach((entry) => {
      form.append("files", entry.file);
    });
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
      .map((f) => {
        const reason = f.reason ? ` - ${f.reason}` : "";
        return `${f.filename}: ${f.status} (${f.chunks} chunks)${reason}`;
      })
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
    const res = await fetch("/memory/files", { method: "DELETE" });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt || "Failed to clear files");
    }
    const data = await res.json();
    renderMemoryFiles(data);
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

refreshMemoryFiles().catch((err) => {
  memorySummary.textContent = `Memory status unavailable: ${err.message}`;
  memoryFileList.textContent = "";
});
renderPendingFiles();
