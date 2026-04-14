const uploadBtn = document.getElementById("uploadBtn");
const askBtn = document.getElementById("askBtn");
const pdfInput = document.getElementById("pdfInput");
const queryInput = document.getElementById("queryInput");
const uploadStatus = document.getElementById("uploadStatus");
const chatLog = document.getElementById("chatLog");

function appendMessage(role, content, metaText = "") {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  const body = document.createElement("pre");
  body.textContent = content;
  div.appendChild(body);
  if (metaText) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = metaText;
    div.appendChild(meta);
  }
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

uploadBtn.addEventListener("click", async () => {
  if (!pdfInput.files.length) {
    uploadStatus.textContent = "Select at least one PDF file.";
    return;
  }
  uploadBtn.disabled = true;
  try {
    const form = new FormData();
    for (const file of pdfInput.files) {
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
  } catch (err) {
    uploadStatus.textContent = `Upload error: ${err.message}`;
  } finally {
    uploadBtn.disabled = false;
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
