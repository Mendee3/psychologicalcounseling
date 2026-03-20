(function () {
  const selector = 'input[type="file"][data-photo-crop]';
  const maxBytes = 900 * 1024;
  const maxDimension = 1600;
  const outputSize = 1200;
  const outputType = "image/jpeg";
  const outputQuality = 0.86;
  const previewSize = 360;

  const inputs = Array.from(document.querySelectorAll(selector));
  if (!inputs.length) {
    return;
  }

  const modal = document.createElement("div");
  modal.className = "photo-cropper-backdrop";
  modal.innerHTML = `
    <div class="photo-cropper-dialog" role="dialog" aria-modal="true" aria-labelledby="photoCropperTitle">
      <div class="photo-cropper-head">
        <h2 id="photoCropperTitle">Зураг тайрах</h2>
        <p>Том зураг шууд илгээхэд алдаа өгөх тул эндээс тайраад, хэмжээг нь багасгаж хадгална.</p>
      </div>
      <div class="photo-cropper-body">
        <div class="photo-cropper-canvas-wrap">
          <canvas class="photo-cropper-canvas" width="${previewSize}" height="${previewSize}"></canvas>
          <div class="photo-cropper-meta">
            <div><strong>Эх зураг:</strong> <span data-role="original-info"></span></div>
            <div><strong>Шинэ зураг:</strong> 1200 × 1200 JPG</div>
            <div>Зургийг чирч байрлалыг тааруулна. Доорх гулсуураар ойртуулж болно.</div>
          </div>
        </div>
        <div class="photo-cropper-controls">
          <label>
            Ойртуулах
            <input type="range" min="100" max="300" step="1" value="100" data-role="zoom" />
          </label>
          <div class="photo-cropper-actions">
            <button type="button" data-role="apply">Тайраад ашиглах</button>
            <button type="button" class="secondary" data-role="cancel">Цуцлах</button>
          </div>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  const canvas = modal.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const zoomInput = modal.querySelector('[data-role="zoom"]');
  const originalInfo = modal.querySelector('[data-role="original-info"]');
  const applyButton = modal.querySelector('[data-role="apply"]');
  const cancelButton = modal.querySelector('[data-role="cancel"]');

  const state = {
    input: null,
    file: null,
    image: null,
    scale: 1,
    minScale: 1,
    offsetX: 0,
    offsetY: 0,
    dragX: 0,
    dragY: 0,
    dragging: false,
  };

  function formatBytes(bytes) {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  }

  function getStatusNode(input) {
    let node = input.parentElement.nextElementSibling;
    if (node && node.classList.contains("photo-upload-status")) {
      return node;
    }

    node = document.createElement("p");
    node.className = "photo-upload-status";
    input.parentElement.insertAdjacentElement("afterend", node);
    return node;
  }

  function setStatus(input, message, warn) {
    const node = getStatusNode(input);
    node.textContent = message;
    node.classList.toggle("warn", Boolean(warn));
  }

  function clearStatus(input) {
    const node = getStatusNode(input);
    node.textContent = "";
    node.classList.remove("warn");
  }

  function setInputFile(input, file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
  }

  function loadImage(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("read_error"));
      reader.onload = () => {
        const image = new Image();
        image.onerror = () => reject(new Error("image_error"));
        image.onload = () => resolve(image);
        image.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  function shouldCrop(file, image) {
    return file.size > maxBytes || image.width > maxDimension || image.height > maxDimension;
  }

  function clampOffsets() {
    const drawWidth = state.image.width * state.scale;
    const drawHeight = state.image.height * state.scale;
    const minX = previewSize - drawWidth;
    const minY = previewSize - drawHeight;
    state.offsetX = Math.min(0, Math.max(minX, state.offsetX));
    state.offsetY = Math.min(0, Math.max(minY, state.offsetY));
  }

  function renderPreview() {
    if (!state.image) {
      return;
    }

    ctx.clearRect(0, 0, previewSize, previewSize);
    ctx.fillStyle = "#eef8ff";
    ctx.fillRect(0, 0, previewSize, previewSize);

    const drawWidth = state.image.width * state.scale;
    const drawHeight = state.image.height * state.scale;
    ctx.drawImage(state.image, state.offsetX, state.offsetY, drawWidth, drawHeight);

    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.95)";
    ctx.lineWidth = 4;
    ctx.strokeRect(2, 2, previewSize - 4, previewSize - 4);
    ctx.restore();
  }

  function openCropper(input, file, image) {
    state.input = input;
    state.file = file;
    state.image = image;
    state.minScale = Math.max(previewSize / image.width, previewSize / image.height);
    state.scale = state.minScale;
    state.offsetX = (previewSize - image.width * state.scale) / 2;
    state.offsetY = (previewSize - image.height * state.scale) / 2;
    zoomInput.value = "100";
    originalInfo.textContent = `${image.width} × ${image.height} · ${formatBytes(file.size)}`;
    clampOffsets();
    renderPreview();
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeCropper(clearInput) {
    if (clearInput && state.input) {
      state.input.value = "";
      clearStatus(state.input);
    }

    state.input = null;
    state.file = null;
    state.image = null;
    state.dragging = false;
    modal.classList.remove("open");
    canvas.classList.remove("dragging");
    document.body.style.overflow = "";
  }

  function updateScale(nextRatio) {
    if (!state.image) {
      return;
    }

    const previousScale = state.scale;
    const centerX = (previewSize / 2 - state.offsetX) / previousScale;
    const centerY = (previewSize / 2 - state.offsetY) / previousScale;
    state.scale = state.minScale * nextRatio;
    state.offsetX = previewSize / 2 - centerX * state.scale;
    state.offsetY = previewSize / 2 - centerY * state.scale;
    clampOffsets();
    renderPreview();
  }

  async function applyCrop() {
    if (!state.input || !state.image) {
      return;
    }

    const outputCanvas = document.createElement("canvas");
    outputCanvas.width = outputSize;
    outputCanvas.height = outputSize;
    const outputContext = outputCanvas.getContext("2d");
    const ratio = outputSize / previewSize;

    outputContext.fillStyle = "#ffffff";
    outputContext.fillRect(0, 0, outputSize, outputSize);
    outputContext.drawImage(
      state.image,
      state.offsetX * ratio,
      state.offsetY * ratio,
      state.image.width * state.scale * ratio,
      state.image.height * state.scale * ratio
    );

    const blob = await new Promise((resolve) => outputCanvas.toBlob(resolve, outputType, outputQuality));
    if (!blob) {
      setStatus(state.input, "Зураг боловсруулах үед алдаа гарлаа.", true);
      closeCropper(true);
      return;
    }

    const baseName = (state.file.name || "counselor").replace(/\.[^.]+$/, "");
    const fileName = `${baseName}-cropped.jpg`;
    const croppedFile = new File([blob], fileName, { type: outputType, lastModified: Date.now() });

    setInputFile(state.input, croppedFile);
    setStatus(state.input, `Тайрч жижигрүүлсэн зураг бэлэн боллоо: ${formatBytes(croppedFile.size)}`, false);
    closeCropper(false);
  }

  zoomInput.addEventListener("input", () => {
    updateScale(Number(zoomInput.value) / 100);
  });

  function startDrag(clientX, clientY) {
    state.dragging = true;
    state.dragX = clientX;
    state.dragY = clientY;
    canvas.classList.add("dragging");
  }

  function moveDrag(clientX, clientY) {
    if (!state.dragging) {
      return;
    }
    state.offsetX += clientX - state.dragX;
    state.offsetY += clientY - state.dragY;
    state.dragX = clientX;
    state.dragY = clientY;
    clampOffsets();
    renderPreview();
  }

  function endDrag() {
    state.dragging = false;
    canvas.classList.remove("dragging");
  }

  canvas.addEventListener("mousedown", (event) => startDrag(event.clientX, event.clientY));
  window.addEventListener("mousemove", (event) => moveDrag(event.clientX, event.clientY));
  window.addEventListener("mouseup", endDrag);

  canvas.addEventListener("touchstart", (event) => {
    const touch = event.touches[0];
    if (!touch) {
      return;
    }
    startDrag(touch.clientX, touch.clientY);
  }, { passive: true });

  window.addEventListener("touchmove", (event) => {
    const touch = event.touches[0];
    if (!touch) {
      return;
    }
    moveDrag(touch.clientX, touch.clientY);
  }, { passive: true });
  window.addEventListener("touchend", endDrag);

  applyButton.addEventListener("click", applyCrop);
  cancelButton.addEventListener("click", () => closeCropper(true));
  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeCropper(true);
    }
  });

  inputs.forEach((input) => {
    clearStatus(input);
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) {
        clearStatus(input);
        return;
      }

      try {
        const image = await loadImage(file);
        if (!shouldCrop(file, image)) {
          setStatus(input, `Зураг сонгогдлоо: ${formatBytes(file.size)}`, false);
          return;
        }

        setStatus(input, "Зураг том байна. Илгээхээс өмнө тайрах шаардлагатай.", true);
        openCropper(input, file, image);
      } catch (error) {
        input.value = "";
        setStatus(input, "Зургийг унших боломжгүй байна. Өөр файл сонгоно уу.", true);
      }
    });
  });
})();
