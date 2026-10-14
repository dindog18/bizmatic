(() => {
  const form = document.getElementById("document-upload-form");
  const input = document.getElementById("document-files");
  const zone = document.getElementById("upload-zone");
  const list = document.getElementById("selected-files");
  const status = document.getElementById("upload-status");
  const error = document.getElementById("upload-error");
  const submit = document.getElementById("upload-submit");
  const label = document.getElementById("upload-submit-label");
  let files = [];
  let pending = false;

  function updateFiles() {
    // Keep the actual multipart input in sync with the visible selection.
    const transfer = new DataTransfer();
    files.forEach(file => transfer.items.add(file));
    input.files = transfer.files;
    list.replaceChildren();
    list.hidden = files.length === 0;
    files.forEach((file, index) => {
      const row = document.createElement("li");
      row.className = "list-group-item d-flex align-items-center justify-content-between gap-3";
      const name = document.createElement("span");
      name.className = "text-break fs-10";
      name.textContent = `${file.name} (${Math.ceil(file.size / 1024)} KB)`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn-link btn-sm text-danger flex-shrink-0";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.disabled = pending;
      remove.addEventListener("click", () => {
        files.splice(index, 1);
        updateFiles();
        input.focus();
      });
      row.append(name, remove);
      list.append(row);
    });
    submit.disabled = pending || files.length === 0;
    status.textContent = pending ? "Uploading and extracting. Please wait…" :
      files.length ? `${files.length} file${files.length === 1 ? "" : "s"} selected` : "No files selected";
  }

  function addFiles(selected) {
    if (pending) return;
    files.push(...selected);
    error.hidden = true;
    updateFiles();
  }

  input.addEventListener("change", () => addFiles(Array.from(input.files)));
  zone.addEventListener("dragover", event => {
    event.preventDefault();
    if (!pending) zone.classList.add("border-primary");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("border-primary"));
  zone.addEventListener("drop", event => {
    event.preventDefault();
    zone.classList.remove("border-primary");
    addFiles(Array.from(event.dataTransfer.files));
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (pending || !form.reportValidity()) return;
    const body = new FormData(form); // Includes all files and the CSRF token.
    pending = true;
    input.disabled = true;
    form.setAttribute("aria-busy", "true");
    error.hidden = true;
    label.textContent = "Extracting…";
    updateFiles();
    try {
      const response = await fetch(form.action, { method: "POST", body, credentials: "same-origin" });
      if (response.ok && response.redirected) {
        window.location.assign(response.url);
        return;
      }
      let message = "Upload or extraction failed. Check Batches for saved results before retrying.";
      if (response.status === 400) {
        const data = await response.json();
        message = Object.values(data.errors || {}).flat().map(item => item.message).join(" ") || message;
      } else if (response.status === 403) {
        message = "Your upload session could not be verified. Reload this page and try again.";
      }
      throw new Error(message);
    } catch (failure) {
      error.textContent = failure instanceof TypeError ?
        "Could not confirm upload completion. Check Batches before retrying." : failure.message;
      error.hidden = false;
      error.focus();
      pending = false;
      input.disabled = false;
      form.removeAttribute("aria-busy");
      label.textContent = "Upload and extract";
      updateFiles();
    }
  });

  updateFiles();
})();
