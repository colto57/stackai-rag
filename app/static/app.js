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

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
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
  return metaText
    .replaceAll(" | ", "\n")
    .replaceAll("; ", "\n- ");
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

function renderPendingFiles() {
  const files = Array.from(pendingFiles.values());
  selectedSummary.textContent = `Pending upload: ${files.length} file${files.length === 1 ? "" : "s"}`;
  if (files.length === 0) {
    selectedFileList.textContent = "No files selected for upload.";
    return;
  }
  selectedFileList.innerHTML = "";
  files.forEach((file) => {
    const item = document.createElement("div");
    item.className = "file-item";
    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
    item.textContent = `${file.name} (${sizeMb} MB)`;
    selectedFileList.appendChild(item);
  });
}

function renderMemoryFiles(data) {
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

uploadBtn.addEventListener("click", async () => {
  const filesToUpload = Array.from(pendingFiles.values());
  if (!filesToUpload.length) {
    uploadStatus.textContent = "Select at least one PDF file.";
    return;
  }
  uploadBtn.disabled = true;
  try {
    const form = new FormData();
    for (const file of filesToUpload) {
      form.append("files", file);
    }
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
    pendingFiles.clear();
    pdfInput.value = "";
    renderPendingFiles();
    await refreshMemoryFiles();
  } catch (err) {
    uploadStatus.textContent = `Upload error: ${err.message}`;
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
  } catch (err) {
    uploadStatus.textContent = `Clear error: ${err.message}`;
  } finally {
    clearFilesBtn.disabled = false;
  }
});

pdfInput.addEventListener("change", () => {
  for (const file of Array.from(pdfInput.files)) {
    pendingFiles.set(fileKey(file), file);
  }
  renderPendingFiles();
  // Allow selecting the same file again later if user clears queue.
  pdfInput.value = "";
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
