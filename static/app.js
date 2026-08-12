
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let selectedFile = null;
let designRefFile = null;
let designPhotoFiles = [];
let linkedDraftId = null;

function switchView(id) {
  $$(".nav").forEach((x) => x.classList.toggle("active", x.dataset.view === id));
  $$(".view").forEach((x) => x.classList.toggle("active", x.id === id));
  if (id === "library") loadLibrary();
  if (id === "contentlib") loadContentLibrary();
  if (id === "designlib") loadDesignLibrary();
}

$$(".nav").forEach((b) => {
  b.onclick = () => switchView(b.dataset.view);
});

$$(".tab").forEach((b) => {
  b.onclick = () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $$(".tabpane").forEach((x) => x.classList.remove("active"));
    $("#tab-" + b.dataset.tab).classList.add("active");
  };
});

$("#fileInput").onchange = (e) => {
  selectedFile = e.target.files[0];
  $("#fileMeta").textContent = selectedFile
    ? `${selectedFile.name} · ${(selectedFile.size / 1024 / 1024).toFixed(1)} MB`
    : "";
};

function esc(s = "") {
  return String(s).replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[m]));
}

function loading(sel, on) {
  $(sel).classList.toggle("hidden", !on);
}

function showErr(sel, msg) {
  $(sel).innerHTML = `<div class="error">${esc(msg)}</div>`;
}

function parseArray(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function buildWriterContext(i) {
  const angles = parseArray(i.content_angles);
  return [
    `CORE INSIGHT:\n${i.core_insight || ""}`,
    i.summary ? `SUMMARY:\n${i.summary}` : "",
    i.audience ? `AUDIENCE:\n${i.audience}` : "",
    i.tension ? `TENSION / DESIRE:\n${i.tension}` : "",
    angles.length ? `CONTENT ANGLES:\n- ${angles.join("\n- ")}` : ""
  ].filter(Boolean).join("\n\n");
}

function renderInsight(d) {
  const i = d.insight || {};
  const angles = parseArray(i.content_angles)
    .map((x) => `<div class="chip">${esc(x)}</div>`)
    .join("");
  const hooks = parseArray(i.hooks)
    .map((x) => `<div class="chip">${esc(x)}</div>`)
    .join("");
  const ctx = encodeURIComponent(buildWriterContext(i));

  $("#result").innerHTML = `
    <div class="result-card card">
      <div class="kicker">Core insight</div>
      <div class="core">${esc(i.core_insight || "")}</div>

      <button class="write-btn js-write-insight" data-context="${ctx}">
        ✎ Viết ngay 2 phiên bản
      </button>

      <div class="cols" style="margin-top:14px">
        <div class="mini"><b>AUDIENCE</b><p>${esc(i.audience || "")}</p></div>
        <div class="mini"><b>TENSION / DESIRE</b><p>${esc(i.tension || "")}</p></div>
      </div>

      <div style="margin-top:20px">
        <div class="kicker">Content angles</div>
        <div class="angle-list">${angles}</div>
      </div>

      <div style="margin-top:20px">
        <div class="kicker">Hooks</div>
        <div class="angle-list">${hooks}</div>
      </div>
    </div>`;
}

$("#analyzeText").onclick = async () => {
  const text = $("#textInput").value.trim();
  if (!text) return showErr("#result", "Hãy nhập nội dung.");

  loading("#loading", true);
  $("#result").innerHTML = "";

  try {
    const r = await fetch("/api/analyze-text", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text, name: $("#textName").value})
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Có lỗi");
    renderInsight(d);
  } catch (e) {
    showErr("#result", e.message);
  } finally {
    loading("#loading", false);
  }
};

$("#analyzeFile").onclick = async () => {
  if (!selectedFile) return showErr("#result", "Hãy chọn ảnh hoặc video.");

  loading("#loading", true);
  $("#result").innerHTML = "";

  try {
    const fd = new FormData();
    fd.append("file", selectedFile);

    const r = await fetch("/api/analyze-file", {
      method: "POST",
      body: fd
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Có lỗi");
    renderInsight(d);
  } catch (e) {
    showErr("#result", e.message);
  } finally {
    loading("#loading", false);
  }
};

async function loadLibrary() {
  const q = $("#search").value.trim();
  const r = await fetch("/api/insights?q=" + encodeURIComponent(q));
  const rows = await r.json();

  $("#libraryGrid").innerHTML = rows.length
    ? rows.map((x) => {
        const tags = parseArray(x.tags);
        const ctx = encodeURIComponent(buildWriterContext(x));

        return `
          <article class="lib" data-id="${x.id}">
            <div class="lib-top">
              <span>${esc((x.source_type || "").toUpperCase())} · ${esc(x.source_name || "")}</span>
              <span>${esc((x.created_at || "").slice(0, 10))}</span>
            </div>

            <h3>${esc(x.core_insight || "")}</h3>

            <div class="tags">
              ${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}
            </div>

            <button class="write-btn js-write-insight" data-context="${ctx}">
              ✎ Viết ngay 2 phiên bản
            </button>

            <footer>
              <select class="js-status">
                ${["New", "Approved", "Used", "Archived"]
                  .map((s) => `<option ${x.status === s ? "selected" : ""}>${s}</option>`)
                  .join("")}
              </select>
              <button class="delete js-delete">Xóa</button>
            </footer>
          </article>`;
      }).join("")
    : `<div class="hint">Chưa có insight nào.</div>`;
}

window.openWriter = (text) => {
  $("#writerInsight").value = text;
  switchView("writer");
  window.scrollTo(0, 0);
};

window.openWriterAndGenerate = async (text) => {
  $("#writerInsight").value = text;
  switchView("writer");
  window.scrollTo(0, 0);
  await generateContentNow();
};

document.addEventListener("click", async (event) => {
  const writeButton = event.target.closest(".js-write-insight");
  if (writeButton) {
    event.preventDefault();
    const context = decodeURIComponent(writeButton.dataset.context || "");
    await window.openWriterAndGenerate(context);
    return;
  }

  const deleteButton = event.target.closest(".js-delete");
  if (deleteButton) {
    event.preventDefault();
    const card = deleteButton.closest(".lib");
    const id = card?.dataset.id;
    if (!id || !confirm("Xóa insight này?")) return;

    await fetch(`/api/insights/${id}`, { method: "DELETE" });
    await loadLibrary();
  }
});

document.addEventListener("change", async (event) => {
  const statusSelect = event.target.closest(".js-status");
  if (!statusSelect) return;

  const card = statusSelect.closest(".lib");
  const id = card?.dataset.id;
  if (!id) return;

  await fetch(`/api/insights/${id}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: statusSelect.value })
  });
});



$("#refresh").onclick = loadLibrary;
$("#search").oninput = () => {
  clearTimeout(window._searchTimer);
  window._searchTimer = setTimeout(loadLibrary, 250);
};

async function generateContentNow() {
  const insight = $("#writerInsight").value.trim();
  if (!insight) return showErr("#writerResult", "Hãy nhập insight.");

  loading("#writerLoading", true);
  $("#writerResult").innerHTML = "";

  try {
    const r = await fetch("/api/write-content", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        insight,
        platform: $("#writerPlatform").value,
        objective: $("#writerObjective").value,
        extra_request: $("#writerExtra").value
      })
    });

    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Có lỗi");

    $("#writerResult").innerHTML = [d.short_hook || {}, d.sales_cta || {}]
      .map((x, i) => `
        <div class="content-version card" data-draft-id="${x.draft_id || ""}">
          <div class="kicker">Version ${i + 1}</div>
          <h3>${esc(x.title || "")}</h3>
          <div class="content-body">${esc(x.content || "")}</div>
          <div class="content-actions">
            <button class="copy-btn" data-copy="${encodeURIComponent(x.content || "")}">Copy</button>
            <button class="create-image-btn" data-draft-id="${x.draft_id || ""}" data-content="${encodeURIComponent(x.content || "")}">◇ Tạo ảnh</button>
          </div>
        </div>`)
      .join("");

    $$(".copy-btn").forEach((b) => {
      b.onclick = () => navigator.clipboard.writeText(decodeURIComponent(b.dataset.copy));
    });
    $$(".create-image-btn").forEach((b) => {
      b.onclick = () => {
        linkedDraftId = parseInt(b.dataset.draftId || "0", 10) || null;
        const contentText = decodeURIComponent(b.dataset.content || "");
        $("#designInstruction").value = `Tạo visual/design phù hợp cho content sau:\n\n${contentText}\n\nƯu tiên visual hỗ trợ đúng thông điệp, không nhồi quá nhiều chữ.`;
        $("#linkedContentNotice").classList.remove("hidden");
        $("#linkedContentNotice").textContent = `Đang tạo ảnh cho Content #${linkedDraftId}. Ảnh tạo xong sẽ lưu trong Content Library.`;
        switchView("design");
        window.scrollTo(0,0);
      };
    });

  } catch (e) {
    showErr("#writerResult", e.message);
  } finally {
    loading("#writerLoading", false);
  }
}

$("#generateContent").onclick = generateContentNow;


function previewSingle(input, imgSel) {
  const f = input.files[0];
  if (!f) return null;
  const img = $(imgSel);
  img.src = URL.createObjectURL(f);
  img.parentElement.classList.add("has-image");
  return f;
}
$("#designRef").onchange = (e) => { designRefFile = previewSingle(e.target, "#refPreview"); };

function renderPhotoPreviews(files) {
  const grid = $("#photoPreviewGrid");
  const empty = $("#photoEmpty");
  const count = $("#photoCount");
  grid.innerHTML = "";
  if (!files.length) {
    empty.style.display = "grid";
    count.textContent = "";
    return;
  }
  empty.style.display = "none";
  count.textContent = `${files.length} ảnh đã chọn`;
  files.forEach((file, index) => {
    const item = document.createElement("div");
    item.className = "photo-thumb";
    item.innerHTML = `<img src="${URL.createObjectURL(file)}" alt="Photo ${index + 1}"><span>${index + 1}</span>`;
    grid.appendChild(item);
  });
}
$("#designPhotos").onchange = (e) => {
  designPhotoFiles = Array.from(e.target.files || []).slice(0, 10);
  renderPhotoPreviews(designPhotoFiles);
};

function gcd(a,b){a=Math.abs(a);b=Math.abs(b);while(b)[a,b]=[b,a%b];return a||1;}
function updateRatioDisplay(){
  const w=parseInt($("#designWidth").value||"0",10);
  const h=parseInt($("#designHeight").value||"0",10);
  if(!w||!h){$("#ratioDisplay").textContent="—";return;}
  const d=gcd(w,h);
  $("#ratioDisplay").textContent=`${w/d}:${h/d}`;
}
$("#designWidth").oninput=updateRatioDisplay;
$("#designHeight").oninput=updateRatioDisplay;

$$(".ratio-btn").forEach((btn)=>{
  btn.onclick=()=>{
    $$(".ratio-btn").forEach((b)=>b.classList.remove("active"));
    btn.classList.add("active");
    const presets={"2:1":[1600,800],"1:1":[1200,1200],"9:16":[1080,1920],"16:9":[1920,1080]};
    const [w,h]=presets[btn.dataset.ratio];
    $("#designWidth").value=w; $("#designHeight").value=h; updateRatioDisplay();
  };
});

$("#generateDesign").onclick=async()=>{
  const instruction=$("#designInstruction").value.trim();
  const width=parseInt($("#designWidth").value||"0",10);
  const height=parseInt($("#designHeight").value||"0",10);
  if(!designRefFile)return showErr("#designResult","Hãy upload ảnh reference design.");
  if(!designPhotoFiles.length)return showErr("#designResult","Hãy upload ít nhất 1 ảnh chụp bên mình.");
  if(!instruction)return showErr("#designResult","Hãy nhập yêu cầu thiết kế.");
  if(!width||!height||width<512||height<512||width>4096||height>4096)return showErr("#designResult","Width và Height phải từ 512 đến 4096 px.");

  loading("#designLoading",true); $("#designResult").innerHTML="";
  try{
    const fd=new FormData();
    fd.append("reference",designRefFile);
    designPhotoFiles.forEach((file)=>fd.append("photos",file));
    fd.append("instruction",instruction);
    fd.append("width",String(width));
    fd.append("height",String(height));
    if(linkedDraftId)fd.append("draft_id",String(linkedDraftId));
    const r=await fetch("/api/generate-design",{method:"POST",body:fd});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||"Có lỗi");
    const src=`data:${d.mime||"image/png"};base64,${d.image_base64}`;
    $("#designResult").innerHTML=`<div class="generated-design card"><div class="kicker">Generated design · ${d.width}×${d.height}px · ${d.photo_count} ảnh nguồn</div><img src="${src}" alt="Generated design"><br><a class="download-btn" href="${src}" download="design_${d.width}x${d.height}.png">↓ Lưu ảnh</a></div>`;
  }catch(e){showErr("#designResult",e.message)}
  finally{loading("#designLoading",false)}
};
updateRatioDisplay();


document.addEventListener("click", (event) => {
  const nav = event.target.closest('.nav[data-view="design"]');
  if (nav) {
    linkedDraftId = null;
    const notice = $("#linkedContentNotice");
    if (notice) {
      notice.classList.add("hidden");
      notice.textContent = "";
    }
  }
});

async function loadContentLibrary(){
  const r=await fetch("/api/content-library");
  const rows=await r.json();
  $("#contentLibraryGrid").innerHTML=rows.length?rows.map(x=>`
    <article class="content-lib-card card" data-id="${x.id}">
      <div class="lib-top"><span>${esc((x.platform||"").toUpperCase())} · ${esc(x.version_type||"")}</span><span>${esc((x.created_at||"").slice(0,10))}</span></div>
      <h3>${esc(x.title||"")}</h3>
      <div class="content-body clamp-content">${esc(x.content||"")}</div>
      ${x.has_image?`<img class="content-lib-image" src="/api/content-library/${x.id}/image" alt="Content design">`:`<div class="no-image-note">Chưa có ảnh cho content này.</div>`}
      <div class="content-actions">
        <button class="library-image-btn" data-id="${x.id}" data-content="${encodeURIComponent(x.content||"")}">${x.has_image?"◇ Tạo lại ảnh":"◇ Tạo ảnh"}</button>
        <select class="content-status">${["Draft","Approved","Posted","Archived"].map(s=>`<option ${x.status===s?"selected":""}>${s}</option>`).join("")}</select>
      </div>
    </article>`).join(""):`<div class="hint">Chưa có content nào.</div>`;

  $$(".library-image-btn").forEach(b=>b.onclick=()=>{
    linkedDraftId=parseInt(b.dataset.id||"0",10)||null;
    const contentText=decodeURIComponent(b.dataset.content||"");
    $("#designInstruction").value=`Tạo visual/design phù hợp cho content sau:\n\n${contentText}\n\nƯu tiên visual hỗ trợ đúng thông điệp, không nhồi quá nhiều chữ.`;
    $("#linkedContentNotice").classList.remove("hidden");
    $("#linkedContentNotice").textContent=`Đang tạo ảnh cho Content #${linkedDraftId}. Ảnh tạo xong sẽ lưu trong Content Library.`;
    switchView("design");window.scrollTo(0,0);
  });
  $$(".content-status").forEach(s=>s.onchange=async()=>{
    const id=s.closest(".content-lib-card").dataset.id;
    await fetch(`/api/content-library/${id}/status`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:s.value})});
  });
}

async function loadDesignLibrary(){
  const r=await fetch("/api/design-library");
  const rows=await r.json();
  $("#designLibraryGrid").innerHTML=rows.length?rows.map(x=>`
    <article class="design-lib-card card">
      <img src="/api/design-library/${x.id}/image" alt="Design">
      <div class="design-lib-meta">
        <div class="kicker">${x.width}×${x.height}px · ${x.photo_count} ảnh nguồn</div>
        <p>${esc(x.instruction||"")}</p>
      </div>
    </article>`).join(""):`<div class="hint">Chưa có design độc lập nào.</div>`;
}
